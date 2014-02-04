# -*- coding: utf-8 -*-

import logging
import threading
from hawkenapi.exceptions import InvalidResponse
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin
from scrimbot.reservations import ReservationResult, ServerReservation

logger = logging.getLogger(__name__)


class SpectatorPlugin(BasePlugin):
    @property
    def name(self):
        return "spectator"

    def enable(self):
        # Register config
        self.register_config("plugins.spectator.polling_limit", 30)

        # Register cache
        self.register_cache("spectators")

        # Register group
        self.register_group("spectator")

        # Register commands
        self.register_command(CommandType.PM, "server", self.server, flags=["permsreq"], permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "spectate", self.server, flags=["permsreq", "alias"], permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "spec", self.server, flags=["permsreq", "alias"], permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "user", self.user, flags=["permsreq"], permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "cancel", self.cancel, flags=["permsreq"], permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "confirm", self.confirm, flags=["permsreq"], permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "save", self.save, flags=["permsreq"], permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "renew", self.renew, flags=["permsreq"], permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "clear", self.clear, flags=["permsreq"], permsreq=["admin", "spectator"])

        # Setup reservation tracking
        self.reservations = {}

    def disable(self):
        # Unregister config
        self.unregister_config("plugins.spectator.polling_limit")

        # Unregister cache
        self.unregister_cache("spectators")

        # Unregister group
        self.unregister_group("spectator")

        # Unregister commands
        self.unregister_command(CommandType.PM, "server")
        self.unregister_command(CommandType.PM, "spectate")
        self.unregister_command(CommandType.PM, "spec")
        self.unregister_command(CommandType.PM, "user")
        self.unregister_command(CommandType.PM, "cancel")
        self.unregister_command(CommandType.PM, "confirm")
        self.unregister_command(CommandType.PM, "save")
        self.unregister_command(CommandType.PM, "renew")
        self.unregister_command(CommandType.PM, "clear")

    def connected(self):
        # Delete all pending reservations (for cleanup on dirty restart/reload)
        for user in self.reservations:
            self.reservation_delete(user)

    def disconnected(self):
        # Delete all pending reservations
        for user in self.reservations:
            self.reservation_delete(user)

    def reservation_has(self, user):
        try:
            return self.reservations[user] is not None
        except KeyError:
            return False

    def reservation_get(self, user):
        try:
            return self.reservations[user]
        except KeyError:
            return False

    def reservation_set(self, user, reservation):
        # Clear the previous reservation
        self.reservation_delete(user)

        self.reservations[user] = reservation

    def reservation_delete(self, user):
        reservation = self.reservation_get(user)
        if reservation and reservation.created:
            reservation.cancel()
            self.reservations[user] = None
            return True

        return False

    def saved_server_has(self, user):
        try:
            return self._cache["spectators"][user] is not None
        except KeyError:
            return False

    def saved_server_get(self, user):
        try:
            return self._cache["spectators"][user]
        except KeyError:
            return None

    def saved_server_set(self, user, server):

        self._cache["spectators"][user] = server

    def saved_server_delete(self, user):
        try:
            self._cache["spectators"][user] = None
        except KeyError:
            pass

    def place_reservation(self, cmdtype, target, user, server):
        # Set up the reservation
        reservation = ServerReservation(self._config, self._cache, self._api, server, [user])

        # Check for potential issues and report them
        critical, issues = reservation.check()
        for issue in issues:
            self._xmpp.send_message(cmdtype, target, issue)

        if critical:
            return

        # Submit the reservation
        reservation.reserve(limit=self._config.plugins.spectator.polling_limit)
        self.reservation_set(user, reservation)

        # Set up the polling in another thread
        reservation_thread = threading.Thread(target=self.poll_reservation, args=(cmdtype, target, user))
        reservation_thread.start()

    def poll_reservation(self, cmdtype, target, user):
        # Get the reservation
        reservation = self.reservation_get(user)

        # Poll the reservation
        try:
            result = reservation.poll()
        except InvalidResponse as e:
            self.reservation_delete(user)
            self._xmpp.send_message(cmdtype, target, "Error: Reservation returned invalid response - {0}.".format(e))
        except:
            self.reservation_delete(user)
            self._xmpp.send_message(cmdtype, target, "Error: Failed to poll for reservation. This is a bug - please report it!")
        else:
            # Handle the result
            if result == ReservationResult.READY:
                message = "\nReservation for server '{2}' complete.\nServer IP: {0}:{1}.\n\nUse '{3}{4} confirm' after joining the server, or '{3}{4} cancel' if you do not plan on joining the server."
                self._xmpp.send_message(cmdtype, target, message.format(reservation.advertisement["AssignedServerIp"], reservation.advertisement["AssignedServerPort"], reservation.server["ServerName"], self._config.bot.command_prefix, self.name))
            else:
                self.reservation_delete(user)
                if result == ReservationResult.TIMEOUT:
                    self._xmpp.send_message(cmdtype, target, "Time limit reached - reservation canceled.")
                elif result == ReservationResult.NOTFOUND:
                    self._xmpp.send_message(cmdtype, target, "Error: Could not retrieve advertisement - expired? This is a bug - please report it!")
                elif result == ReservationResult.ERROR:
                    self._xmpp.send_message(cmdtype, target, "Error: Failed to poll for reservation. This is a bug - please report it!")

    def cancel(self, cmdtype, cmdname, args, target, user, room):
        # Delete the user's server reservation
        if self.reservation_delete(user):
            self._xmpp.send_message(cmdtype, target, "Canceled server reservation.")
        else:
            self._xmpp.send_message(cmdtype, target, "No reservation found to cancel.")

    def confirm(self, cmdtype, cmdname, args, target, user, room):
        # Grab the reservation for the user
        reservation = self.reservation_get(user)

        # Check if the user actually has a reservation
        if not reservation:
            self._xmpp.send_message(cmdtype, target, "No reservation found to confirm.")
        else:
            # Save the assigned server for later use
            self.saved_server_set(user, reservation.advertisement["AssignedServerGuid"])
            self._xmpp.send_message(cmdtype, target, "Reservation confirmed; saved for future use.")

            # Delete the server reservation (as it's fulfilled now)
            self.reservation_delete(user)

    def save(self, cmdtype, cmdname, args, target, user, room):
        # Check that the user isn't already joining a server
        if self.reservation_get(user):
            self._xmpp.send_message(cmdtype, target, "Error: You cannot save a server while joining another.")
        else:
            # Get the user's current server
            server = self._api.get_user_server(user)

            # Check if they are actually on a server
            if server is None:
                self._xmpp.send_message(cmdtype, target, "You are not on a server.")
            else:
                self.saved_server_set(user, server[0])
                self._xmpp.send_message(cmdtype, target, "Current server saved for future use.")

    def clear(self, cmdtype, cmdname, args, target, user, room):
        # Clear data for user
        self.reservation_delete(user)
        self.saved_server_delete(user)

        self._xmpp.send_message(cmdtype, target, "Cleared stored spectator data for your user.")

    def renew(self, cmdtype, cmdname, args, target, user, room):
        # Check if the user has a saved server
        if not self.saved_server_has(user):
            self._xmpp.send_message(cmdtype, target, "No saved server on file.")
        else:
            # Get the server info
            server = self.saved_server_get(user)

            # Check if the server exists
            if server is None:
                self._xmpp.send_message(cmdtype, target, "Error: Could not find the server from your last reservation.")
            else:
                # Place the reservation
                self._xmpp.send_message(cmdtype, target, "Renewing server reservation, waiting for response... use '{0}{1} cancel' to abort.".format(self._config.bot.command_prefix, self.name))
                self.place_reservation(cmdtype, target, user, server)

    def user(self, cmdtype, cmdname, args, target, user, room):
        # Check arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing target user")
        else:
            # Get the user
            guid = self._cache.get_guid(args[0])

            # Check if the user exists
            if guid is None:
                self._xmpp.send_message(cmdtype, target, "No such player exists.")
            else:
                # Get the user's server
                servers = self._api.get_user_server(guid)

                # Check if the user is on a server
                if servers is None:
                    self._xmpp.send_message(cmdtype, target, "{0} is not on a server.".format(self._cache.get_callsign(guid)))
                else:
                    server = servers[0]

                    # Check if the server exists
                    if server is None:
                        self._xmpp.send_message(cmdtype, target, "Error: Could not the find the server '{0}' is on.".format(self._cache.get_callsign(guid)))
                    else:
                        # Place the reservation
                        self._xmpp.send_message(cmdtype, target, "Placing server reservation, waiting for response... use '{0}{1} cancel' to abort.".format(self._config.bot.command_prefix, self.name))
                        self.place_reservation(cmdtype, target, user, server)

    def server(self, cmdtype, cmdname, args, target, user, room):
        # Check arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing target server.")
        else:
            # Get the server
            servers = self._api.get_server_by_name(args[0])

            # Check if the server exists
            if servers is False:
                self._xmpp.send_message(cmdtype, target, "Error: Failed to load server list.")
            elif len(servers) < 1:
                self._xmpp.send_message(cmdtype, target, "Error: Could not find server '{0}'.".format(args[0]))
            elif len(servers) > 1:
                self._xmpp.send_message(cmdtype, target, "Error: Server '{0}' is ambiguous.".format(args[0]))
            else:
                # Place the reservation
                self._xmpp.send_message(cmdtype, target, "Placing server reservation, waiting for response... use '{0}{1} cancel' to abort.".format(self._config.bot.command_prefix, self.name))
                self.place_reservation(cmdtype, target, user, servers[0])


plugin = SpectatorPlugin
