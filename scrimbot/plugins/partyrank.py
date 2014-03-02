# -*- coding: utf-8 -*-

import logging
import hawkenapi.exceptions
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin
from scrimbot.util import stat_analysis, get_bracket

logger = logging.getLogger(__name__)


class PartyRankPlugin(BasePlugin):
    @property
    def name(self):
        return "partyrank"

    def enable(self):
        # Register config
        self.register_config("plugins.partyrank.min_users", 2)
        self.register_config("plugins.partyrank.log_usage", False)
        self.register_config("plugins.partyrank.show_minmax", True)
        self.register_config("plugins.partyrank.minmax_bracket", 100)

        # Register commands
        self.register_command(CommandType.PARTY, "partyrank", self.party_rank, alias=["pr"])
        self.register_command(CommandType.PARTY, "partyrankdetailed", self.party_rank_detailed, alias=["prd"])

    def disable(self):
        pass

    def connected(self):
        pass

    def disconnected(self):
        pass

    def record_usage(self, command, returned, party, data=None):
        if self._config.plugins.partyrank.log_usage:
            if returned:
                status = "returned"
            else:
                status = "rejected"

            message = "Call usage for [{0}]: Party {1} with {2} player(s) {3} request".format(command, party.name or party.guid, len(party.players), status)

            if data is not None:
                message += " - Avg: {0[mean]:.2f} Max: {0[max]:.2f} Min: {0[min]:.2f} Stddev: {0[stddev]:.3f}".format(data)

            logger.info(message)

    def check_party(self, party, user):
        if len(party.players) < 1:
            return False, "No one is in the party."

        if not self._permissions.user_check_group(user, "admin") and \
           len(party.players) < self._config.plugins.partyrank.min_users:
            return False, "There needs to be at least {0} players in the party to use this command.".format(self._config.plugins.partyrank.min_users)

        return True, None

    def party_rank(self, cmdtype, cmdname, args, target, user, party):
        # Check the party
        result = self.check_party(party, user)

        # Check the response
        if not result[0]:
            self._xmpp.send_message(cmdtype, target, result[1])
        else:
            try:
                data = self._api.get_user_stats(list(party.players))
            except hawkenapi.exceptions.InvalidBatch:
                self._xmpp.send_message(cmdtype, target, "Error: Failed to load player data.")
            else:
                mmr_info = stat_analysis(data, "MatchMaking.Rating")
                pilot_level = stat_analysis(data, "Progress.Pilot.Level")

                if not mmr_info:
                    self._xmpp.send_message(cmdtype, target, "There are no ranked players in the party.")

                    # Log it
                    self.record_usage(cmdname, False, party)
                elif len(mmr_info["list"]) < self._config.plugins.partyrank.min_users and not self._permissions.user_check_group(user, "admin"):
                    self._xmpp.send_message(cmdtype, target, "There needs to be at least {0} ranked players in the party - only {1} of the players are currently ranked.".format(self._config.plugins.partyrank.min_users, len(mmr_info["list"])))

                    # Log it
                    self.record_usage(cmdname, False, party, mmr_info)
                else:
                    # Display the simple party rank info
                    message = "Ranking info for the party: MMR Average: {0[mean]:.2f}, Average Pilot Level: {1[mean]:.0f}".format(mmr_info, pilot_level)
                    self._xmpp.send_message(cmdtype, target, message)

                    # Log it
                    self.record_usage(cmdname, True, party, mmr_info)

    def party_rank_detailed(self, cmdtype, cmdname, args, target, user, party):
        # Check the party
        result = self.check_party(party, user)

        # Check the response
        if not result[0]:
            self._xmpp.send_message(cmdtype, target, result[1])
        else:
            try:
                data = self._api.get_user_stats(list(party.players))
            except hawkenapi.exceptions.InvalidBatch:
                self._xmpp.send_message(cmdtype, target, "Error: Failed to load player data.")
            else:
                mmr_info = stat_analysis(data, "MatchMaking.Rating")

                if not mmr_info:
                    self._xmpp.send_message(cmdtype, target, "There are no ranked players in the party.")

                    # Log it
                    self.record_usage(cmdname, False, party)
                elif len(mmr_info["list"]) < self._config.plugins.partyrank.min_users and not self._permissions.user_check_group(user, "admin"):
                    self._xmpp.send_message(cmdtype, target, "There needs to be at least {0} ranked players in the party - only {1} of the players are currently ranked.".format(self._config.plugins.partyrank.min_users, len(mmr_info["list"])))

                    # Log it
                    self.record_usage(cmdname, False, party, mmr_info)
                else:
                    # Display stats
                    if self._config.plugins.partyrank.show_minmax:
                        if self._config.plugins.partyrank.minmax_bracket == 0:
                            minmax = "Min MMR: {0[min]:.2f}, Max MMR: {0[max]:.2f}, ".format(mmr_info)
                        else:
                            low = get_bracket(mmr_info["min"], self._config.plugins.partyrank.minmax_bracket)[0]
                            high = get_bracket(mmr_info["max"], self._config.plugins.partyrank.minmax_bracket)[1]

                            minmax = "MMR Range: {0}-{1}, ".format(low, high)
                    else:
                        minmax = ""

                    message = "MMR breakdown for the party: Average MMR: {0[mean]:.2f}, {1}Standard deviation: {0[stddev]:.3f}".format(mmr_info, minmax)
                    self._xmpp.send_message(cmdtype, target, message)


plugin = PartyRankPlugin
