# -*- coding: utf-8 -*-

import logging
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin
from scrimbot.util import calc_fitness

logger = logging.getLogger(__name__)


class QualityPlugin(BasePlugin):
    @property
    def name(self):
        return "quality"

    def enable(self):
        # Register config
        self.register_config("plugins.quality.arbitrary_servers", True)
        self.register_config("plugins.quality.min_users", 2)
        self.register_config("plugins.quality.log_usage", False)
        self.register_config("plugins.quality.health_offset", 100)

        # Register commands
        self.register_command(CommandType.ALL, "quality", self.quality, alias=["qa"])
        self.register_command(CommandType.ALL, "qualityexplain", self.quality_explain, alias=["qae"])

    def disable(self):
        pass

    def connected(self):
        pass

    def disconnected(self):
        pass

    def record_usage(self, command, returned, server_info, data=None):
        if self._config.plugins.quality.log_usage:
            if returned:
                status = "returned"
            else:
                status = "rejected"

            message = "Call usage for [{0}]: Server {1} with {2} player(s) {3} request".format(command, server_info["ServerName"], len(server_info["Users"]), status)

            if data is not None:
                message += " - MMR Avg: {0:.2f} Score: {1[score][sum]:.2f} Health: {1[health]} Rating: {1[rating]}".format(server_info["ServerRanking"], data)
            else:
                message += " - MMR Avg: {0:.2f}".format(server_info["ServerRanking"])

            logger.info(message)

    def load_server_info(self, args, user):
        if len(args) > 0:
            # Check if this user is allowed to pick what server to check
            if self._config.plugins.quality.arbitrary_servers or self._permissions.user_check_group(user, "admin"):
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
        if self._config.plugins.quality.min_users == -1:
            min_players = server["MinUsers"]
        else:
            min_players = self._config.plugins.quality.min_users

        return min_players

    def check_server(self, server_info, user):
        if len(server_info["Users"]) < 1:
            return False, "No one is on the server '{0[ServerName]}'.".format(server_info)

        if not self._permissions.user_check_group(user, "admin") and \
           len(server_info["Users"]) < self.min_users(server_info):
            return False, "There needs to be at least {0} players on the server to use this command.".format(self.min_users(server_info))

        return True, None

    def quality(self, cmdtype, cmdname, args, target, user, party):
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
                self.record_usage(cmdname, result[0], server_info)
            else:
                # Load the player data
                player = self._api.get_user_stats(user)

                if player is None:
                    self._xmpp.send_message(cmdtype, target, "Error: Failed to load player stats.")
                else:
                    score, health, rating, details = calc_fitness(self._cache["globals"], player, server_info)

                    if self._config.plugins.quality.health_offset:
                        # Offset the health
                        health = -health + self._config.plugins.quality.health_offset

                    # Display the standard quality info
                    message = "Quality info for {0[ServerName]}: Rating {1}, Quality {2}".format(server_info, rating, health)
                    self._xmpp.send_message(cmdtype, target, message)

                    # Log it
                    self.record_usage(cmdname, result[0], server_info, data=details)

    def quality_explain(self, cmdtype, cmdname, args, target, user, party):
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
                self.record_usage(cmdname, result[0], server_info)
            else:
                # Load the player data
                player = self._api.get_user_stats(user)

                if player is None:
                    self._xmpp.send_message(cmdtype, target, "Error: Failed to load player stats.")
                else:
                    score, health, rating, details = calc_fitness(self._cache["globals"], player, server_info)

                    if self._config.plugins.quality.health_offset:
                        # Offset the health
                        health = -health + self._config.plugins.quality.health_offset

                    # Display the detailed quality info
                    score = int((details["score"]["sum"] / details["threshold"]["sum"]) * 100)
                    rank = int((details["score"]["rank"] / details["threshold"]["sum"]) * 100)
                    level = int((details["score"]["level"] / details["threshold"]["sum"]) * 100)
                    message = "Quality info for {0[ServerName]}: Rating {1}, Quality {2}, Score {3}% [Rating {4}% + Level {5}%]".format(server_info, rating, health, score, rank, level)
                    self._xmpp.send_message(cmdtype, target, message)

                    # Log it
                    self.record_usage(cmdname, result[0], server_info, data=details)


plugin = QualityPlugin
