# -*- coding: utf-8 -*-

import logging
import hawkenapi.exceptions
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin
from scrimbot.util import mmr_stats


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
        self.register_config("plugins.serverrank.playerrank_integration", False)

        # Register commands
        self.register_command(CommandType.ALL, "serverrank", self.server_rank)
        self.register_command(CommandType.ALL, "serverrankdetailed", self.server_rank_detailed)
        self.register_command(CommandType.ALL, "sr", self.server_rank, flags=["alias"])
        self.register_command(CommandType.ALL, "srd", self.server_rank_detailed, flags=["alias"])

    def disable(self):
        # Unregister config
        self.unregister_config("plugins.serverrank.arbitrary_servers")
        self.unregister_config("plugins.serverrank.min_users")
        self.unregister_config("plugins.serverrank.log_usage")
        self.unregister_config("plugins.serverrank.show_minmax")
        self.unregister_config("plugins.serverrank.playerrank_integration")

        # Unregister commands
        self.unregister_command(CommandType.ALL, "serverrank")
        self.unregister_command(CommandType.ALL, "serverrankdetailed")
        self.unregister_command(CommandType.ALL, "sr")
        self.unregister_command(CommandType.ALL, "srd")

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
                message += " - Avg: {0[mean]:.2f} Max: {0[max]:.2f} Min: {0[min]:.2f} Stddev: {0[stddev]:.3f}".format(data)
            else:
                message += " - Avg: {0:.2f}".format(server_info["ServerRanking"])

            logger.info(message)

    def load_server_info(self, args, user):
        if len(args) > 0:
            # Check if this user is allowed to pick what server to check
            if self._config.plugins.serverrank.arbitrary_servers or self._permissions.user_check_group(user, "admin"):
                # Load the server info by name
                server_info = self._api.get_server_by_name(args[0])

                if not server_info:
                    return False, "No such server."
            else:
                return False, "Rankings for arbitrary servers are disabled."
        else:
            # Find the server the user is on
            server = self._api.get_user_server(user)

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

    def server_rank(self, cmdtype, cmdname, args, target, user, room):
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

    def server_rank_detailed(self, cmdtype, cmdname, args, target, user, room):
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
                    users = {}
                    for user_data in data:
                        try:
                            mmr = user_data["MatchMaking.Rating"]
                        except KeyError:
                            # Handle a quirk of the API where users have no mmr
                            mmr = None

                        users[user_data["Guid"]] = {"mmr": mmr}

                    min_users = self.min_users(server_info)
                    ranked_users = len([x for x in users.values() if x["mmr"] is not None])

                    # Process stats
                    mmr_info = mmr_stats(users)

                    if ranked_users < min_users and not self._permissions.user_check_group(user, "admin"):
                        self._xmpp.send_message(cmdtype, target, "There needs to be {0} ranked players (i.e. have an MMR set) on the server to use this command - only {1} of the players are currently ranked.".format(min_users, ranked_users))

                        # Log it
                        self.record_usage(cmdname, False, server_info, mmr_info)
                    else:
                        # Display stats
                        if not self._config.plugins.serverrank.show_minmax or \
                           (self._config.plugins.serverrank.playerrank_integration and "playerrank" in self._plugins.active and self._plugins.active["playerrank"].user_overlimit(user)[0]):
                            minmax = ""
                        else:
                            minmax = "Max MMR: {0[max]:.2f}, Min MMR: {0[min]:.2f}, ".format(mmr_info)

                        message = "MMR breakdown for {0[ServerName]}: Average MMR: {1[mean]:.2f}, {2}Standard deviation {1[stddev]:.3f}".format(server_info, mmr_info, minmax)
                        self._xmpp.send_message(cmdtype, target, message)

                        # Log it
                        self.record_usage(cmdname, True, server_info, mmr_info)


plugin = ServerRankPlugin
