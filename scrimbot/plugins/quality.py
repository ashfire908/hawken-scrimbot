# -*- coding: utf-8 -*-

import logging
from scrimbot.api import region_names, gametype_names, get_region, get_gametype
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
        self.register_config("plugins.quality.target_results", 3)
        self.register_config("plugins.quality.max_results", 6)

        # Register commands
        self.register_command(CommandType.ALL, "quality", self.quality, alias=["qa"])
        self.register_command(CommandType.ALL, "qualityexplain", self.quality_explain, alias=["qae"])
        self.register_command(CommandType.ALL, "qualitysearch", self.quality_search, alias=["qs"])

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

    def quality_search(self, cmdtype, cmdname, args, target, user, party):
        blacklist = ["HawkenCoOp"]

        # Check the arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Error: Missing target region.")
            return

        region = get_region(args[0])
        if not region:
            self._xmpp.send_message(cmdtype, target, "Error: Invalid target region.")
            return
        if len(args) > 1:
            gametype = get_gametype(args[1])
            if not gametype:
                self._xmpp.send_message(cmdtype, target, "Error: Invalid gametype.")
                return

            if gametype in blacklist:
                self._xmpp.send_message(cmdtype, target, "Error: Searching for {0} is disabled.".format(gametype_names[gametype]))
                return
        else:
            gametype = None

        # Get the server list
        server_list = self._api.get_server_list()

        # Load the player data
        player = self._api.get_user_stats(user)

        if player is None:
            self._xmpp.send_message(cmdtype, target, "Error: Failed to load player stats.")
        else:
            # Filter the servers
            def server_filter(server):
                if len(server["Users"]) == 0:
                    # Empty server
                    return False

                if server["Region"].lower() != region.lower():
                    # Region does not match
                    return False

                if server["GameType"] in blacklist:
                    # Gametype is blacklisted
                    return False

                if gametype is not None and server["GameType"] != gametype:
                    # Gametype does not match
                    return False

                return True

            servers = [server for server in server_list if server_filter(server)]

            # Get the header identifier
            if gametype is None:
                identifier = region_names[region]
            else:
                identifier = "{0} {1}".format(region_names[region], gametype_names[gametype])

            # Check if we have any servers left
            if len(servers) == 0:
                lines = ["No {0} servers found.".format(identifier)]
            else:
                # Calculate the server fitness
                server_fitness = {}

                def get_fitness(server):
                    fitness = calc_fitness(self._cache["globals"], player, server)
                    server_fitness[server["Guid"]] = fitness[3]

                    return abs(fitness[0])
                results = sorted(servers, key=get_fitness)[:self._config.plugins.quality.max_results]

                # Format the output
                lines = []
                x = 0
                for server in results:
                    if x >= self._config.plugins.quality.target_results:
                        break

                    fitness = server_fitness[server["Guid"]]

                    if self._config.plugins.quality.health_offset:
                        # Offset the health
                        health = -fitness["health"] + self._config.plugins.quality.health_offset
                    else:
                        health = fitness["health"]

                    lines.append("{0[ServerName]}: Quality {1} ({2}) - {3} - Players {4}/{0[MaxUsers]}".format(server, fitness["rating"], health, gametype_names[server["GameType"]], len(server["Users"])))

                    if len(server["Users"]) < server["MaxUsers"]:
                        x += 1

                # Add the header
                lines.insert(0, "Found {0} {1} servers by fitness:".format(len(lines), identifier))

            # Return the results
            self._xmpp.send_message(cmdtype, target, "\n".join(lines))


plugin = QualityPlugin
