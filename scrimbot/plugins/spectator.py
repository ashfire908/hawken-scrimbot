# -*- coding: utf-8 -*-

import logging
import threading
from hawkenapi.exceptions import InvalidResponse
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin
from scrimbot.reservations import ReservationResult, ServerReservation, NoSuchServer

logger = logging.getLogger(__name__)


class SpectatorPlugin(BasePlugin):
    @property
    def name(self):
        return "spectator"

    def enable(self):
        # Register cache
        self.register_cache("spectators")

        # Register group
        self.register_group("spectator")

        # Register commands
        self.register_command(CommandType.PM, "server", self.server, permsreq=["admin", "spectator"], alias=["spectate", "spec"])
        self.register_command(CommandType.PM, "user", self.user, permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "cancel", self.cancel, permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "confirm", self.confirm, permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "save", self.save, permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "renew", self.renew, permsreq=["admin", "spectator"])
        self.register_command(CommandType.PM, "clear", self.clear, permsreq=["admin", "spectator"])

        # Setup reservation tracking
        self.reservations = {}

    def disable(self):
        pass

    def connected(self):
        pass

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
        try:
            reservation = ServerReservation(self._config, self._cache, self._api, server, [user])
        except NoSuchServer:
            if isinstance(server, str):
                logger.warning("Reservation for {0}: Cannot find server {1} - reservation not created".format(user, server))
            else:
                logger.warning("Reservation for {0}: Cannot find server {1} [{2}] with match id {3} - reservation not created".format(user, server["Guid"], server["ServerName"], server["MatchId"]))
            self._xmpp.send_message(cmdtype, target, "Error: Unable to initialize reservation - the requested server does not exist.")
            return

        # Check for potential issues and report them
        critical, issues = reservation.check()
        for issue in issues:
            self._xmpp.send_message(cmdtype, target, issue)

        if critical:
            logger.info("Reservation for {0}: Check failed critically for server {1} [{2}] with match id {3} - reservation not created".format(user, reservation.server["Guid"], reservation.server["ServerName"], reservation.server["MatchId"]))
            return

        # Submit the reservation
        reservation.reserve()
        logger.info("Reservation for {0}: Created for server {1} [{2}] with match id {3}".format(user, reservation.server["Guid"], reservation.server["ServerName"], reservation.server["MatchId"]))
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
            logger.exception("Reservation for {0}: Invalid response for server {1} [{2}] with match id {3}".format(user, reservation.server["Guid"], reservation.server["ServerName"], reservation.server["MatchId"]))
            self.reservation_delete(user)
            self._xmpp.send_message(cmdtype, target, "Error: Reservation returned invalid response - {0}.".format(e))
        except:
            logger.exception("Reservation for {0}: Polling failed for server {1} [{2}] with match id {3}".format(user, reservation.server["Guid"], reservation.server["ServerName"], reservation.server["MatchId"]))
            self.reservation_delete(user)
            self._xmpp.send_message(cmdtype, target, "Error: Failed to poll for reservation. This is a bug - please report it!")
        else:
            # Handle the result
            if result == ReservationResult.READY:
                logger.info("Reservation for {0}: Reservation complete for server {1} [{2}] with match id {3} - Server address {4}:{5}".format(user, reservation.server["Guid"], reservation.server["ServerName"], reservation.server["MatchId"], reservation.advertisement["AssignedServerIp"], reservation.advertisement["AssignedServerPort"]))
                if reservation.server["DeveloperData"]["PasswordHash"] == "":
                    message = "\nReservation for server '{2}' complete.\nServer IP: {0}:{1}\nCommand: openip {0}:{1}?spectatorOnly=1\n\nUse '{3}{4} confirm' after joining the server, or '{3}{4} cancel' if you do not plan on joining the server."
                else:
                    message = "\nReservation for server '{2}' complete.\nServer IP: {0}:{1}\nCommand: openip {0}:{1}?spectatorOnly=1?password=\nPassword is required to join the server\n\nUse '{3}{4} confirm' after joining the server, or '{3}{4} cancel' if you do not plan on joining the server."
                self._xmpp.send_message(cmdtype, target, message.format(reservation.advertisement["AssignedServerIp"], reservation.advertisement["AssignedServerPort"], reservation.server["ServerName"], self._config.bot.command_prefix, self.name))
            else:
                self.reservation_delete(user)
                if result == ReservationResult.TIMEOUT:
                    logger.info("Reservation for {0}: Reservation timeout for server {1} [{2}] with match id {3}".format(user, reservation.server["Guid"], reservation.server["ServerName"], reservation.server["MatchId"]))
                    self._xmpp.send_message(cmdtype, target, "Time limit reached - reservation canceled.")
                elif result == ReservationResult.NOTFOUND:
                    logger.error("Reservation for {0}: Reservation missing for server {1} [{2}] with match id {3}".format(user, reservation.server["Guid"], reservation.server["ServerName"], reservation.server["MatchId"]))
                    self._xmpp.send_message(cmdtype, target, "Error: Could not retrieve advertisement - expired? This is a bug - please report it!")
                elif result == ReservationResult.ERROR:
                    logger.info("Reservation for {0}: Reservation error for server {1} [{2}] with match id {3}".format(user, reservation.server["Guid"], reservation.server["ServerName"], reservation.server["MatchId"]))
                    self._xmpp.send_message(cmdtype, target, "Error: Failed to poll for reservation. This is a bug - please report it!")

    def cancel(self, cmdtype, cmdname, args, target, user, party):
        # Delete the user's server reservation
        if self.reservation_delete(user):
            logger.info("Canceled reservation for {0}".format(user))
            self._xmpp.send_message(cmdtype, target, "Canceled server reservation.")
        else:
            self._xmpp.send_message(cmdtype, target, "No reservation found to cancel.")

    def confirm(self, cmdtype, cmdname, args, target, user, party):
        # Grab the reservation for the user
        reservation = self.reservation_get(user)

        # Check if the user actually has a reservation
        if not reservation:
            self._xmpp.send_message(cmdtype, target, "No reservation found to confirm.")
        else:
            logger.info("Confirmed reservation for {0}".format(user))
            # Save the assigned server for later use
            self.saved_server_set(user, reservation.advertisement["AssignedServerGuid"])
            self._xmpp.send_message(cmdtype, target, "Reservation confirmed; saved for future use.")

            # Delete the server reservation (as it's fulfilled now)
            self.reservation_delete(user)

    def save(self, cmdtype, cmdname, args, target, user, party):
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
                logger.info("Saved reservation for {0}: Server {1}".format(user, server))
                self.saved_server_set(user, server[0])
                self._xmpp.send_message(cmdtype, target, "Current server saved for future use.")

    def clear(self, cmdtype, cmdname, args, target, user, party):
        # Clear data for user
        self.reservation_delete(user)
        self.saved_server_delete(user)

        self._xmpp.send_message(cmdtype, target, "Cleared stored spectator data for your user.")

    def renew(self, cmdtype, cmdname, args, target, user, party):
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
                logger.info("Placing reservation for {0} by renewal: Server {1}".format(user, server))
                # Place the reservation
                self._xmpp.send_message(cmdtype, target, "Renewing server reservation, waiting for response... use '{0}{1} cancel' to abort.".format(self._config.bot.command_prefix, self.name))
                self.place_reservation(cmdtype, target, user, server)

    def user(self, cmdtype, cmdname, args, target, user, party):
        # Check arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing target user")
        else:
            # Get the user
            guid = self._api.get_user_guid(args[0])

            # Check if the user exists
            if guid is None:
                self._xmpp.send_message(cmdtype, target, "No such player exists.")
            else:
                # Get the user's server
                servers = self._api.get_user_server(guid, cache_bypass=True)

                # Check if the user is on a server
                if servers is None:
                    self._xmpp.send_message(cmdtype, target, "{0} is not on a server.".format(self._api.get_user_callsign(guid)))
                else:
                    server = servers[0]

                    # Check if the server exists
                    if server is None:
                        self._xmpp.send_message(cmdtype, target, "Error: Could not the find the server '{0}' is on.".format(self._api.get_user_callsign(guid)))
                    else:
                        # Place the reservation
                        logger.info("Placing reservation for {0} by user: Server {1}".format(user, server))
                        self._xmpp.send_message(cmdtype, target, "Placing server reservation, waiting for response... use '{0}{1} cancel' to abort.".format(self._config.bot.command_prefix, self.name))
                        self.place_reservation(cmdtype, target, user, server)

    def server(self, cmdtype, cmdname, args, target, user, party):
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
                server = servers[0]

                # Place the reservation
                logger.info("Placing reservation for {0} by server: Server {1}".format(user, server["Guid"]))
                self._xmpp.send_message(cmdtype, target, "Placing server reservation, waiting for response... use '{0}{1} cancel' to abort.".format(self._config.bot.command_prefix, self.name))
                self.place_reservation(cmdtype, target, user, server)


plugin = SpectatorPlugin
