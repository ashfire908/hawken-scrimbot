# -*- coding: utf-8 -*-

import logging
import threading
from hawkenapi.sleekxmpp.party import CancelCode
from scrimbot.command import CommandType
from scrimbot.party import Party, joined, requireleader
from scrimbot.reservations import ReservationResult
from scrimbot.util import enum

DeploymentState = enum(IDLE=0, MATCHMAKING=1, DEPLOYING=2, DEPLOYED=3)

logger = logging.getLogger(__name__)


class ScrimParty(Party):
    _deploy_time = 12

    def _init_party(self):
        super()._init_party()
        self.reservation = None
        self.state = DeploymentState.IDLE

        try:
            if self._thread_timer is not None:
                self._thread_timer.cancel()
        except AttributeError:
            pass
        self._thread_timer = None
        self._thread_deploy = None

    def _handle_online(self, presence):
        # Stop any active deployment
        self.abort(CancelCode.MEMBERJOIN)

    def _handle_offline(self, presence):
        # Stop any active deployment
        self.abort(CancelCode.MEMBERLEFT)

    def _handle_message(self, message):
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

    def _thread_timer_start(self):
        self._thread_timer = threading.Timer(ScrimParty._deploy_time, self._complete_deployment)
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

    def leave(self):
        # Stop the matchmaking
        self.abort(CancelCode.LEADERCANCEL)

        super().leave()

    def kick(self, user):
        super().kick(user)

        # Stop any active deployment
        self.abort(CancelCode.MEMBERKICK)

    def set_leader(self, user):
        super().set_leader(user)

        # Stop any active deployment
        self.abort(CancelCode.LEADERCHANGE)

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
