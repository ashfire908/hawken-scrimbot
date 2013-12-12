# -*- coding: utf-8 -*-

from copy import deepcopy
import math
import hawkenapi.exceptions
from scrimbot.plugins.base import BasePlugin, Command, CommandType


class ServerRankPlugin(BasePlugin):
    def enable(self):
        # Register config
        self.register_config("plugins.serverrank.arbitrary_servers", True)
        self.register_config("plugins.serverrank.min_users", 2)

        # Register commands
        self.register_command(Command(CommandType.ALL, "serverrank", self.server_rank))
        self.register_command(Command(CommandType.ALL, "serverrankdetailed", self.server_rank_detailed))
        self.register_command(Command(CommandType.ALL, "sr", self.server_rank, flags=["alias"]))
        self.register_command(Command(CommandType.ALL, "srd", self.server_rank_detailed, flags=["alias"]))

    def disable(self):
        # Unregister config
        self.unregister_config("plugins.serverrank.arbitrary_servers")
        self.unregister_config("plugins.serverrank.min_users")

        # Unregister commands
        self.unregister_command(Command.format_id(CommandType.ALL, "serverrank"))
        self.unregister_command(Command.format_id(CommandType.ALL, "serverrankdetailed"))
        self.unregister_command(Command.format_id(CommandType.ALL, "sr"))
        self.unregister_command(Command.format_id(CommandType.ALL, "srd"))

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

    def load_server_info(self, args, user):
        if len(args) > 0:
            # Check if this user is allowed to pick what server to check
            if self.config.plugins.serverrank.arbitrary_servers or self.permissions.user_check_group(user, "admin"):
                # Load the server info by name
                server_info = self.api.wrapper(self.api.server_by_name, args[0])

                if not server_info:
                    return False, "No such server."
            else:
                return False, "Rankings for arbitrary servers are disabled."
        else:
            # Find the server the user is on
            server = self.api.wrapper(self.api.user_server, user)
            # Check if they are actually on a server
            if server is None:
                return False, "You are not on a server."
            else:
                # Load the server info
                server_info = self.api.wrapper(self.api.server_list, server[0])

                if not server_info:
                    return False, "Error: Failed to load server info."

        return True, server_info

    def server_min(self, server):
        if self.config.plugins.serverrank.min_users == -1:
            min_players = server["MinUsers"]
        else:
            min_players = self.config.plugins.serverrank.min_users

        return min_players

    def check_server(self, server_info, user):
        if len(server_info["Users"]) < 1:
            return False, "No one is on the server '{0[ServerName]}'.".format(server_info)

        if not self.permissions.user_check_group(user, "admin") and \
           len(server_info["Users"]) < self.server_min(server_info):
            return False, "There needs to be at least {0} players on the server to use this command.".format(self.server_min(server_info))

        return True, None

    def server_rank(self, cmdtype, cmdname, args, target, user, room):
        # Get the server info
        result = self.load_server_info(args, user)

        # Check the response
        if not result[0]:
            self.xmpp.send_message(cmdtype, target, result[1])
        else:
            server_info = result[1]

            # Check server
            result = self.check_server(server_info, user)

            # Check the response
            if not result[0]:
                self.xmpp.send_message(cmdtype, target, result[1])
            else:
                # Display the standard server rank
                message = "Ranking info for {0[ServerName]}: MMR Average: {0[ServerRanking]}, Average Pilot Level: {0[DeveloperData][AveragePilotLevel]}".format(server_info)
                self.xmpp.send_message(cmdtype, target, message)

    def server_rank_detailed(self, cmdtype, cmdname, args, target, user, room):
        # Get the server info
        result = self.load_server_info(args, user)

        # Check the response
        if not result[0]:
            self.xmpp.send_message(cmdtype, target, result[1])
        else:
            server_info = result[1]

            # Check server
            result = self.check_server(server_info, user)

            # Check the response
            if not result[0]:
                self.xmpp.send_message(cmdtype, target, result[1])
            else:
                # Load the MMR for all the players on the server
                try:
                    data = self.api.wrapper(self.api.user_stats, server_info["Users"])
                except hawkenapi.exceptions.InvalidBatch:
                    self.xmpp.send_message(cmdtype, target, "Error: Failed to load player data.")
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

                    if ranked_users < server_min and not self.permissions.user_check_group(user, "admin"):
                        self.xmpp.send_message(cmdtype, target, "There needs to be {0} ranked players (i.e. have an MMR set) on the server to use this command - only {1} of the players are currently ranked.".format(server_min, ranked_users))
                    else:
                        # Process stats, display
                        mmr_info = self.mmr_stats(users)

                        message = "MMR breakdown for {0[ServerName]}: Average MMR: {1[mean]:.2f}, Max MMR: {1[max]:.2f}, Min MMR: {1[min]:.2f}, Standard deviation {1[stddev]:.3f}".format(server_info, mmr_info)
                        self.xmpp.send_message(cmdtype, target, message)


plugin = ServerRankPlugin
