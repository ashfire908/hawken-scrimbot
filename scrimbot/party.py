# -*- coding: utf-8 -*-

import logging
import threading
import time
import uuid
from hawkenapi.sleekxmpp.party import CancelCode
from scrimbot.plugins.base import CommandType
from scrimbot.reservations import ReservationResult
from scrimbot.util import enum

DeploymentState = enum(IDLE=0, MATCHMAKING=1, DEPLOYING=2, DEPLOYED=3)

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
    _deploy_time = 12

    def __init__(self, client, xmpp, config, cache, api):
        self.client = client
        self.xmpp = xmpp
        self.config = config
        self.cache = cache
        self.api = api

        self.guid = None
        self._init_party()

    def _init_party(self):
        self.joined = False
        self.players = set()
        self.reservation = None

        self.state = DeploymentState.IDLE
        self.create_time = None
        try:
            if self._thread_timer is not None:
                self._thread_timer.cancel()
        except AttributeError:
            pass
        self._thread_timer = None
        self._thread_deploy = None

    def _setup_party(self, party):
        self.guid = party
        self.create_time = time.time()

    def _room_jid(self):
        return "{0}@{1}".format(self.guid, self.xmpp.party_server)

    def _get_callsign(self):
        return self.xmpp.plugin["hawken_party"].our_callsign(self._room_jid())

    def _register_events(self):
        self.xmpp.add_event_handler("muc::%s::got_online" % self._room_jid(), self._handle_online)
        self.xmpp.add_event_handler("muc::%s::got_offline" % self._room_jid(), self._handle_offline)
        self.xmpp.add_event_handler("muc::%s::message" % self._room_jid(), self._handle_message)
        self.xmpp.add_event_handler("session_end", self._handle_session_end)

    def _unregister_events(self):
        self.xmpp.del_event_handler("muc::%s::got_online" % self._room_jid(), self._handle_online)
        self.xmpp.del_event_handler("muc::%s::got_offline" % self._room_jid(), self._handle_offline)
        self.xmpp.del_event_handler("muc::%s::message" % self._room_jid(), self._handle_message)
        self.xmpp.del_event_handler("session_end", self._handle_session_end)

    def _handle_online(self, presence):
        # Ignore the bot
        if presence["muc"]["nick"] == self._get_callsign():
            return

        # Add the player to the list
        self.players.add(presence["muc"]["jid"].user)

        # Stop any active deployment
        self.abort(CancelCode.MEMBERJOIN)

    def _handle_offline(self, presence):
        # Ignore ourselves
        if presence["muc"]["nick"] == self._get_callsign():
            return

        # Remove the player to the list
        self.players.remove(presence["muc"]["jid"].user)

        # Stop any active deployment
        self.abort(CancelCode.MEMBERLEFT)

    def _handle_message(self, message):
        # Check if we sent this message
        if message["from"].resource != self._get_callsign():
            # Check if there is party data attached to this message
            if "partymemberdata" in message:
                # Update the party state
                if message["partymemberdata"]["infoName"] == "PartyMatchmakingStart":
                    self.state = DeploymentState.MATCHMAKING
                    if not self.is_leader():
                        self.message("Leaving the party to avoid issues with matchmaking the bot.")
                        self.leave()
                elif message["partymemberdata"]["infoName"] == "PartyMatchmakingCancel":
                    self.state = DeploymentState.IDLE
                elif message["partymemberdata"]["infoName"] == "DeployPartyData":
                    self.state = DeploymentState.DEPLOYING
                elif message["partymemberdata"]["infoName"] == "DeployCancelData":
                    self.state = DeploymentState.IDLE

    def _handle_session_end(self, event):
        if self.joined:
            # "Leave" the party
            self.leave()

    def _thread_timer_start(self):
        self._thread_timer = threading.Timer(Party._deploy_time, self._complete_deployment)
        self._thread_timer.start()

    def _thread_deploy_start(self):
        self._thread_deploy = threading.Thread(target=self._handle_deployment)
        self._thread_deploy.start()

    def _start_matchmaking(self, reservation):
        assert self.state == DeploymentState.IDLE
        assert self.is_leader()

        # Set the reservation
        self.reservation = reservation

        # Send the notice
        self.xmpp.plugin["hawken_party"].matchmaking_start(self._room_jid(), self.xmpp.boundjid)

        # Set the state to matchmaking
        self.state = DeploymentState.MATCHMAKING

        # Start the deployment thread
        self._thread_deploy_start()

    def _cancel_matchmaking(self, code):
        assert self.state == DeploymentState.MATCHMAKING
        assert self.is_leader()

        # Send the notice
        self.xmpp.plugin["hawken_party"].matchmaking_cancel(self._room_jid(), self.xmpp.boundjid, code)

        # Set the state back to idle
        self.state = DeploymentState.IDLE

    def _start_deployment(self):
        assert self.state == DeploymentState.MATCHMAKING
        assert self.is_leader()

        # Format the server info
        server_string = ";".join((self.reservation.advertisement["AssignedServerGuid"],
                                  self.reservation.advertisement["AssignedServerIp"],
                                  str(self.reservation.advertisement["AssignedServerPort"])))

        # Send the notice
        self.xmpp.plugin["hawken_party"].deploy_start(self._room_jid(), self.xmpp.boundjid, server_string)

        # Start deployment timer
        self._thread_timer_start()

        # Set the state to deploying
        self.state = DeploymentState.DEPLOYING

    def _cancel_deployment(self, code):
        assert self.state == DeploymentState.DEPLOYING
        assert self.is_leader()

        # Cancel the deployment timer
        if self._thread_timer is not None:
            self._thread_timer.cancel()

        # Send the notice
        self.xmpp.plugin["hawken_party"].deploy_cancel(self._room_jid(), self.xmpp.boundjid, code)

        # Set the state back to idle
        self.state = DeploymentState.IDLE

    def _complete_deployment(self):
        assert self.state == DeploymentState.DEPLOYING
        assert self.is_leader()

        # Set the party as deployed
        self.xmpp.plugin["hawken_party"].game_start(self._room_jid())

        # Set the state to deployed
        self.state = DeploymentState.DEPLOYED

    def _undo_deployment(self):
        assert self.state == DeploymentState.DEPLOYED
        assert self.is_leader()

        # Set the party as deployed
        self.xmpp.plugin["hawken_party"].game_end(self._room_jid())

        # Set the state to deployed
        self.state = DeploymentState.IDLE

    def _handle_deployment(self):
        # Poll the reservation
        result = self.reservation.poll()

        if result == ReservationResult.READY:
            self._start_deployment()
        elif result == ReservationResult.TIMEOUT:
            self.abort(CancelCode.NOMATCH)
        elif result == ReservationResult.NOTFOUND:
            self.xmpp.send_message(CommandType.PARTY, self._room_jid(), "Error: Could not retrieve advertisement - expired? This is a bug - please report it!")
            self.abort(CancelCode.PARTYCANCEL)
        elif result == ReservationResult.ERROR:
            self.xmpp.send_message(CommandType.PARTY, self._room_jid(), "Error: Failed to poll for reservation. This is a bug - please report it!")
            self.abort(CancelCode.PARTYCANCEL)

    @notjoined
    def create(self, party):
        # Init the party
        self._setup_party(party)

        # Register events with the bot
        self._register_events()

        # Create the party
        self.xmpp.plugin["hawken_party"].create(self._room_jid(), self.api.callsign)

        # Register with active parties
        self.client.active_parties[party] = self

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
        self.client.active_parties[party] = self

        # Mark as joined
        self.joined = True

    @joined
    def leave(self):
        # Stop the matchmaking
        self.abort(CancelCode.LEADERCANCEL)

        # Remove from active parties
        try:
            del self.client.active_parties[self.guid]
        except KeyError:
            pass

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
        # Get the target and callsign
        target = "{0}@{1}".format(user, self.xmpp.boundjid.host)
        callsign = self.cache.get_callsign(user)

        # Send the invite
        self.xmpp.plugin["hawken_party"].invite(self._room_jid(), self.xmpp.boundjid, target, callsign)

    @joined
    @requireleader
    def kick(self, user):
        # Get the callsign
        callsign = self.cache.get_callsign(user)

        # Make sure we aren't kicking ourselves
        if callsign == self._get_callsign():
            raise ValueError("Cannot kick ourself from a party")

        # Stop any active deployment
        self.abort(CancelCode.MEMBERKICK)

        # Send the kick
        self.xmpp.plugin["hawken_party"].kick(self._room_jid(), callsign)

    @joined
    def is_leader(self):
        return self.xmpp.plugin["hawken_party"].leader_get(self._room_jid()) == self._get_callsign()

    @joined
    def get_leader(self):
        return self.xmpp.plugin["hawken_party"].leader_get(self._room_jid())

    @joined
    @requireleader
    def set_leader(self, user):
        # Get the callsign
        callsign = self.cache.get_callsign(user)

        # Stop any active deployment
        self.abort(CancelCode.LEADERCHANGE)

        # Change the leader
        self.xmpp.plugin["hawken_party"].leader_set(self._room_jid(), callsign)

    @joined
    @requireleader
    def deploy(self, reservation):
        if self.state != DeploymentState.IDLE:
            raise ValueError("A deployment cannot be started while one is in progress.")

        # Start the deployment
        self._start_matchmaking(reservation)

    @joined
    def abort(self, code=CancelCode.PARTYCANCEL):
        if not self.is_leader():
            return False
        elif self.state == DeploymentState.MATCHMAKING:
            self._cancel_matchmaking(code)
        elif self.state == DeploymentState.DEPLOYING:
            self._cancel_deployment(code)
        else:
            return False

        # Cancel the reservation
        self.reservation.cancel()

        return True

    @staticmethod
    def generate_guid():
        return str(uuid.uuid4())

    @staticmethod
    def our_callsign(xmpp, room):
        return xmpp.plugin["hawken_party"].our_callsign(room)
