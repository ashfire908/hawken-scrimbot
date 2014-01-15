# -*- coding: utf-8 -*-

from copy import deepcopy
import math
import logging
import hawkenapi.exceptions
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin

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
        self.register_config("plugins.serverrank.health_offset", 100)

        # Register commands
        self.register_command(CommandType.ALL, "serverrank", self.server_rank)
        self.register_command(CommandType.ALL, "serverrankdetailed", self.server_rank_detailed)
        self.register_command(CommandType.ALL, "sr", self.server_rank, flags=["alias"])
        self.register_command(CommandType.ALL, "srd", self.server_rank_detailed, flags=["alias"])
        self.register_command(CommandType.ALL, "quality", self.quality)
        self.register_command(CommandType.ALL, "qualitydetailed", self.quality_detailed)
        self.register_command(CommandType.ALL, "qa", self.quality, flags=["alias"])
        self.register_command(CommandType.ALL, "qad", self.quality_detailed, flags=["alias"])

    def disable(self):
        # Unregister config
        self.unregister_config("plugins.serverrank.arbitrary_servers")
        self.unregister_config("plugins.serverrank.min_users")
        self.unregister_config("plugins.serverrank.log_usage")
        self.unregister_config("plugins.serverrank.show_minmax")
        self.unregister_config("plugins.serverrank.health_offset")

        # Unregister commands
        self.unregister_command(CommandType.ALL, "serverrank")
        self.unregister_command(CommandType.ALL, "serverrankdetailed")
        self.unregister_command(CommandType.ALL, "sr")
        self.unregister_command(CommandType.ALL, "srd")
        self.unregister_command(CommandType.ALL, "quality")
        self.unregister_command(CommandType.ALL, "qualitydetailed")
        self.unregister_command(CommandType.ALL, "qa")
        self.unregister_command(CommandType.ALL, "qad")

    def connected(self):
        pass

    def disconnected(self):
        pass

    def mmr_stats(self, users):
        # TODO: Redo the loop so this isn't needed or such
        users = deepcopy(users)
        mmr = {}

        # Calculate min/max/mean
        mmr["list"] = [user["mmr"] for user in users.values() if user["mmr"] is not None]
        if len(mmr["list"]) > 0:
            mmr["max"] = max(mmr["list"])
            mmr["min"] = min(mmr["list"])
            mmr["mean"] = math.fsum(mmr["list"]) / float(len(mmr["list"]))

            # Process each user's stats
            for user in users.values():
                # Check if they have an mmr
                if not user["mmr"] is None:
                    # Calculate the deviation
                    user["deviation"] = user["mmr"] - mmr["mean"]  # Server MMR can be fixed

            # Calculate standard deviation
            stddev_list = [user["deviation"] ** 2 for user in users.values() if "deviation" in user]
            if len(stddev_list) > 0:
                mmr["stddev"] = math.sqrt(math.fsum(stddev_list) / float(len(stddev_list)))

            return mmr
        else:
            # Can't pull mmr out of thin air
            return False

    def calc_fitness(self, player, server):
        # Get shared values
        weight_rank = int(self._cache["globals"]["MMGlickoWeight"])
        weight_level = int(self._cache["globals"]["MMPilotLevelWeight"])
        min_matches = int(self._cache["globals"]["NoobHandicapCutoff"])
        avg_level = int(server["DeveloperData"]["AveragePilotLevel"])
        avg_rank = server["ServerRanking"]

        # Get threshold
        threshold = {}
        threshold["rank"] = weight_rank * int(self._cache["globals"]["MMSkillRange"])
        threshold["level"] = weight_level * int(self._cache["globals"]["MMPilotLevelRange"])
        threshold["sum"] = sum(threshold.values())

        # Calculate handicap
        matches = min(min_matches, abs(min(0, int(player["GameMode.All.TotalMatches"]) - min_matches)))
        handicap = matches * int(self._cache["globals"]["NoobHandicapSize"])

        # Get adjusted player rating
        rank = player["MatchMaking.Rating"] - handicap

        # Calculate score
        score = {}
        score["rank"] = (avg_rank - rank) * weight_rank
        score["level"] = (avg_level - int(player["Progress.Pilot.Level"])) * weight_level
        score["sum"] = sum(score.values())

        # Calculate health
        health = int((abs(score["sum"]) * 100) / threshold["sum"])

        # Calculate rating
        if avg_level <= 0 or avg_rank <= 0:
            rating = 3
        elif abs(score["sum"]) > threshold["sum"]:
            rating = 0
        elif health > int(self._cache["globals"]["BrowserMedium"]):
            rating = 1
        elif health > int(self._cache["globals"]["BrowserGood"]):
            rating = 2
        else:
            rating = 3

        details = {
            "threshold": threshold,
            "handicap": handicap,
            "score": score,
            "health": health,
            "rating": rating
        }

        if self._config.plugins.serverrank.health_offset:
            # Offset the health
            health = -health + self._config.plugins.serverrank.health_offset

        return score["sum"], health, rating, details

    def record_serverrank_usage(self, command, returned, server_info, data=None):
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

    def record_quality_usage(self, command, returned, server_info, data=None):
        if self._config.plugins.serverrank.log_usage:
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
            if self._config.plugins.serverrank.arbitrary_servers or self._permissions.user_check_group(user, "admin"):
                # Load the server info by name
                server_info = self._api.wrapper(self._api.server_by_name, args[0])

                if not server_info:
                    return False, "No such server."
            else:
                return False, "Rankings for arbitrary servers are disabled."
        else:
            # Find the server the user is on
            server = self._api.wrapper(self._api.user_server, user)
            # Check if they are actually on a server
            if server is None:
                return False, "You are not on a server."
            else:
                # Load the server info
                server_info = self._api.wrapper(self._api.server_list, server[0])

                if not server_info:
                    return False, "Error: Failed to load server info."

        return True, server_info

    def server_min(self, server):
        if self._config.plugins.serverrank.min_users == -1:
            min_players = server["MinUsers"]
        else:
            min_players = self._config.plugins.serverrank.min_users

        return min_players

    def check_serverrank(self, server_info, user):
        if len(server_info["Users"]) < 1:
            return False, "No one is on the server '{0[ServerName]}'.".format(server_info)

        if not self._permissions.user_check_group(user, "admin") and \
           len(server_info["Users"]) < self.server_min(server_info):
            return False, "There needs to be at least {0} players on the server to use this command.".format(self.server_min(server_info))

        return True, None

    def check_fitness(self, server_info, user):
        if len(server_info["Users"]) < 1:
            return False, "No one is on the server '{0[ServerName]}'.".format(server_info)

        if not self._permissions.user_check_group(user, "admin") and \
           len(server_info["Users"]) < self.server_min(server_info):
            return False, "There needs to be at least {0} players on the server to use this command.".format(self.server_min(server_info))

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
            result = self.check_serverrank(server_info, user)

            # Log it
            self.record_serverrank_usage(cmdname, result[0], server_info)

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
            result = self.check_serverrank(server_info, user)

            # Check the response
            if not result[0]:
                self._xmpp.send_message(cmdtype, target, result[1])

                # Log it
                self.record_serverrank_usage(cmdname, False, server_info)
            else:
                # Load the MMR for all the players on the server
                try:
                    data = self._api.wrapper(self._api.user_stats, server_info["Users"])
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

                    server_min = self.server_min(server_info)
                    ranked_users = len([x for x in users.values() if x["mmr"] is not None])

                    # Process stats
                    mmr_info = self.mmr_stats(users)

                    if ranked_users < server_min and not self._permissions.user_check_group(user, "admin"):
                        self._xmpp.send_message(cmdtype, target, "There needs to be {0} ranked players (i.e. have an MMR set) on the server to use this command - only {1} of the players are currently ranked.".format(server_min, ranked_users))

                        # Log it
                        self.record_serverrank_usage(cmdname, False, server_info, mmr_info)
                    else:
                        # Display stats
                        if self._config.plugins.serverrank.show_minmax:
                            minmax = "Max MMR: {0[max]:.2f}, Min MMR: {0[min]:.2f}, ".format(mmr_info)
                        else:
                            minmax = ""

                        message = "MMR breakdown for {0[ServerName]}: Average MMR: {1[mean]:.2f}, {2}Standard deviation {1[stddev]:.3f}".format(server_info, mmr_info, minmax)
                        self._xmpp.send_message(cmdtype, target, message)

                        # Log it
                        self.record_serverrank_usage(cmdname, True, server_info, mmr_info)

    def quality(self, cmdtype, cmdname, args, target, user, room):
        # Get the server info
        result = self.load_server_info(args, user)

        # Check the response
        if not result[0]:
            self._xmpp.send_message(cmdtype, target, result[1])
        else:
            server_info = result[1]

            # Check server
            result = self.check_fitness(server_info, user)

            # Check the response
            if not result[0]:
                self._xmpp.send_message(cmdtype, target, result[1])

                # Log it
                self.record_quality_usage(cmdname, result[0], server_info)
            else:
                # Load the player data
                player = self._api.wrapper(self._api.user_stats, user)

                if player is None:
                    self._xmpp.send_message(cmdtype, target, "Error: Failed to load player stats.")
                else:
                    score, health, rating, details = self.calc_fitness(player, server_info)

                    # Display the standard quality info
                    message = "Quality info for {0[ServerName]}: Rating {1}, Quality {2}".format(server_info, rating, health)
                    self._xmpp.send_message(cmdtype, target, message)

                    # Log it
                    self.record_quality_usage(cmdname, result[0], server_info, data=details)

    def quality_detailed(self, cmdtype, cmdname, args, target, user, room):
        # Get the server info
        result = self.load_server_info(args, user)

        # Check the response
        if not result[0]:
            self._xmpp.send_message(cmdtype, target, result[1])
        else:
            server_info = result[1]

            # Check server
            result = self.check_fitness(server_info, user)

            # Check the response
            if not result[0]:
                self._xmpp.send_message(cmdtype, target, result[1])

                # Log it
                self.record_quality_usage(cmdname, result[0], server_info)
            else:
                # Load the player data
                player = self._api.wrapper(self._api.user_stats, user)

                if player is None:
                    self._xmpp.send_message(cmdtype, target, "Error: Failed to load player stats.")
                else:
                    score, health, rating, details = self.calc_fitness(player, server_info)

                    # Display the detailed quality info
                    score = int((details["score"]["sum"] / details["threshold"]["sum"]) * 100)
                    rank = int((details["score"]["rank"] / details["threshold"]["rank"]) * 100)
                    level = int((details["score"]["level"] / details["threshold"]["level"]) * 100)
                    message = "Quality info for {0[ServerName]}: Rating {1}, Quality {2}, Score {3}% [Rating {4}% + Level {5}%]".format(server_info, rating, health, score, rank, level)
                    self._xmpp.send_message(cmdtype, target, message)

                    # Log it
                    self.record_quality_usage(cmdname, result[0], server_info, data=details)


plugin = ServerRankPlugin
