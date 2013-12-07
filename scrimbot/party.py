# -*- coding: utf-8 -*-

import logging
import threading
import time
import uuid
import hawkenapi.exceptions
from hawkenapi.sleekxmpp.party import CancelCode
from scrimbot.plugins.base import CommandType
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


class Party:
    _deploy_time = 12

    def __init__(self, xmpp, config, cache, api):
        self.xmpp = xmpp
        self.config = config
        self.cache = cache
        self.api = api

        self.joined = False
        self.guid = None
        self.players = set()
        self.advertisement = None

        self.state = DeploymentState.IDLE
        self._thread_timer = None
        self._thread_deploy = None

    def _init_party(self, party):
        self.guid = party

    def _clear_party(self):
        self.guid = None
        self.players = set()
        self.state = DeploymentState.IDLE
        if self._thread_timer is not None:
            self._thread_timer.cancel()
        self._thread_timer = None
        self._thread_deploy = None
        self.joined = False
        self.advertisement = None

    def _room_jid(self):
        return "{0}@{1}".format(self.guid, self.xmpp.party_server)

    def _register_events(self):
        self.xmpp.add_event_handler("muc::%s::got_online" % self._room_jid(), self._handle_online)
        self.xmpp.add_event_handler("muc::%s::got_offline" % self._room_jid(), self._handle_offline)

    def _unregister_events(self):
        self.xmpp.del_event_handler("muc::%s::got_online" % self._room_jid(), self._handle_online)
        self.xmpp.del_event_handler("muc::%s::got_offline" % self._room_jid(), self._handle_offline)

    def _handle_online(self, presence):
        # Ignore the bot
        if presence["muc"]["nick"] == self.api.callsign:
            return

        # Add the player to the list
        self.players.add(presence["muc"]["jid"].user)

        # Stop any active deployment
        self.abort(CancelCode.MEMBERJOIN)

    def _handle_offline(self, presence):
        # Ignore ourselves
        if presence["muc"]["nick"] == self.api.callsign:
            return

        # Remove the player to the list
        self.players.remove(presence["muc"]["jid"].user)

        # Stop any active deployment
        self.abort(CancelCode.MEMBERLEFT)

    def _thread_timer_start(self):
        self._thread_timer = threading.Timer(Party._deploy_time, self._complete_deployment)
        self._thread_timer.start()

    def _thread_deploy_start(self, poll_limit):
        self._thread_deploy = threading.Thread(target=self._handle_deployment, args=[poll_limit])
        self._thread_deploy.start()

    def _start_matchmaking(self, advertisement, poll_limit):
        assert self.state == DeploymentState.IDLE

        # Set the advertisement
        self.advertisement = advertisement

        # Send the notice
        self.xmpp.plugin["hawken_party"].matchmaking_start(self._room_jid(), self.xmpp.boundjid)

        # Set the state to matchmaking
        self.state = DeploymentState.MATCHMAKING

        # Start the deployment thread
        self._thread_deploy_start(poll_limit)

    def _cancel_matchmaking(self, code):
        assert self.state == DeploymentState.MATCHMAKING

        # Send the notice
        self.xmpp.plugin["hawken_party"].matchmaking_cancel(self._room_jid(), self.xmpp.boundjid, code)

        # Set the state back to idle
        self.state = DeploymentState.IDLE

    def _start_deployment(self, advertisement_info):
        assert self.state == DeploymentState.MATCHMAKING

        # Format the server info
        server_string = ";".join((advertisement_info["AssignedServerGuid"], advertisement_info["AssignedServerIp"],
                                  str(advertisement_info["AssignedServerPort"])))

        # Send the notice
        self.xmpp.plugin["hawken_party"].deploy_start(self._room_jid(), self.xmpp.boundjid, server_string)

        # Start deployment timer
        self._thread_timer_start()

        # Set the state to deploying
        self.state = DeploymentState.DEPLOYING

    def _cancel_deployment(self, code):
        assert self.state == DeploymentState.DEPLOYING

        # Cancel the deployment timer
        if self._thread_timer is not None:
            self._thread_timer.cancel()

        # Send the notice
        self.xmpp.plugin["hawken_party"].deploy_cancel(self._room_jid(), self.xmpp.boundjid, code)

        # Set the state back to idle
        self.state = DeploymentState.IDLE

    def _complete_deployment(self):
        assert self.state == DeploymentState.DEPLOYING

        # Set the party as deployed
        self.xmpp.plugin["hawken_party"].game_start(self._room_jid())

        # Set the state to deployed
        self.state = DeploymentState.DEPLOYED

    def _undo_deployment(self):
        assert self.state == DeploymentState.DEPLOYED

        # Set the party as deployed
        self.xmpp.plugin["hawken_party"].game_end(self._room_jid())

        # Set the state to deployed
        self.state = DeploymentState.IDLE

    def _handle_deployment(self, poll_limit):
        # Start polling the advertisement
        start_time = time.time()
        timeout = True
        while self.state == DeploymentState.MATCHMAKING and (time.time() - start_time) < poll_limit:
            # Check the advertisement
            try:
                advertisement_info = self.api.wrapper(self.api.matchmaking_advertisement, self.advertisement)
            except hawkenapi.exceptions.RetryLimitExceeded:
                # Continue polling the advertisement
                pass
            else:
                # Check if the advertisement still exists
                if advertisement_info is None:
                    # Check if the advertisement has been canceled
                    if self.state == DeploymentState.MATCHMAKING:
                        # Couldn't find reservation, cancel it.
                        logger.warning("Reservation {0} for party {1} cannot be found! Stopped polling.".format(self.advertisement, self.guid))
                        self.xmpp.send_message(CommandType.PARTY, self._room_jid(), "Error: Could not retrieve advertisement - expired? If you did not cancel it, this is a bug - please report it!")
                        self.abort(CancelCode.PARTYCANCEL)

                    timeout = False
                    break
                else:
                    # Check if the reservation has been completed
                    if advertisement_info["ReadyToDeliver"]:
                        # Deploy
                        if self.state != DeploymentState.MATCHMAKING:
                            # Last minute abort
                            return
                        self._start_deployment(advertisement_info)
                        timeout = False
                        break

            if timeout:
                # Sleep a bit before requesting again.
                time.sleep(self.config.api.advertisement.polling_rate)

        if timeout:
            self.abort(CancelCode.NOMATCH)

    @notjoined
    def create(self, party):
        # Init the party
        self._init_party(party)

        # Register events with the bot
        self._register_events()

        # Create the party
        self.xmpp.plugin["hawken_party"].create(self._room_jid(), self.api.callsign)

        # Mark as joined
        self.joined = True

    @notjoined
    def join(self, party):
        # Init the party
        self._init_party(party)

        # Register events with the bot
        self._register_events()

        # Join the party
        self.xmpp.plugin["hawken_party"].join(self._room_jid(), self.api.callsign)

        # Mark as joined
        self.joined = True

    @joined
    def leave(self):
        # Stop the matchmaking
        self.abort(CancelCode.LEADERCANCEL)

        # Leave the party
        self.xmpp.plugin["hawken_party"].leave(self._room_jid(), self.api.callsign)

        # Reset the state
        self._clear_party()

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
        self.xmpp.plugin["hawken_party"].invite(self._room_jid(), self.xmpp.boundjid, self.api.callsign, target, callsign)

    @joined
    def kick(self, user):
        # Get the callsign
        callsign = self.cache.get_callsign(user)

        # Stop any active deployment
        self.abort(CancelCode.MEMBERKICK)

        # Send the kick
        self.xmpp.plugin["hawken_party"].kick(self._room_jid(), callsign)

    @joined
    def set_leader(self, user):
        # Get the callsign
        callsign = self.cache.get_callsign(user)

        # Stop any active deployment
        self.abort(CancelCode.LEADERCHANGE)

        # Change the leader
        self.xmpp.plugin["hawken_party"].leader_set(self._room_jid(), callsign)

    @joined
    def deploy(self, advertisement, poll_limit=None):
        if self.state != DeploymentState.IDLE:
            raise ValueError("A deployment cannot be started while one is in progress.")

        if poll_limit is None:
            poll_limit = self.config.api.advertisement.polling_limit

        # Start the deployment
        self._start_matchmaking(advertisement, poll_limit)

    @joined
    def abort(self, code=CancelCode.PARTYCANCEL):
        if self.state == DeploymentState.MATCHMAKING:
            self._cancel_matchmaking(code)
        elif self.state == DeploymentState.DEPLOYING:
            self._cancel_deployment(code)
        else:
            return False

        # Delete the advertisement
        self.api.wrapper(self.api.matchmaking_advertisement_delete, self.advertisement)

        return True

    @staticmethod
    def generate_guid():
        return str(uuid.uuid4())
