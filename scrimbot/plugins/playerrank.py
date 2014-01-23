# -*- coding: utf-8 -*-

import time
import math
import logging
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin
from scrimbot.util import enum, format_dhms

LookupMode = enum(MMR="mmr", RAW="raw")
logger = logging.getLogger(__name__)


class PlayerRankPlugin(BasePlugin):
    @property
    def name(self):
        return "playerrank"

    def enable(self):
        # Register config
        self.register_config("plugins.playerrank.limit.count", 0)
        self.register_config("plugins.playerrank.limit.period", 60 * 60 * 2)
        self.register_config("plugins.playerrank.limit.mmr", True)
        self.register_config("plugins.playerrank.limit.raw", True)
        self.register_config("plugins.playerrank.restricted.mmr", False)
        self.register_config("plugins.playerrank.restricted.raw", False)
        self.register_config("plugins.playerrank.bracket_range", 0)

        # Register group
        self.register_group("mmr")

        # Register commands
        self.register_command(CommandType.PM, "mmr", self.mmr)
        self.register_command(CommandType.PM, "rawmmr", self.rawmmr)
        self.register_command(CommandType.PM, "elo", self.elo, flags=["hidden", "safe"])
        self.register_command(CommandType.PM, "glicko", self.glicko, flags=["hidden", "safe"])

        # Setup usage tracking
        self.mmr_usage = {}

    def disable(self):
        # Unregister config
        self.unregister_config("plugins.playerrank.limit.count")
        self.unregister_config("plugins.playerrank.limit.period")
        self.unregister_config("plugins.playerrank.limit.mmr")
        self.unregister_config("plugins.playerrank.limit.raw")
        self.unregister_config("plugins.playerrank.restricted.mmr")
        self.unregister_config("plugins.playerrank.restricted.raw")
        self.unregister_config("plugins.playerrank.bracket_range")

        # Unregister group
        self.unregister_group("mmr")

        # Unregister commands
        self.unregister_command(CommandType.PM, "mmr")
        self.unregister_command(CommandType.PM, "rawmmr")
        self.unregister_command(CommandType.PM, "elo")
        self.unregister_command(CommandType.PM, "glicko")

    def connected(self):
        pass

    def disconnected(self):
        pass

    def limit_active(self, user, mode):
        return self._config["plugins.playerrank.limit." + mode] and \
            self._config.plugins.playerrank.limit.count > 0 and \
            not self._permissions.user_check_group(user, "admin")

    def user_overlimit(self, user, mode):
        if not self.limit_active(user, mode):
            return False

        self.update_usage(user, mode)

        try:
            return len(self.mmr_usage[user]) >= self._config.plugins.playerrank.limit.count
        except KeyError:
            return False

    def next_check(self, user):
        return math.ceil(self._config.plugins.playerrank.limit.period - (time.time() - self.mmr_usage[user][0]))

    def get_bracket(self, mmr):
        x = math.floor(mmr / self._config.plugins.playerrank.bracket_range)
        low = x * self._config.plugins.playerrank.bracket_range
        high = (x + 1) * self._config.plugins.playerrank.bracket_range

        return low, high

    def lookup_allowed(self, user, mode):
        if self._config["plugins.playerrank.restricted." + mode] and not self._permissions.user_check_groups(user, ("admin", "mmr")):
            return False, "Access to looking up player MMR is restricted."

        if self.user_overlimit(user, mode):
            return False, "You have reached your limit of MMR lookups. (Next check allowed in {0})".format(format_dhms(self.next_check(user)))

        return True, None

    def update_usage(self, user, mode):
        if self.limit_active(user, mode):
            if user not in self.mmr_usage:
                return

            now = time.time()
            for _time in self.mmr_usage[user][:]:
                if _time < now - self._config.plugins.playerrank.limit.period:
                    self.mmr_usage[user].remove(_time)

    def increment_usage(self, user, mode):
        if self.limit_active(user, mode):
            if user not in self.mmr_usage:
                self.mmr_usage[user] = []

            # Increment the usage
            self.mmr_usage[user].append(time.time())

    def get_mmr(self, guid):
        # Get the user's stats
        stats = self._api.get_user_stats(guid)

        # Check for player data
        if stats is None:
            return False, "Error: Failed to look up player stats."

        # Check for a MMR
        if "MatchMaking.Rating" not in stats:
            return False, "Error: Player does not appear to have an MMR."

        return True, stats["MatchMaking.Rating"]

    def lookup_mmr(self, cmdname, cmdtype, args, target, user, room, mode):
        # Check if this user can perform a mmr lookup
        result = self.lookup_allowed(user, mode)
        if not result[0]:
            self._xmpp.send_message(cmdtype, target, result[1])
            return

        # Determine the requested user
        if len(args) > 0:
            guid = self._cache.get_guid(args[0])
        else:
            guid = user

        # Setup output, check perms, target user
        if guid == user:
            identifier = "Your"
        else:
            if self._permissions.user_check_group(user, "admin"):
                if not guid:
                    self._xmpp.send_message(cmdtype, target, "No such user exists.")
                    return
                identifier = "{}'s".format(args[0])
            else:
                self._xmpp.send_message(cmdtype, target, "You are not an admin.")
                return

        # Grab the mmr
        result = self.get_mmr(guid)

        # Check the response
        if not result[0]:
            self._xmpp.send_message(cmdtype, target, result[1])
        else:
            if mode == LookupMode.MMR:
                mmr = int(result[1])
            else:
                mmr = result[1]

            # Update the usage
            self.increment_usage(user, mode)

            if mode == LookupMode.MMR and self._config.plugins.playerrank.bracket_range > 0:
                # Apply the range
                low, high = self.get_bracket(mmr)

                # Format the message
                message = "{0} MMR bracket is {1}-{2}.".format(identifier, low, high)
            else:
                # Format the message
                message = "{0} MMR is {1}.".format(identifier, mmr)

            if self.limit_active(user, mode):
                # Add the limit message
                message += " (Request {0} out of {1} allowed in the next {2})".format(len(self.mmr_usage[user]),
                                                                                      self._config.plugins.playerrank.limit.count,
                                                                                      format_dhms(self.next_check(user)))

            self._xmpp.send_message(cmdtype, target, message)

    def mmr(self, cmdtype, cmdname, args, target, user, room):
        self.lookup_mmr(cmdname, cmdtype, args, target, user, room, LookupMode.MMR)

    def rawmmr(self, cmdtype, cmdname, args, target, user, room):
        self.lookup_mmr(cmdname, cmdtype, args, target, user, room, LookupMode.RAW)

    def elo(self, cmdtype, cmdname, args, target, user, room):
        # Easter egg
        self._xmpp.send_message(cmdtype, target, "Fuck off. (use !mmr)")

    def glicko(self, cmdtype, cmdname, args, target, user, room):
        # Easter egg
        self._xmpp.send_message(cmdtype, target, ":D :D :D")


plugin = PlayerRankPlugin
