# -*- coding: utf-8 -*-

from copy import deepcopy
import math
import logging
import hawkenapi.exceptions
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin

logger = logging.getLogger(__name__)


class PartyRankPlugin(BasePlugin):
    @property
    def name(self):
        return "partyrank"

    def enable(self):
        # Register config
        self.register_config("plugins.partyrank.min_users", 2)

        # Register commands
        self.register_command(CommandType.PARTY, "partyrank", self.party_rank)
        self.register_command(CommandType.PARTY, "partyrankdetailed", self.party_rank_detailed)
        self.register_command(CommandType.PARTY, "pr", self.party_rank, flags=["alias"])
        self.register_command(CommandType.PARTY, "prd", self.party_rank_detailed, flags=["alias"])

    def disable(self):
        # Unregister config
        self.unregister_config("plugins.partyrank.min_users")

        # Unregister commands
        self.unregister_command(CommandType.PARTY, "partyrank")
        self.unregister_command(CommandType.PARTY, "partyrankdetailed")
        self.unregister_command(CommandType.PARTY, "pr")
        self.unregister_command(CommandType.PARTY, "prd")

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
            mmr["mean"] = math.fsum(mmr["list"]) / len(mmr["list"])

            # Process each user's stats
            for user in users.values():
                # Check if they have an mmr
                if not user["mmr"] is None:
                    # Calculate the deviation
                    user["deviation"] = user["mmr"] - mmr["mean"]

            # Calculate standard deviation
            stddev_list = [user["deviation"] ** 2 for user in users.values() if "deviation" in user]
            if len(stddev_list) > 0:
                mmr["stddev"] = math.sqrt(math.fsum(stddev_list) / len(stddev_list))

            return mmr
        else:
            # Can't pull mmr out of thin air
            return False

    def check_party(self, party, user):
        if len(party.players) < 1:
            return False, "No one is in the party."

        if not self._permissions.user_check_group(user, "admin") and \
           len(party.players) < self._config.plugins.partyrank.min_users:
            return False, "There needs to be at least {0} players in the party to use this command.".format(self._config.plugins.partyrank.min_users)

        return True, None

    def load_party_data(self, party):
        # Get the player stats data
        try:
            data = self._api.get_user_stats(party.players)
        except hawkenapi.exceptions.InvalidBatch:
            return False, "Error: Failed to load player data."
        else:
            users = {}
            for user_data in data:
                try:
                    mmr = user_data["MatchMaking.Rating"]
                except KeyError:
                    # In case no MMR is set for the user
                    mmr = None

                try:
                    pilot_level = user_data["Progress.Pilot.Level"]
                except KeyError:
                    # In case no Pilot Level is set
                    pilot_level = None

                users[user_data["Guid"]] = {"mmr": mmr, "pilotlevel": pilot_level}

            return True, users

    def party_rank(self, cmdtype, cmdname, args, target, user, room):
        # Get the party
        try:
            party = self._client.active_parties[room]
        except KeyError:
            self._xmpp.send_message(cmdtype, target, "Error: Couldn't find party object. This is a bug, please report it!")
            logger.warn("Could not find active party object for {0}.".format(room))
        else:
            # Check the party
            result = self.check_party(party, user)

            # Check the response
            if not result[0]:
                self._xmpp.send_message(cmdtype, target, result[1])
            else:
                # Load the party data
                result = self.load_party_data(party)

                # Check the response
                if not result[0]:
                    self._xmpp.send_message(cmdtype, target, result[1])
                else:
                    users = result[1]

                    # Check if there are enough ranked users
                    ranked_users = len([x for x in users.values() if x["mmr"] is not None])

                    if ranked_users < self._config.plugins.partyrank.min_users and not self._permissions.user_check_group(user, "admin"):
                        self._xmpp.send_message(cmdtype, target, "There needs to be {0} ranked players (i.e. have an MMR set) in the party to use this command - only {1} of the players are currently ranked.".format(self._config.plugins.partyrank.min_users, ranked_users))
                    else:
                        # Process stats, display
                        mmrs = [x["mmr"] for x in users.values() if x["mmr"] is not None]
                        pilot_levels = [x["pilotlevel"] for x in users.values() if x["pilotlevel"] is not None]

                        mmr_average = math.fsum(mmrs) / len(mmrs)
                        pilot_level_average = math.fsum(pilot_levels) / len(pilot_levels)

                        # Display the simple party rank info
                        message = "Ranking info for the party: MMR Average: {0:.2f}, Average Pilot Level: {1:.0f}".format(mmr_average, pilot_level_average)
                        self._xmpp.send_message(cmdtype, target, message)

    def party_rank_detailed(self, cmdtype, cmdname, args, target, user, room):
        # Get the party
        try:
            party = self._client.active_parties[room]
        except KeyError:
            self._xmpp.send_message(cmdtype, target, "Error: Couldn't find party object. This is a bug, please report it!")
            logger.warn("Could not find active party object for {0}.".format(room))
        else:
            # Check the party
            result = self.check_party(party, user)

            # Check the response
            if not result[0]:
                self._xmpp.send_message(cmdtype, target, result[1])
            else:
                # Load the party data
                result = self.load_party_data(party)

                # Check the response
                if not result[0]:
                    self._xmpp.send_message(cmdtype, target, result[1])
                else:
                    users = result[1]

                    # Check if there are enough ranked users
                    ranked_users = len([x for x in users.values() if x["mmr"] is not None])

                    if ranked_users < self._config.plugins.partyrank.min_users and not self._permissions.user_check_group(user, "admin"):
                        self._xmpp.send_message(cmdtype, target, "There needs to be {0} ranked players (i.e. have an MMR set) in the party to use this command - only {1} of the players are currently ranked.".format(self._config.plugins.partyrank.min_users, ranked_users))
                    else:
                        # Process stats, display
                        mmr_info = self.mmr_stats(users)

                        message = "MMR breakdown for the party: Average MMR: {0[mean]:.2f}, Max MMR: {0[max]:.2f}, Min MMR: {0[min]:.2f}, Standard deviation {0[stddev]:.3f}".format(mmr_info)
                        self._xmpp.send_message(cmdtype, target, message)


plugin = PartyRankPlugin
