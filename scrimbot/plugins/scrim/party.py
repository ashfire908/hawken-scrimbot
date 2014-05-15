# -*- coding: utf-8 -*-

import logging
import threading
from hawkenapi.exceptions import InvalidResponse
from hawkenapi.sleekxmpp.party import CancelCode
from hawkenapi.sleekxmpp.stanza import MemberDataCodes
from scrimbot.command import CommandType
from scrimbot.party import Party, joined, requireleader
from scrimbot.reservations import ReservationResult
from scrimbot.util import enum

DeploymentState = enum(IDLE=0, MATCHMAKING=1, DEPLOYING=2, DEPLOYED=3)

logger = logging.getLogger(__name__)


class ScrimParty(Party):
    def __init__(self, party, config, api, cache, xmpp, guid, name):
        super().__init__(party, config, api, cache, xmpp, guid, name)

        # Init
        self.register_feature("scrim")
        self.reservation = None
        self.countdown = None
        self.state = DeploymentState.IDLE
        self._thread_timer = None
        self._thread_deploy = None

        # Register events
        self.register_event("joined", self._handle_joined)
        self.register_event("left", self._handle_left)
        self.register_event("online", self._handle_online)
        self.register_event("offline", self._handle_offline)
        self.register_event("partymemberdata", self._handle_partymemberdata)

    def _handle_joined(self):
        if not self.is_leader:
            # Bot needs leader access for scrims
            self.message("Please grant me leader status or tell me to leave.")

    def _handle_left(self):
        # Cancel any pending reservation
        if self.reservation is not None:
            self.reservation.cancel()

        # Reset the state
        self.reservation = None
        self.countdown = None
        self.state = DeploymentState.IDLE

        try:
            if self._thread_timer is not None:
                self._thread_timer.cancel()
        except AttributeError:
            pass
        self._thread_timer = None
        self._thread_deploy = None

    def _handle_online(self, presence):
        if self.joined:
            # Stop any active deployment
            self.abort(CancelCode.member_join)

    def _handle_offline(self, presence):
        if self.joined:
            # Stop any active deployment
            self.abort(CancelCode.member_left)

    def _handle_partymemberdata(self, message):
        # Update the party state
        if message["partymemberdata"]["infoName"] == MemberDataCodes.matchmaking_start:
            self.state = DeploymentState.MATCHMAKING
            if not self.is_leader:
                self.message("Leaving the party to avoid issues with matchmaking the bot.")
                self.leave()
        elif message["partymemberdata"]["infoName"] == MemberDataCodes.matchmaking_cancel:
            self.state = DeploymentState.IDLE
        elif message["partymemberdata"]["infoName"] == MemberDataCodes.deploy_party:
            self.state = DeploymentState.DEPLOYING
        elif message["partymemberdata"]["infoName"] == MemberDataCodes.deploy_cancel:
            self.state = DeploymentState.IDLE
        elif message["partymemberdata"]["infoName"] == MemberDataCodes.travel_request:
            self.state = DeploymentState.DEPLOYED

    def _thread_timer_start(self):
        self._thread_timer = threading.Timer(self.countdown, self._complete_deployment)
        self._thread_timer.start()

    def _thread_deploy_start(self, countdown):
        self._thread_deploy = threading.Thread(target=self._handle_deployment, args=(self._start_deployment, ))
        self._thread_deploy.start()

    def _start_matchmaking(self, reservation, countdown):
        assert self.state == DeploymentState.IDLE
        assert self.is_leader

        # Set the reservation
        self.reservation = reservation
        self.countdown = countdown

        # Send the notice
        self.xmpp.plugin["hawken_party"].matchmaking_start(self.room_jid, self.xmpp.boundjid)

        # Set the state to matchmaking
        self.state = DeploymentState.MATCHMAKING

        # Start the deployment thread
        self._thread_deploy_start(countdown)

    def _cancel_matchmaking(self, code):
        assert self.state == DeploymentState.MATCHMAKING
        assert self.is_leader

        # Send the notice
        self.xmpp.plugin["hawken_party"].matchmaking_cancel(self.room_jid, self.xmpp.boundjid, code)

        # Set the state back to idle
        self.state = DeploymentState.IDLE

    def _start_deployment(self):
        assert self.state == DeploymentState.MATCHMAKING
        assert self.is_leader

        # Send the notice
        self.xmpp.plugin["hawken_party"].deploy_start(self.room_jid, self.xmpp.boundjid, 10)

        # Start deployment timer
        self._thread_timer_start()

        # Set the state to deploying
        self.state = DeploymentState.DEPLOYING

    def _cancel_deployment(self, code):
        assert self.state == DeploymentState.DEPLOYING
        assert self.is_leader

        # Cancel the deployment timer
        if self._thread_timer is not None:
            self._thread_timer.cancel()

        # Send the notice
        self.xmpp.plugin["hawken_party"].deploy_cancel(self.room_jid, self.xmpp.boundjid, code)

        # Set the state back to idle
        self.state = DeploymentState.IDLE

    def _complete_deployment(self):
        assert self.state == DeploymentState.DEPLOYING
        assert self.is_leader

        # Perform a travel request
        self.xmpp.plugin["hawken_party"].travel_request(self.room_jid, self.xmpp.boundjid,
                                                        self.reservation.advertisement["AssignedServerGuid"],
                                                        self.reservation.advertisement["AssignedServerIp"],
                                                        self.reservation.advertisement["AssignedServerPort"],
                                                        True)

        # Set the party as deployed
        self.xmpp.plugin["hawken_party"].game_start(self.room_jid)

        # Set the state to deployed
        self.state = DeploymentState.DEPLOYED

    def _change_server(self, reservation):
        self.reservation = reservation

        def server_callback():
            assert self.state == DeploymentState.DEPLOYED
            assert self.is_leader

            # Perform a travel request
            self.xmpp.plugin["hawken_party"].travel_request(self.room_jid, self.xmpp.boundjid,
                                                            self.reservation.advertisement["AssignedServerGuid"],
                                                            self.reservation.advertisement["AssignedServerIp"],
                                                            self.reservation.advertisement["AssignedServerPort"],
                                                            True)

            # Set the party as deployed
            self.xmpp.plugin["hawken_party"].game_start(self.room_jid)

            # Set the state to deployed
            self.state = DeploymentState.DEPLOYED

        self._handle_deployment(server_callback)

    def _undo_deployment(self):
        assert self.state == DeploymentState.DEPLOYED
        assert self.is_leader

        # Set the party as deployed
        self.xmpp.plugin["hawken_party"].game_end(self.room_jid)

        # Set the state to deployed
        self.state = DeploymentState.IDLE

    def _handle_deployment(self, callback):
        # Poll the reservation
        try:
            result = self.reservation.poll()
        except InvalidResponse as e:
            self.xmpp.send_message(CommandType.PARTY, self.room_jid, "Error: Reservation returned invalid response - {0}.".format(e))
            self.abort(CancelCode.none)
        except:
            self.xmpp.send_message(CommandType.PARTY, self.room_jid, "Error: Failed to poll for reservation. This is a bug - please report it!")
            self.abort(CancelCode.none)
        else:
            if result == ReservationResult.READY:
                callback()
            elif result == ReservationResult.TIMEOUT:
                self.abort(CancelCode.match_failure)
            elif result == ReservationResult.NOTFOUND:
                self.xmpp.send_message(CommandType.PARTY, self.room_jid, "Error: Could not retrieve advertisement - expired? This is a bug - please report it!")
                self.abort(CancelCode.none)
            elif result == ReservationResult.ERROR:
                self.xmpp.send_message(CommandType.PARTY, self.room_jid, "Error: Failed to poll for reservation. This is a bug - please report it!")
                self.abort(CancelCode.none)

    def leave(self):
        # Stop the matchmaking
        self.abort(CancelCode.leader_action)

        super().leave()

    def kick(self, user):
        # Stop any active deployment
        self.abort(CancelCode.member_kick)

        super().kick(user)

    def set_leader(self, user):
        # Stop any active deployment
        self.abort(CancelCode.leader_change)

        super().set_leader(user)

    @joined
    @requireleader
    def deploy(self, reservation, countdown=10):
        # Start the deployment
        if self.state == DeploymentState.IDLE:
            self._start_matchmaking(reservation, countdown)
        elif self.state == DeploymentState.DEPLOYED:
            self._change_server(reservation)
        else:
            raise ValueError("A deployment cannot be started while one is in progress.")

    @joined
    def abort(self, code=CancelCode.none):
        if not self.is_leader:
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
