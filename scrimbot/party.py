# -*- coding: utf-8 -*-

import uuid


class Party:
    def __init__(self, xmpp, party, player, callsign):
        # Set up the settings
        self.xmpp = xmpp

        self.guid = party
        self.player = player
        self.callsign = callsign

        self.players = set()
        self.joined = False

        self.reservation = None
        self._deploying = False

    def _get_room(self):
        return "{0}@party.{1}".format(self.guid, self.xmpp.boundjid.server)

    def _register_events(self):
        self.xmpp.add_event_handler("muc::%s::got_online" % self._get_room(), self._handle_online)
        self.xmpp.add_event_handler("muc::%s::got_offline" % self._get_room(), self._handle_offline)

    def _unregister_events(self):
        self.xmpp.del_event_handler("muc::%s::got_online" % self._get_room(), self._handle_online)
        self.xmpp.del_event_handler("muc::%s::got_offline" % self._get_room(), self._handle_offline)

    def _handle_online(self, presence):
        # Ignore ourselves
        if presence["muc"]["nick"] == self.callsign:
            return

        # Add the player to the list
        self.players.add(presence["muc"]["jid"].user)

        # Abort any reservations/deployment
        self.abort()

    def _handle_offline(self, presence):
        # Ignore ourselves
        if presence["muc"]["nick"] == self.callsign:
            return

        # Remove the player to the list
        self.players.remove(presence["muc"]["jid"].user)

        # Abort any reservations/deployment
        self.abort()

    def _reservation_set(self, advertisement):
        self.reservation = advertisement

    def _reservation_delete(self):
        self.xmpp.hawken_api.matchmaking_advertisement_delete(self.reservation)
        self.reservation = None

    def create(self):
        # We can't have already joined the channel
        assert not self.joined

        # Register events with the bot
        self._register_events()

        # Create the party
        self.xmpp.plugin["hawken_party"].create(self._get_room(), self.callsign)

        # Mark as joined
        self.joined = True

    def join(self):
        # We can't have already joined the channel
        assert not self.joined

        # Register events with the bot
        self._register_events()

        # Join the party
        self.xmpp.plugin["hawken_party"].join(self._get_room(), self.callsign)

        # Mark as joined
        self.joined = True

    def leave(self):
        # Abort any reservations/deployment
        self.abort()

        # Leave the party
        self.xmpp.plugin["hawken_party"].leave(self._get_room(), self.callsign)

        # Unregister events with the bot
        self._unregister_events()

        # Clear players, mark as no longer joined
        self.players = set()
        self.joined = False

    def message(self, message):
        # Send the message
        self.xmpp.plugin["hawken_party"].message(self._get_room(), self.xmpp.boundjid.bare, self.player, message)

    def invite(self, target, callsign, reason=""):
        # Send the invite
        self.xmpp.plugin["hawken_party"].invite(self._get_room(), self.xmpp.boundjid.bare, self.player, self.callsign, target, callsign, reason)

    def kick(self, callsign):
        # Kick the user
        self.xmpp.plugin["hawken_party"].kick(self._get_room(), callsign)

    def leader_set(self, callsign):
        # Set the user as the leader
        self.xmpp.plugin["hawken_party"].leader_set(self._get_room(), callsign)

    def matchmaking_start(self, advertisement):
        # Signal that matchmaking has started
        self._reservation_set(advertisement)
        self.xmpp.plugin["hawken_party"].matchmaking_start(self._get_room(), self.xmpp.boundjid.bare, self.player)

    def matchmaking_stop(self):
        # Remove the reservation
        self._reservation_delete()

        # Signal that matchmaking has stopped
        self.xmpp.plugin["hawken_party"].matchmaking_cancel(self._get_room(), self.xmpp.boundjid.bare, self.player)

    def deploy_start(self, server, ip, port):
        # Mark deploy status
        self._deploying = True

        # Signal the players to deploy
        self.xmpp.plugin["hawken_party"].deploy_start(self._get_room(), self.xmpp.boundjid.bare, self.player, ";".join((server, ip, str(port))))

    def deploy_stop(self):
        # Mark deploy status
        self._deploying = False

        # Remove the reservation
        self._reservation_delete()

        # Signal the players to cancel the deploy
        self.xmpp.plugin["hawken_party"].deploy_cancel(self._get_room(), self.xmpp.boundjid.bare, self.player)

    def is_matchmaking(self):
        return self.reservation is not None

    def is_deploying(self):
        return self._deploying

    def abort(self):
        # Check for the deploy first, as it's the second step
        if self.is_deploying():
            self.deploy_stop()
        elif self.is_matchmaking():
            self.matchmaking_stop()

    def confirm(self):
        # Silent clear
        self.reservation = None
        self._deploying = False

    @staticmethod
    def generate_guid():
        return str(uuid.uuid4())
