# -*- coding: utf-8 -*-

import logging
import threading
import time
import hawkenapi.exceptions
from scrimbot.plugins.base import BasePlugin, CommandType

logger = logging.getLogger(__name__)


class SpectatorPlugin(BasePlugin):
    @property
    def name(self):
        return "spectator"

    def enable(self):
        # Register config
        self.register_config("plugins.spectator.polling_limit", 30)

        # Register group
        self.register_group("spectator")

        # Register commands
        self.register_command(CommandType.PM, "server", self.server, flags=["permsreq"], metadata={"permsreq": ["admin", "spectator"]})
        self.register_command(CommandType.PM, "spectate", self.server, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "spectator"]})
        self.register_command(CommandType.PM, "spec", self.server, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "spectator"]})
        self.register_command(CommandType.PM, "user", self.user, flags=["permsreq"], metadata={"permsreq": ["admin"]})
        self.register_command(CommandType.PM, "cancel", self.cancel, flags=["permsreq"], metadata={"permsreq": ["admin", "spectator"]})
        self.register_command(CommandType.PM, "confirm", self.confirm, flags=["permsreq"], metadata={"permsreq": ["admin", "spectator"]})
        self.register_command(CommandType.PM, "save", self.save, flags=["permsreq"], metadata={"permsreq": ["admin", "spectator"]})
        self.register_command(CommandType.PM, "renew", self.renew, flags=["permsreq"], metadata={"permsreq": ["admin", "spectator"]})
        self.register_command(CommandType.PM, "clear", self.clear, flags=["permsreq"], metadata={"permsreq": ["admin", "spectator"]})

        # Setup reservation tracking
        self.reservations = {}

    def disable(self):
        # Unregister config
        self.unregister_config("plugins.spectator.polling_limit")

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
        pass

    def disconnected(self):
        # Delete all pending reservations
        for user in self.reservations:
            if self.reservation_has(user):
                self.reservation_delete(user)

    def reservation_init(self, user):
        template = {
            "advertisement": None,
            "saved": None
        }
        if not user in self.reservations:
            self.reservations[user] = template

    def reservation_has(self, user):
        try:
            return self.reservations[user]["advertisement"] is not None
        except KeyError:
            return False

    def reservation_get(self, user):
        if self.reservation_has(user):
            return self.reservations[user]["advertisement"]
        else:
            return False

    def reservation_set(self, user, advertisement):
        # Initialize the user data
        self.reservation_init(user)

        # Clear the previous reservation
        if self.reservation_has(user):
            self.reservation_delete(user)

        self.reservations[user]["advertisement"] = advertisement

    def reservation_delete(self, user):
        if self.reservation_has(user):
            self.api.wrapper(self.api.matchmaking_advertisement_delete, self.reservations[user]["advertisement"])
            self.reservations[user]["advertisement"] = None
            return True

        return False

    def reservation_clear(self, user):
        self.reservation_delete(user)

        try:
            del self.reservations[user]
        except KeyError:
            pass

    def saved_server_has(self, user):
        try:
            return self.reservations[user]["saved"] is not None
        except KeyError:
            return False

    def saved_server_get(self, user):
        return self.reservations[user]["saved"]

    def saved_server_set(self, user, server):
        # Initialize the user data
        self.reservation_init(user)

        self.reservations[user]["saved"] = server

    def saved_server_delete(self, user):
        try:
            self.reservations[user]["saved"] = None
        except KeyError:
            pass

    def check_issues(self, user, server):
        issues = []

        # Server full
        user_count = len(server["Users"])
        if user_count >= server["MaxUsers"]:
            issues.append("Warning: Server is full ({0}/{1}) - reservation may fail!".format(user_count, server["MaxUsers"]))

        # Server outside user's rank
        server_level = int(server["DeveloperData"]["AveragePilotLevel"])
        if server_level != 0:
            stats = self.api.wrapper(self.api.user_stats, user)
            if stats is not None:
                pilot_level = int(stats["Progress.Pilot.Level"])
                if pilot_level - int(self.cache["globals"]["MMPilotLevelRange"]) > server_level:
                    issues.append("Warning: Server outside your skill level ({1} vs {0}) - reservation may fail!".format(pilot_level, server_level))

        return issues

    def place_reservation(self, cmdtype, target, user, server):
        # Check for potential issues and report them
        issues = self.check_issues(user, server)
        for issue in issues:
            self.xmpp.send_message(cmdtype, target, issue)

        # Place the reservation
        advertisement = self.api.wrapper(self.api.matchmaking_advertisement_post_server, server["GameVersion"],
                                         server["Region"], server["Guid"], self.api.guid, [user])
        self.reservation_set(user, advertisement)

        # Set up the polling in another thread
        reservation_thread = threading.Thread(target=self.poll_reservation, args=(cmdtype, target, user))
        reservation_thread.start()

    def poll_reservation(self, cmdtype, target, user):
        # Get the advertisement
        advertisement = self.reservation_get(user)

        # Start polling the advertisement
        start_time = time.time()
        timeout = True
        while (time.time() - start_time) < self.config.plugins.spectator.polling_limit:
            # Check the advertisement
            try:
                advertisement_info = self.api.wrapper(self.api.matchmaking_advertisement, advertisement)
            except hawkenapi.exceptions.RetryLimitExceeded:
                # Continue polling the advertisement
                pass
            else:
                # Check if the advertisement still exists
                if advertisement_info is None:
                    # Check if the advertisement has been canceled
                    if not self.reservation_has(user):
                        logger.debug("Reservation {0} for user {1} has been canceled, stopped polling.".format(advertisement, user))
                        timeout = False
                        break
                    else:
                        # Couldn't find reservation
                        logger.warning("Reservation {0} for user {1} cannot be found! Stopped polling.".format(advertisement, user))
                        self.xmpp.send_message(cmdtype, target, "Error: Could not retrieve advertisement - expired? If you did not cancel it, this is a bug - please report it!")
                        timeout = False
                        break
                else:
                    # Check if the reservation has been completed
                    if advertisement_info["ReadyToDeliver"]:
                        # Get the server name
                        try:
                            server_name = self.api.wrapper(self.api.server_list, advertisement_info["AssignedServerGuid"])["ServerName"]
                        except KeyError:
                            server_name = "<unknown>"

                        message = "\nReservation for server '{2}' complete.\nServer IP: {0}:{1}.\n\nUse '{3}{4} confirm' after joining the server, or '{3}{4} cancel' if you do not plan on joining the server."
                        self.xmpp.send_message(cmdtype, target, message.format(advertisement_info["AssignedServerIp"], advertisement_info["AssignedServerPort"], server_name, self.config.bot.command_prefix, self.name))
                        timeout = False
                        break

            if timeout:
                # Sleep a bit before requesting again.
                time.sleep(self.config.api.advertisement.polling_rate)

        if timeout:
            self.reservation_delete(user)
            self.xmpp.send_message(cmdtype, target, "Time limit reached - reservation canceled.")

    def cancel(self, cmdtype, cmdname, args, target, user, room):
        # Delete the user's server reservation
        if self.reservation_delete(user):
            self.xmpp.send_message(cmdtype, target, "Canceled server reservation.")
        else:
            self.xmpp.send_message(cmdtype, target, "No reservation found to cancel.")

    def confirm(self, cmdtype, cmdname, args, target, user, room):
        # Grab the reservation for the user
        reservation = self.reservation_get(user)

        # Check if the user actually has a reservation
        if not reservation:
            self.xmpp.send_message(cmdtype, target, "No reservation found to confirm.")
        else:
            # Load the advertisement
            advertisement = self.api.wrapper(self.api.matchmaking_advertisement, reservation)

            # Check if the advertisement exists
            if advertisement is None:
                self.xmpp.send_message(cmdtype, target, "Error: Failed to load reservation info (request probably expired).")
            else:
                # Save the advertisement server for later use
                self.saved_server_set(user, advertisement["AssignedServerGuid"])
                self.xmpp.send_message(cmdtype, target, "Reservation confirmed; saved for future use.")

            # Delete the server reservation (as it's fulfilled now)
            self.reservation_delete(user)

    def save(self, cmdtype, cmdname, args, target, user, room):
        # Check that the user isn't already joining a server
        if self.reservation_get(user):
            self.xmpp.send_message(cmdtype, target, "Error: You cannot save a server while joining another.")
        else:
            # Get the user's current server
            server = self.api.wrapper(self.api.user_server, user)

            # Check if they are actually on a server
            if server is None:
                self.xmpp.send_message(cmdtype, target, "You are not on a server.")
            else:
                self.saved_server_set(user, server[0])
                self.xmpp.send_message(cmdtype, target, "Current server saved for future use.")

    def clear(self, cmdtype, cmdname, args, target, user, room):
        # Clear data for user
        self.reservation_delete(user)
        self.saved_server_delete(user)

        self.xmpp.send_message(cmdtype, target, "Cleared stored spectator data for your user.")

    def renew(self, cmdtype, cmdname, args, target, user, room):
        # Check if the user has a saved server
        if not self.saved_server_has(user):
            self.xmpp.send_message(cmdtype, target, "No saved server on file.")
        else:
            # Get the server info
            server = self.api.wrapper(self.api.server_list, self.saved_server_get(user))

            # Check if the server exists
            if server is None:
                self.xmpp.send_message(cmdtype, target, "Error: Could not find the server from your last reservation.")
            else:
                # Place the reservation
                self.xmpp.send_message(cmdtype, target, "Renewing server reservation, waiting for response... use '{0}{1} cancel' to abort.".format(self.config.bot.command_prefix, self.name))
                self.place_reservation(cmdtype, target, user, server)

    def user(self, cmdtype, cmdname, args, target, user, room):
        # Check arguments
        if len(args) < 1:
            self.xmpp.send_message(cmdtype, target, "Missing target user")
        else:
            # Get the user
            guid = self.cache.get_guid(args[0])

            # Check if the user exists
            if guid is None:
                self.xmpp.send_message(cmdtype, target, "No such player exists.")
            else:
                # Get the user's server
                servers = self.api.wrapper(self.api.user_server, guid)

                # Check if the user is on a server
                if servers is None:
                    self.xmpp.send_message(cmdtype, target, "{0} is not on a server.".format(self.cache.get_callsign(guid)))
                else:
                    server = self.api.wrapper(self.api.server_list, servers[0])

                    # Check if the server exists
                    if server is None:
                        self.xmpp.send_message(cmdtype, target, "Error: Could not the find the server '{0}' is on.".format(self.cache.get_callsign(guid)))
                    else:
                        # Place the reservation
                        self.xmpp.send_message(cmdtype, target, "Placing server reservation, waiting for response... use '{0}{1} cancel' to abort.".format(self.config.bot.command_prefix, self.name))
                        self.place_reservation(cmdtype, target, user, server)

    def server(self, cmdtype, cmdname, args, target, user, room):
        # Check arguments
        if len(args) < 1:
            self.xmpp.send_message(cmdtype, target, "Missing target server.")
        else:
            # Get the server
            server = self.api.wrapper(self.api.server_by_name, args[0])

            # Check if the server exists
            if server is False:
                self.xmpp.send_message(cmdtype, target, "Error: Failed to load server list.")
            elif server is None:
                self.xmpp.send_message(cmdtype, target, "Error: Could not find server '{0}'.".format(args[0]))
            else:
                # Place the reservation
                self.xmpp.send_message(cmdtype, target, "Placing server reservation, waiting for response... use '{0}{1} cancel' to abort.".format(self.config.bot.command_prefix, self.name))
                self.place_reservation(cmdtype, target, user, server)


plugin = SpectatorPlugin
