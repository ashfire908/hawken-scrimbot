# -*- coding: utf-8 -*-

import logging
import time
import uuid
from sleekxmpp.plugins.xep_0045.muc import MUCJoinTimeout, MUCJoinError

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
        if not self.is_leader:
            raise ValueError("Not the leader of the party.")

        return f(self, *args, **kwargs)

    return leader_required


class Party:
    def __init__(self, party, config, api, cache, xmpp, guid, name):
        # Register handlers
        self.parties = party
        self.config = config
        self.api = api
        self.cache = cache
        self.xmpp = xmpp

        # Init party variables
        self.guid = guid
        self.name = name
        self.features = set()

        # Events
        self.events = {"joined", "left", "online", "offline", "message"}
        self.event_handlers = {}
        for event in self.events:
            self.event_handlers[event] = set()

        # Init state
        self._active = False
        self.joined = False
        self.players = set()
        self.join_time = None

    def __register_events(self):
        self.xmpp.add_event_handler("muc::%s::joined" % self.room_jid, self.__handle_joined)
        self.xmpp.add_event_handler("muc::%s::left" % self.room_jid, self.__handle_left)
        self.xmpp.add_event_handler("muc::%s::presence" % self.room_jid, self.__handle_presence)
        self.xmpp.add_event_handler("muc::%s::message" % self.room_jid, self.__handle_message)
        self.xmpp.add_event_handler("session_end", self.__handle_session_end)

    def __unregister_events(self):
        self.xmpp.del_event_handler("muc::%s::joined" % self.room_jid, self.__handle_joined)
        self.xmpp.del_event_handler("muc::%s::left" % self.room_jid, self.__handle_left)
        self.xmpp.del_event_handler("muc::%s::presence" % self.room_jid, self.__handle_presence)
        self.xmpp.del_event_handler("muc::%s::message" % self.room_jid, self.__handle_message)
        self.xmpp.del_event_handler("session_end", self.__handle_session_end)

    def __handle_joined(self, presence):
        # Setup party state
        self.joined = True
        self.join_time = time.time()

        # Trigger joined event
        for handler in self.event_handlers["joined"]:
            handler()

    def __handle_left(self, presence):
        # Reset party state
        self.joined = False
        self.players = set()
        self.join_time = None

        # Trigger left event
        for handler in self.event_handlers["left"]:
            handler()

    def __handle_presence(self, presence):
        # Ignore the bot
        if presence["muc"]["jid"].user == self.api.guid:
            return

        if presence["type"] == "unavailable":
            # Remove the player to the list
            self.players.remove(presence["muc"]["jid"].user)

            # Trigger offline event
            for handler in self.event_handlers["offline"]:
                handler(presence)
        elif presence["muc"]["jid"].user not in self.players:
            # Add the player to the list
            self.players.add(presence["muc"]["jid"].user)

            # Trigger online event
            for handler in self.event_handlers["online"]:
                handler(presence)

    def __handle_message(self, message):
        # Ignore the bot
        if message["from"].resource == self.callsign:
            return

        # Trigger message event
        for handler in self.event_handlers["message"]:
            handler(message)

    def __handle_session_end(self, event):
        # Reset party state
        self.joined = False
        self.players = set()
        self.join_time = None
        self.active = False

        # Unregister events
        self.__unregister_events()

        # Trigger left event
        for handler in self.event_handlers["left"]:
            handler()

    @property
    def room_jid(self):
        return "{0}@{1}".format(self.guid, self.xmpp.party_server)

    @property
    def callsign(self):
        return self.parties.get_callsign(self.room_jid)

    @property
    def active(self):
        return self._active

    @active.setter
    def active(self, value):
        if value and not self._active:
            # Register party
            self.parties.register(self)
        elif not value and self._active:
            # Unregister party
            self.parties.unregister(self)

        self._active = value

    @property
    def is_leader(self):
        if self.joined:
            return self.get_leader() == self.callsign
        else:
            return False

    @joined
    def get_leader(self):
        if joined:
            return self.xmpp.plugin["hawken_party"].get_leader(self.room_jid)
        else:
            return None

    @joined
    @requireleader
    def set_leader(self, user):
        # Change the leader
        self.xmpp.plugin["hawken_party"].set_leader(self.room_jid, self.xmpp.format_jid(user))

    def register_feature(self, feature):
        self.features.add(feature)

    def unregister_feature(self, feature):
        self.features.remove(feature)

    def register_event(self, event, handler):
        self.event_handlers[event].add(handler)

    def unregister_event(self, event, handler):
        self.event_handlers[event].remove(handler)

    @notjoined
    def create(self):
        # Register events
        self.__register_events()

        try:
            # Create the party
            self.xmpp.plugin["hawken_party"].create(self.room_jid, self.api.callsign)
        except (MUCJoinTimeout, MUCJoinError):
            # Unregister events
            self.__unregister_events()

            return False
        else:
            # Mark as active
            self.active = True

            return True

    @notjoined
    def join(self):
        # Register events
        self.__register_events()

        try:
            # Join the party
            self.xmpp.plugin["hawken_party"].join(self.room_jid, self.api.callsign)
        except (MUCJoinTimeout, MUCJoinError):
            # Unregister events
            self.__unregister_events()

            return False
        else:
            # Mark as active
            self.active = True

            return True

    @joined
    def leave(self):
        # Mark as inactive
        self.active = False

        # Leave the party
        self.xmpp.plugin["hawken_party"].leave(self.room_jid)

        # Unregister events
        self.__unregister_events()

    @joined
    def message(self, message):
        # Send the message
        self.xmpp.plugin["hawken_party"].message(self.room_jid, self.xmpp.boundjid, message)

    @joined
    def invite(self, user):
        # Get the callsign
        callsign = self.cache.get_callsign(user)

        # Send the invite
        self.xmpp.plugin["hawken_party"].invite(self.room_jid, self.xmpp.boundjid, self.xmpp.format_jid(user), callsign)

    @joined
    @requireleader
    def kick(self, user):
        # Make sure we aren't kicking ourselves
        if user == self.api.guid:
            raise ValueError("Cannot kick ourself from a party")

        # Get the callsign
        callsign = self.cache.get_callsign(user)

        # Send the kick
        self.xmpp.plugin["hawken_party"].kick(self.room_jid, callsign)

    @joined
    @requireleader
    def ban(self, user):
        # Make sure we aren't banning ourselves
        if user == self.api.guid:
            raise ValueError("Cannot ban ourself from a party")

        # Send the ban
        self.xmpp.plugin["hawken_party"].ban(self.room_jid, user)

    @joined
    @requireleader
    def unban(self, user):
        # Make sure we aren't banning ourselves
        if user == self.api.guid:
            raise ValueError("Cannot unban ourself from a party")

        # Send the unban
        self.xmpp.plugin["hawken_party"].unban(self.room_jid, user)


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

    def new(self, party, guid, name=None):
        return party(self, self.config, self.api, self.cache, self.xmpp, guid, name)

    def get_callsign(self, room):
        return self.xmpp.plugin["hawken_party"].get_callsign(room)

    @property
    def joined_rooms(self):
        return self.xmpp.plugin["hawken_party"].get_joined_rooms()

    @staticmethod
    def generate_guid():
        return str(uuid.uuid4())
