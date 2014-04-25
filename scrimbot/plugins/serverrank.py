# -*- coding: utf-8 -*-

import math
import logging
import hawkenapi.exceptions
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin
from scrimbot.util import stat_analysis, get_bracket


logger = logging.getLogger(__name__)


class ServerRankPlugin(BasePlugin):
    @property
    def name(self):
        return "serverrank"

    def enable(self):
        # Register config
        self.register_config("plugins.serverrank.arbitrary_servers", True)
        self.register_config("plugins.serverrank.min_users", 2)
        self.register_config("plugins.serverrank.log_usage", False)
        self.register_config("plugins.serverrank.show_minmax", True)
        self.register_config("plugins.serverrank.minmax_bracket", 100)

        # Register commands
        self.register_command(CommandType.ALL, "serverrank", self.server_rank, alias=["sr"])
        self.register_command(CommandType.ALL, "serverrankdetailed", self.server_rank_detailed, alias=["srd"])

    def disable(self):
        pass

    def connected(self):
        pass

    def disconnected(self):
        pass

    def record_usage(self, command, returned, server_info, data=None):
        if self._config.plugins.serverrank.log_usage:
            if returned:
                status = "returned"
            else:
                status = "rejected"

            message = "Call usage for [{0}]: Server {1} with {2} player(s) {3} request".format(command, server_info["ServerName"], len(server_info["Users"]), status)

            if data is not None:
                message += " - Avg: {0[mean]:.2f} Max: {0[max]:.2f} Min: {0[min]:.2f} Stddev: {0[stddev]:.3f} Reported Avg: {1}".format(data, server_info["ServerRanking"])
            else:
                message += " - Avg: {0}".format(server_info["ServerRanking"])

            logger.info(message)

    def load_server_info(self, args, user):
        if len(args) > 0:
            # Check if this user is allowed to pick what server to check
            if self._config.plugins.serverrank.arbitrary_servers or self._permissions.user_check_group(user, "admin"):
                # Load the server info by name
                servers = self._api.get_server_by_name(args[0])

                if len(servers) < 1:
                    return False, "No such server."
                if len(servers) > 1:
                    return False, "Server name is ambiguous."
                else:
                    server_info = servers[0]
            else:
                return False, "Rankings for arbitrary servers are disabled."
        else:
            # Find the server the user is on
            server = self._api.get_user_server(user, cache_bypass=True)

            # Check if they are actually on a server
            if server is None:
                return False, "You are not on a server."
            else:
                # Load the server info
                server_info = self._api.get_server(server[0])

                if not server_info:
                    return False, "Error: Failed to load server info."

        return True, server_info

    def min_users(self, server):
        if self._config.plugins.serverrank.min_users == -1:
            min_players = server["MinUsers"]
        else:
            min_players = self._config.plugins.serverrank.min_users

        return min_players

    def check_server(self, server_info, user):
        if len(server_info["Users"]) < 1:
            return False, "No one is on the server '{0[ServerName]}'.".format(server_info)

        if not self._permissions.user_check_group(user, "admin") and \
           len(server_info["Users"]) < self.min_users(server_info):
            return False, "There needs to be at least {0} players on the server to use this command.".format(self.min_users(server_info))

        return True, None

    def server_rank(self, cmdtype, cmdname, args, target, user, party):
        # Get the server info
        result = self.load_server_info(args, user)

        # Check the response
        if not result[0]:
            self._xmpp.send_message(cmdtype, target, result[1])
        else:
            server_info = result[1]

            # Check server
            result = self.check_server(server_info, user)

            # Log it
            self.record_usage(cmdname, result[0], server_info)

            # Check the response
            if not result[0]:
                self._xmpp.send_message(cmdtype, target, result[1])
            else:
                # Display the standard server rank
                message = "Ranking info for {0[ServerName]}: MMR Average: {0[ServerRanking]}, Average Pilot Level: {0[DeveloperData][AveragePilotLevel]}".format(server_info)
                self._xmpp.send_message(cmdtype, target, message)

    def server_rank_detailed(self, cmdtype, cmdname, args, target, user, party):
        # Get the server info
        result = self.load_server_info(args, user)

        # Check the response
        if not result[0]:
            self._xmpp.send_message(cmdtype, target, result[1])
        else:
            server_info = result[1]

            # Check server
            result = self.check_server(server_info, user)

            # Check the response
            if not result[0]:
                self._xmpp.send_message(cmdtype, target, result[1])

                # Log it
                self.record_usage(cmdname, False, server_info)
            else:
                # Load the MMR for all the players on the server
                try:
                    data = self._api.get_user_stats(server_info["Users"])
                except hawkenapi.exceptions.InvalidBatch:
                    self._xmpp.send_message(cmdtype, target, "Error: Failed to load player data.")
                else:
                    # Process stats
                    mmr_info = stat_analysis(data, "MatchMaking.Rating")

                    # Check if we have enough players
                    min_users = self.min_users(server_info)

                    if not mmr_info:
                        self._xmpp.send_message(cmdtype, target, "There are no ranked players on the server.")

                        # Log it
                        self.record_usage(cmdname, False, server_info)
                    elif len(mmr_info["list"]) < min_users and not self._permissions.user_check_group(user, "admin"):
                        self._xmpp.send_message(cmdtype, target, "There needs to be at least {0} ranked players on the server - only {1} of the players are currently ranked.".format(min_users, len(mmr_info["list"])))

                        # Log it
                        self.record_usage(cmdname, False, server_info, mmr_info)
                    else:
                        # Display stats
                        if self._config.plugins.serverrank.show_minmax:
                            if self._config.plugins.serverrank.minmax_bracket == 0:
                                minmax = "Min MMR: {0[min]:.2f}, Max MMR: {0[max]:.2f}, ".format(mmr_info)
                            else:
                                low = get_bracket(mmr_info["min"], self._config.plugins.serverrank.minmax_bracket)[0]
                                high = get_bracket(mmr_info["max"], self._config.plugins.serverrank.minmax_bracket)[1]

                                minmax = "MMR Range: {0}-{1}, ".format(low, high)
                        else:
                            minmax = ""

                        if math.floor(mmr_info["mean"]) != server_info["ServerRanking"]:
                            warn = " (Server is reporting an average of {0})".format(server_info["ServerRanking"])
                        else:
                            warn = ""

                        message = "MMR breakdown for {0[ServerName]}: Average MMR: {1[mean]:.2f}, {2}Standard deviation: {1[stddev]:.3f}{3}".format(server_info, mmr_info, minmax, warn)
                        self._xmpp.send_message(cmdtype, target, message)

                        # Log it
                        self.record_usage(cmdname, True, server_info, mmr_info)


plugin = ServerRankPlugin
