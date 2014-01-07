# -*- coding: utf-8 -*-

import logging
import time
import uuid

logger = logging.getLogger(__name__)


def joined(f):
    def join_required(self, *args, **kwargs):
        if not self.joined:
            raise ValueError("Party has not been joined yet.")

        return f(self, *args, **kwargs)

    return join_required


def notjoined(f):
    def notjoin_required(self, *args, **kwargs):
        if self.joined:
            raise ValueError("Party has already been joined.")

        return f(self, *args, **kwargs)

    return notjoin_required


def requireleader(f):
    def leader_required(self, *args, **kwargs):
        if not self.is_leader():
            raise ValueError("Not the leader of the party.")

        return f(self, *args, **kwargs)

    return leader_required


class Party:
    features = []

    def __init__(self, party, config, api, cache, xmpp):
        self.parties = party
        self.config = config
        self.api = api
        self.cache = cache
        self.xmpp = xmpp

        self.guid = None
        self._init_party()

    def __handle_presence(self, presence):
        # Ignore the bot
        if presence["muc"]["jid"].user == self.api.guid:
            return

        if presence["type"] == "unavailable":
            # Remove the player to the list
            self.players.remove(presence["muc"]["jid"].user)

            # User is offline
            self._handle_offline(presence)
        elif presence["muc"]["jid"].user not in self.players:
            # Add the player to the list
            self.players.add(presence["muc"]["jid"].user)

            # User is online
            self._handle_online(presence)

    def __handle_message(self, message):
        # Ignore the bot
        if message["from"].resource != self._get_callsign():
            return

        self._handle_message(message)

    def __handle_session_end(self, event):
        self._handle_session_end(event)

    def _init_party(self):
        self.joined = False
        self.players = set()
        self.create_time = None

    def _setup_party(self, party):
        self.guid = party
        self.create_time = time.time()

    def _room_jid(self):
        return "{0}@{1}".format(self.guid, self.xmpp.party_server)

    def _get_callsign(self):
        return self.parties.get_callsign(self._room_jid())

    def _register_events(self):
        self.xmpp.add_event_handler("muc::%s::presence" % self._room_jid(), self.__handle_presence)
        self.xmpp.add_event_handler("muc::%s::message" % self._room_jid(), self.__handle_message)
        self.xmpp.add_event_handler("session_end", self.__handle_session_end)

    def _unregister_events(self):
        self.xmpp.del_event_handler("muc::%s::presence" % self._room_jid(), self.__handle_presence)
        self.xmpp.del_event_handler("muc::%s::message" % self._room_jid(), self.__handle_message)
        self.xmpp.del_event_handler("session_end", self.__handle_session_end)

    def _handle_online(self, presence):
        pass

    def _handle_offline(self, presence):
        pass

    def _handle_message(self, message):
        pass

    def _handle_session_end(self, event):
        if self.joined:
            # Leave the party
            self.leave()

    @notjoined
    def create(self, party):
        # Init the party
        self._setup_party(party)

        # Register events with the bot
        self._register_events()

        # Create the party
        self.xmpp.plugin["hawken_party"].create(self._room_jid(), self.api.callsign)

        # Register with active parties
        self.parties.register(self)

        # Mark as joined
        self.joined = True

    @notjoined
    def join(self, party):
        # Init the party
        self._setup_party(party)

        # Register events with the bot
        self._register_events()

        # Join the party
        self.xmpp.plugin["hawken_party"].join(self._room_jid(), self.api.callsign)

        # Register with active parties
        self.parties.register(self)

        # Mark as joined
        self.joined = True

    @joined
    def leave(self):
        # Remove from active parties
        self.parties.unregister(self)

        # Leave the party
        self.xmpp.plugin["hawken_party"].leave(self._room_jid())

        # Reset the state
        self._init_party()

    @joined
    def message(self, message):
        # Send the message
        self.xmpp.plugin["hawken_party"].message(self._room_jid(), self.xmpp.boundjid, message)

    @joined
    def invite(self, user):
        # Get the callsign
        callsign = self.cache.get_callsign(user)

        # Send the invite
        self.xmpp.plugin["hawken_party"].invite(self._room_jid(), self.xmpp.boundjid, self.xmpp.format_jid(user), callsign)

    @joined
    @requireleader
    def kick(self, user):
        # Make sure we aren't kicking ourselves
        if user == self.api.guid:
            raise ValueError("Cannot kick ourself from a party")

        # Get the callsign
        callsign = self.cache.get_callsign(user)

        # Send the kick
        self.xmpp.plugin["hawken_party"].kick(self._room_jid(), callsign)

    @joined
    @requireleader
    def ban(self, user):
        # Make sure we aren't banning ourselves
        if user == self.api.guid:
            raise ValueError("Cannot ban ourself from a party")

        # Send the ban
        self.xmpp.plugin["hawken_party"].ban(self._room_jid(), user)

    @joined
    @requireleader
    def unban(self, user):
        # Make sure we aren't banning ourselves
        if user == self.api.guid:
            raise ValueError("Cannot unban ourself from a party")

        # Send the unban
        self.xmpp.plugin["hawken_party"].unban(self._room_jid(), user)

    @joined
    def is_leader(self):
        return self.get_leader() == self._get_callsign()

    @joined
    def get_leader(self):
        return self.xmpp.plugin["hawken_party"].get_leader(self._room_jid())

    @joined
    @requireleader
    def set_leader(self, user):
        # Change the leader
        self.xmpp.plugin["hawken_party"].set_leader(self._room_jid(), self.xmpp.format_jid(user))

    @staticmethod
    def generate_guid():
        return str(uuid.uuid4())


class PartyManager:
    def __init__(self, config, api, cache, xmpp):
        self.config = config
        self.api = api
        self.cache = cache
        self.xmpp = xmpp

        self.active = {}

    def register(self, party):
        self.active[party.guid] = party

    def unregister(self, party):
        try:
            del self.active[party.guid]
        except KeyError:
            pass

    def new(self, party, *args, **kwargs):
        return party(self, self.config, self.api, self.cache, self.xmpp, *args, **kwargs)

    def get_callsign(self, room):
        return self.xmpp.plugin["hawken_party"].get_callsign(room)

    @property
    def joined_rooms(self):
        return self.xmpp.plugin["hawken_party"].get_joined_rooms()
