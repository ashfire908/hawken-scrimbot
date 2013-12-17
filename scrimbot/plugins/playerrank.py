# -*- coding: utf-8 -*-

import logging
from scrimbot.plugins.base import BasePlugin, CommandType
from scrimbot.util import format_dhms

logger = logging.getLogger(__name__)


class PlayerRankPlugin(BasePlugin):
    @property
    def name(self):
        return "playerrank"

    def enable(self):
        # Register config
        self.register_config("plugins.playerrank.mmr_limit", -1)
        self.register_config("plugins.playerrank.mmr_period", 60 * 60 * 6)
        self.register_config("plugins.playerrank.mmr_restricted", False)

        # Register group
        self.register_group("mmr")

        # Register commands
        self.register_command(CommandType.PM, "mmr", self.mmr)
        self.register_command(CommandType.PM, "rawmmr", self.rawmmr)
        self.register_command(CommandType.PM, "elo", self.elo, flags=["hidden", "safe"])

        # Setup usage tracking
        self.mmr_usage = {}

    def disable(self):
        # Unregister config
        self.unregister_config("plugins.playerrank.mmr_limit")
        self.unregister_config("plugins.playerrank.mmr_period")
        self.unregister_config("plugins.playerrank.mmr_restricted")

        # Unregister group
        self.unregister_group("mmr")

        # Unregister commands
        self.unregister_command(CommandType.PM, "mmr")
        self.unregister_command(CommandType.PM, "rawmmr")
        self.unregister_command(CommandType.PM, "elo")

    def connected(self):
        if self.config.plugins.playerrank.mmr_limit > 0:
            # Start the usage reset thread
            self.register_task("mmr_reset", self.config.plugins.playerrank.mmr_period, self.reset_mmr, repeat=True)

    def disconnected(self):
        # Stop the reset thread
        self.unregister_task("mmr_reset")

    def reset_mmr(self):
        logger.info("Resetting MMR usage.")

        # A loop would probably be better here
        self.mmr_usage = dict.fromkeys(self.mmr_usage, 0)

    def limit_active(self, user):
        return self.config.plugins.playerrank.mmr_limit != -1 and not self.permissions.user_check_group(user, "admin")

    def lookup_allowed(self, user):
        if self.config.plugins.playerrank.mmr_restricted and not self.permissions.user_check_groups(user, ("admin", "mmr")):
            return False, "Access to looking up player MMR is restricted."

        if self.user_overlimit(user):
            return False, "You have reached your limit of MMR lookups. (Limit reset every {0})".format(format_dhms(self.config.plugins.playerrank.mmr_period))

        return True, None

    def user_update_usage(self, user):
        if self.limit_active(user):
            if user not in self.mmr_usage:
                self.mmr_usage[user] = 0

            # Increment the usage
            self.mmr_usage[user] += 1

    def user_overlimit(self, user):
        if not self.limit_active(user):
            return False

        try:
            return self.mmr_usage[user] >= self.config.plugins.playerrank.mmr_limit
        except KeyError:
            return False

    def get_mmr(self, guid):
        # Get the user's stats
        stats = self.api.wrapper(self.api.user_stats, guid)

        # Check for player data
        if stats is None:
            return False, "Error: Failed to look up player stats."

        # Check for a MMR
        if "MatchMaking.Rating" not in stats.keys():
            return False, "Error: Player does not appear to have a MMR."

        return True, int(stats["MatchMaking.Rating"])

    def get_rawmmr(self, guid):
        # Get the user's stats
        stats = self.api.wrapper(self.api.user_stats, guid)

        # Check for player data
        if stats is None:
            return False, "Error: Failed to look up player stats."

        # Check for a MMR
        if "MatchMaking.Rating" not in stats.keys():
            return False, "Error: Player does not appear to have a MMR."

        return True, stats["MatchMaking.Rating"]

    def lookup_mmr(self, cmdname, cmdtype, args, target, user, room, method):
        # Check if this user can perform a mmr lookup
        result = self.lookup_allowed(user)
        if not result[0]:
            self.xmpp.send_message(cmdtype, target, result[1])
            return

        # Determine the requested user
        if len(args) > 0:
            guid = self.cache.get_guid(args[0])
        else:
            guid = user

        # Setup output, check perms, target user
        if guid == user:
            identifier = "Your"
        else:
            if self.permissions.user_check_group(user, "admin"):
                if not guid:
                    self.xmpp.send_message(cmdtype, target, "No such user exists.")
                    return
                identifier = "{}'s".format(args[0])
            else:
                self.xmpp.send_message(cmdtype, target, "You are not an admin.")
                return

        # Grab the mmr
        result = method(guid)

        # Check the response
        if not result[0]:
            self.xmpp.send_message(cmdtype, target, result[1])
        else:
            # Update the usage
            self.user_update_usage(user)

            # Display the mmr
            if self.limit_active(user):
                self.xmpp.send_message(cmdtype, target, "{0} MMR is {1}. ({2} out of {3} requests)".format(identifier, result[1], self.mmr_usage[user], self.config.plugins.playerrank.mmr_limit))
            else:
                self.xmpp.send_message(cmdtype, target, "{0} MMR is {1}.".format(identifier, result[1]))

    def mmr(self, cmdtype, cmdname, args, target, user, room):
        self.lookup_mmr(cmdname, cmdtype, args, target, user, room, self.get_mmr)

    def rawmmr(self, cmdtype, cmdname, args, target, user, room):
        self.lookup_mmr(cmdname, cmdtype, args, target, user, room, self.get_rawmmr)

    def elo(self, cmdtype, cmdname, args, target, user, room):
        # Easter egg
        self.xmpp.send_message(cmdtype, target, "Fuck off. (use !mmr)")


plugin = PlayerRankPlugin
