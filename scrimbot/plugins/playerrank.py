# -*- coding: utf-8 -*-

import time
import math
import logging
from scrimbot.cache import CacheList
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin
from scrimbot.util import format_dhms, get_bracket

logger = logging.getLogger(__name__)


class PlayerRankPlugin(BasePlugin):
    @property
    def name(self):
        return "playerrank"

    def enable(self):
        # Register config
        self.register_config("plugins.playerrank.limit.count", 0)
        self.register_config("plugins.playerrank.limit.period", 60 * 60 * 2)
        self.register_config("plugins.playerrank.restricted.mmr", False)
        self.register_config("plugins.playerrank.bracket_range", 0)

        # Register cache
        self.register_cache("mmr_usage")

        # Register group
        self.register_group("mmr")

        # Register commands
        self.register_command(CommandType.PM, "mmr", self.mmr)
        self.register_command(CommandType.PM, "glicko", self.mmr, flags=["alias"])
        self.register_command(CommandType.PM, "elo", self.elo, flags=["hidden", "safe"])

    def disable(self):
        # Unregister config
        self.unregister_config("plugins.playerrank.limit.count")
        self.unregister_config("plugins.playerrank.limit.period")
        self.unregister_config("plugins.playerrank.restricted.mmr")
        self.unregister_config("plugins.playerrank.bracket_range")

        # Unregister cache
        self.unregister_cache("mmr_usage")

        # Unregister group
        self.unregister_group("mmr")

        # Unregister commands
        self.unregister_command(CommandType.PM, "mmr")
        self.unregister_command(CommandType.PM, "glicko")
        self.unregister_command(CommandType.PM, "elo")

    def connected(self):
        pass

    def disconnected(self):
        pass

    def limit_active(self, user):
        return self._config.plugins.playerrank.limit.count > 0 and \
            not self._permissions.user_check_group(user, "admin")

    def user_overlimit(self, user):
        if not self.limit_active(user):
            return False

        self.update_usage(user)

        try:
            return len(self._cache["mmr_usage"][user]) >= self._config.plugins.playerrank.limit.count
        except KeyError:
            return False

    def next_check(self, user):
        return math.ceil(self._config.plugins.playerrank.limit.period - (time.time() - self._cache["mmr_usage"][user][0]))

    def update_usage(self, user):
        if self.limit_active(user):
            if user not in self._cache["mmr_usage"]:
                return

            now = time.time()
            for _time in self._cache["mmr_usage"][user][:]:
                if _time < now - self._config.plugins.playerrank.limit.period:
                    self._cache["mmr_usage"][user].remove(_time)

    def increment_usage(self, user):
        if self.limit_active(user):
            if user not in self._cache["mmr_usage"]:
                self._cache["mmr_usage"][user] = CacheList()

            # Increment the usage
            self._cache["mmr_usage"][user].append(time.time())

    def mmr(self, cmdtype, cmdname, args, target, user, room):
        # Check if the user can perform a mmr lookup
        if self._config.plugins.playerrank.restricted.mmr and not self._permissions.user_check_groups(user, ("admin", "mmr")):
            self._xmpp.send_message(cmdtype, target, "Access to looking up a player's MMR is restricted.")
        # Check if the user is over their limit
        elif self.user_overlimit(user):
            self._xmpp.send_message(cmdtype, target, "You have reached your limit of MMR lookups. (Next check allowed in {0})".format(format_dhms(self.next_check(user))))
        else:
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
            stats = self._api.get_user_stats(guid)

            # Check for player data
            if stats is None:
                self._xmpp.send_message(cmdtype, target, "Error: Failed to look up player stats.")
            elif "MatchMaking.Rating" not in stats or "MatchMaking.Deviation" not in stats:
                self._xmpp.send_message(cmdtype, target, "Error: Player does not appear to have an MMR.")
            else:
                mmr = stats["MatchMaking.Rating"]
                deviation = stats["MatchMaking.Deviation"]

                # Update the usage
                self.increment_usage(user)

                # Format the message
                if self._config.plugins.playerrank.bracket_range == 0:
                    message = "{0} MMR is {1:.2f}, with an approximate true rating between {2:.2f}-{3:.2f}.".format(identifier, mmr, mmr - (deviation * 2), mmr + (deviation * 2))
                else:
                    low, high = get_bracket(mmr, self._config.plugins.playerrank.bracket_range)
                    message = "{0} MMR bracket is {1}-{2}.".format(identifier, low, high)

                if self.limit_active(user):
                    # Add the limit message
                    message += " (Request {0} out of {1} allowed in the next {2})".format(len(self._cache["mmr_usage"][user]),
                                                                                          self._config.plugins.playerrank.limit.count,
                                                                                          format_dhms(self.next_check(user)))

                self._xmpp.send_message(cmdtype, target, message)

    def elo(self, cmdtype, cmdname, args, target, user, room):
        # Easter egg
        self._xmpp.send_message(cmdtype, target, "Fuck off. (use !mmr)")


plugin = PlayerRankPlugin
