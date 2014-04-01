# -*- coding: utf-8 -*-

import random
import time
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

If you need help with the bot, send a pm to Ashfire908 on the Hawken forums, talk to him on the #hawkenscrim IRC channel on QuakeNet, or send an email to: scrimbot@hawkenwiki.com

This bot is an unofficial tool, neither run nor endorsed by Adhesive Games or Meteor Entertainment."""

        self._xmpp.send_message(cmdtype, target, message)

    def foundabug(self, cmdtype, cmdname, args, target, user, party):
        message = "Error: " + random.choice("""clock speed mismatch
solar flares
electromagnetic radiation from satellite debris
static from nylon underwear
static from plastic slide rules
global warming
poor power conditioning
static buildup
doppler effect
hardware stress fractures
magnetic interference from money/credit cards
dry joints on cable plug
waiting for AWS to fix the line
temporary routing anomaly
somebody is calculating pi on the server
fat electrons in the lines
excess surge protection
floating point processor overflow
divide-by-zero error
POSIX compliance problem
monitor resolution too high
improperly oriented keyboard
network packets travelling uphill
Decreasing electron flux
first Saturday after first full moon in Winter
radiosity depletion
CPU radiator broken
positron router malfunction
cellular telephone interference
techtonic stress
piezo-electric interference
dynamic software linking table corrupted
heavy gravity fluctuation, move computer to floor rapidly
not enough memory, please visit http://downloadmoreram.com/
interrupt configuration error
spaghetti cable cause packet failure
boss forgot system password
bank holiday - system operating credits not recharged
waste water tank overflowed onto computer
Complete Transient Lockout
bad ether in the cables
Bogon emissions
Change in Earth's rotational speed
Cosmic ray particles crashed through the hard disk platter
Smell from unhygienic janitorial staff wrecked the tape heads
Little hamster in running wheel had coronary; waiting for replacement to be Fedexed from Wyoming
high pressure system failure
failed trials, system needs redesigned
system has been recalled
not approved by the FCC
not properly grounded, please bury computer
CPU needs recalibration
system needs to be rebooted
bit bucket overflow
descramble code needed from software company
only available on a need to know basis
knot in cables caused data stream to become twisted and kinked
nesting roaches shorted out the ether cable
The file system is full of it""".split("\n"))

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
        callsign = self._cache.get_callsign(user)

        # Check if we got a callsign back
        if callsign is None:
            message = "Error: Failed to look up your callsign."
        else:
            message = "You are '{0}'.".format(callsign)

        self._xmpp.send_message(cmdtype, target, message)

    def hammertime(self, cmdtype, cmdname, args, target, user, party):
        self._xmpp.send_message(cmdtype, target, "STOP!")
        time.sleep(5)
        self._xmpp.send_message(cmdtype, target, "HAMMER TIME!")

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
        message = "Server {0[ServerName]}: {1} on {2} in {3} - Users {4}/{0[MaxUsers]} - Rating {5}".format(server, gametype_names.get(server["GameType"], server["GameType"]), map_names.get(server["Map"], server["Map"]), region_names.get(server["Region"], server["Region"]), len(server["Users"]), server["ServerRanking"] or "<None>")
        message += " - " + random.choice(["Likes long walks on the beach", "Hates the rain", "Spreads rumors behind {0}'s back".format(self._cache.get_callsign(user)), "Busy determining priorities"])
        self._xmpp.send_message(cmdtype, target, message)

plugin = InfoPlugin
