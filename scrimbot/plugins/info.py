# -*- coding: utf-8 -*-

import itertools
from scrimbot.api import region_names, map_names, gametype_names
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin


class InfoPlugin(BasePlugin):
    @property
    def name(self):
        return "info"

    def enable(self):
        # Register config
        self.register_config("plugins.info.arbitrary_servers", True)
        self.register_config("plugins.info.min_users", 2)

        # Register commands
        self.register_command(CommandType.PM, "botinfo", self.botinfo, safe=True)
        self.register_command(CommandType.PM, "foundabug", self.foundabug, safe=True)
        self.register_command(CommandType.ALL, "commands", self.commands, alias=["?"])
        self.register_command(CommandType.ALL, "plugins", self.plugin_list, safe=True)
        self.register_command(CommandType.ALL, "whoami", self.whoami)
        self.register_command(CommandType.ALL, "hammertime", self.hammertime, hidden=True, safe=True)
        self.register_command(CommandType.PM, "serverinfo", self.server_info, alias=["srv", "si"])

    def disable(self):
        pass

    def connected(self):
        pass

    def disconnected(self):
        pass

    def botinfo(self, cmdtype, cmdname, args, target, user, party):
        message = """Hello, I am ScrimBot, the Hawken Scrim Bot. I do various competitive-related and utility functions. I am run by Ashfire908.

If you need help with the bot, send a pm to Ashfire908 on the Hawken forums, talk to him on the #hawkenscrim IRC channel on QuakeNet, or send an email to: scrimbot@ashfire908.com

This bot is an unofficial tool."""

        self._xmpp.send_message(cmdtype, target, message)

    def foundabug(self, cmdtype, cmdname, args, target, user, party):
        message = """If you have encounter an error with the bot, please send in an error report. Either send a pm to Ashfire908 on the Hawken forums, talk to him on the #hawkenscrim IRC channel, or send an email to: scrimbot@ashfire908.com

The error report should contain your callsign, what you were doing, the command you were using, what time is was (including timezone), and the error you received.

Not every bit of information is required, but at the very least you need to send in your callsign and the approximate time the error occurred; Otherwise the error can't be found."""

        self._xmpp.send_message(cmdtype, target, message)

    def commands(self, cmdtype, cmdname, args, target, user, party):
        if len(args) > 0:
            plugin_name = args[0].lower()
            if plugin_name in self._plugins.active:
                targets = self._plugins.active[plugin_name].registered["commands"].values()
            else:
                self._xmpp.send_message(cmdtype, target, "Error: No such plugin.")
                return
        else:
            targets = itertools.chain(*self._commands.registered.values())

        # Build command list
        handler_list = set()
        for handler in targets:
            # Filter out commands by type
            if handler.cmdtype not in (cmdtype, CommandType.ALL):
                continue

            # Filter out hidden commands
            if handler.flags.b.hidden:
                continue

            # Filter out commands by required permission
            if handler.flags.b.permsreq and not self._permissions.user_check_groups(user, handler.flags.data.permsreq):
                continue

            # Filter out parties lacking the needed feature(s)
            if handler.flags.b.partyfeat:
                missing = False
                for feature in handler.flags.data.partyfeat:
                    if feature not in party.features:
                        missing = True
                        break

                if missing:
                    continue

            # Add it to the display list
            handler_list.add(handler)

        # Display the list
        commands = [x.cmdname for x in handler_list]
        if len(commands) > 0:
            formatted = []
            for handler in sorted(handler_list, key=lambda x: x.cmdname):
                if commands.count(handler.cmdname) > 1:
                    formatted.append("{0}{1} {2}".format(self._config.bot.command_prefix, handler.plugin.name, handler.cmdname))
                else:
                    formatted.append("{0}{1}".format(self._config.bot.command_prefix, handler.cmdname))
            self._xmpp.send_message(cmdtype, target, "Available commands: {0}".format(" ".join(formatted)))
        else:
            self._xmpp.send_message(cmdtype, target, "No available commands found.")

    def plugin_list(self, cmdtype, cmdname, args, target, user, party):
        self._xmpp.send_message(cmdtype, target, "Loaded plugins: {0}".format(", ".join(sorted([plugin.name for plugin in self._plugins.active.values()]))))

    def whoami(self, cmdtype, cmdname, args, target, user, party):
        # Get the callsign
        callsign = self._api.get_user_callsign(user)

        # Check if we got a callsign back
        if callsign is None:
            message = "Error: Failed to look up your callsign."
        else:
            message = "You are '{0}'.".format(callsign)

        self._xmpp.send_message(cmdtype, target, message)

    def hammertime(self, cmdtype, cmdname, args, target, user, party):
        self._xmpp.send_message(cmdtype, target, "STOP! HAMMER TIME!")

    def server_info(self, cmdtype, cmdname, args, target, user, party):
        if len(args) > 0:
            # Check if this user is allowed to pick what server to check
            if not self._config.plugins.info.arbitrary_servers and not self._permissions.user_check_group(user, "admin"):
                self._xmpp.send_message(cmdtype, target, "Info for arbitrary servers is disabled.")
                return

            # Load the server info by name
            servers = self._api.get_server_by_name(args[0])
            if len(servers) < 1:
                self._xmpp.send_message(cmdtype, target, "No such server.")
                return
            if len(servers) > 1:
                self._xmpp.send_message(cmdtype, target, "Server name is ambiguous.")
                return

            server = servers[0]
        else:
            # Find the server the user is on
            servers = self._api.get_user_server(user, cache_bypass=True)
            if servers is None:
                self._xmpp.send_message(cmdtype, target, "You are not on a server.")
                return

            # Load the server info
            server = self._api.get_server(servers[0])

        # Return the server info
        message = "Server {0[ServerName]}: {1} on {2} in {3} - Users {4}/{0[MaxUsers]}".format(server, gametype_names.get(server["GameType"], server["GameType"]), map_names.get(server["Map"], server["Map"]), region_names.get(server["Region"], server["Region"]), len(server["Users"]))

        # Add rating
        if len(server["Users"]) >= self._config.plugins.info.min_users:
            message += " - Rating {0}".format(server["ServerRanking"] or "<None>")

        # Add state
        if server["DeveloperData"]["MatchState"] == "1":
            message += " - State: Prematch"
        elif server["DeveloperData"]["MatchState"] == "2" or (server["DeveloperData"]["bTournament"] == "true" and server["DeveloperData"]["MatchState"] == "0"):
            message += " - State: In Progress"
        elif server["DeveloperData"]["MatchState"] == "2" or (server["MatchCompletionPercent"] >= 100 and server["DeveloperData"]["MatchState"] == "0"):
            message += " - State: Postmatch"

        # Add private state
        if not server["IsMatchmakingVisible"]:
            message += " - Private"

        # Add password state
        if server["DeveloperData"]["PasswordHash"] != "":
            message += " - Password Protected"

        self._xmpp.send_message(cmdtype, target, message)

plugin = InfoPlugin
