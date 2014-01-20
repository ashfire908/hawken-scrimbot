# -*- coding: utf-8 -*-

import time
import math
import logging
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin
from scrimbot.util import format_dhms

logger = logging.getLogger(__name__)


class PlayerRankPlugin(BasePlugin):
    @property
    def name(self):
        return "playerrank"

    def enable(self):
        # Register config
        self.register_config("plugins.playerrank.limit", 0)
        self.register_config("plugins.playerrank.period", 60 * 60 * 2)
        self.register_config("plugins.playerrank.restricted", False)

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
        self.unregister_config("plugins.playerrank.limit")
        self.unregister_config("plugins.playerrank.period")
        self.unregister_config("plugins.playerrank.restricted")

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

    def limit_active(self, user):
        return self._config.plugins.playerrank.limit > 0 and not self._permissions.user_check_group(user, "admin")

    def next_check(self, user):
        return math.ceil(self._config.plugins.playerrank.period - (time.time() - self.mmr_usage[user][0]))

    def lookup_allowed(self, user):
        if self._config.plugins.playerrank.restricted and not self._permissions.user_check_groups(user, ("admin", "mmr")):
            return False, "Access to looking up player MMR is restricted."

        if self.user_overlimit(user):
            return False, "You have reached your limit of MMR lookups. (Next check allowed in {0})".format(format_dhms(self.next_check(user)))

        return True, None

    def update_usage(self, user):
        if self.limit_active(user):
            if user not in self.mmr_usage:
                return

            now = time.time()
            for _time in self.mmr_usage[user][:]:
                if _time < now - self._config.plugins.playerrank.period:
                    self.mmr_usage[user].remove(_time)

    def increment_usage(self, user):
        if self.limit_active(user):
            if user not in self.mmr_usage:
                self.mmr_usage[user] = []

            # Increment the usage
            self.mmr_usage[user].append(time.time())

    def user_overlimit(self, user):
        if not self.limit_active(user):
            return False

        self.update_usage(user)

        try:
            return len(self.mmr_usage[user]) >= self._config.plugins.playerrank.limit
        except KeyError:
            return False

    def get_mmr(self, guid):
        # Get the user's stats
        stats = self._api.wrapper(self._api.user_stats, guid)

        # Check for player data
        if stats is None:
            return False, "Error: Failed to look up player stats."

        # Check for a MMR
        if "MatchMaking.Rating" not in stats:
            return False, "Error: Player does not appear to have an MMR."

        return True, int(stats["MatchMaking.Rating"])

    def get_rawmmr(self, guid):
        # Get the user's stats
        stats = self._api.wrapper(self._api.user_stats, guid)

        # Check for player data
        if stats is None:
            return False, "Error: Failed to look up player stats."

        # Check for a MMR
        if "MatchMaking.Rating" not in stats:
            return False, "Error: Player does not appear to have an MMR."

        return True, stats["MatchMaking.Rating"]

    def lookup_mmr(self, cmdname, cmdtype, args, target, user, room, method):
        # Check if this user can perform a mmr lookup
        result = self.lookup_allowed(user)
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
        result = method(guid)

        # Check the response
        if not result[0]:
            self._xmpp.send_message(cmdtype, target, result[1])
        else:
            # Update the usage
            self.increment_usage(user)

            # Display the mmr
            if self.limit_active(user):
                self._xmpp.send_message(cmdtype, target, "{0} MMR is {1}. (Request {2} out of {3} allowed in the next {4})".format(identifier,
                                        result[1], len(self.mmr_usage[user]), self._config.plugins.playerrank.limit, format_dhms(self.next_check(user))))
            else:
                self._xmpp.send_message(cmdtype, target, "{0} MMR is {1}.".format(identifier, result[1]))

    def mmr(self, cmdtype, cmdname, args, target, user, room):
        self.lookup_mmr(cmdname, cmdtype, args, target, user, room, self.get_mmr)

    def rawmmr(self, cmdtype, cmdname, args, target, user, room):
        self.lookup_mmr(cmdname, cmdtype, args, target, user, room, self.get_rawmmr)

    def elo(self, cmdtype, cmdname, args, target, user, room):
        # Easter egg
        self._xmpp.send_message(cmdtype, target, "Fuck off. (use !mmr)")

    def glicko(self, cmdtype, cmdname, args, target, user, room):
        # Easter egg
        self._xmpp.send_message(cmdtype, target, ":D :D :D")


plugin = PlayerRankPlugin
