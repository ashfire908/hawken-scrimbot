# -*- coding: utf-8 -*-

import itertools
from scrimbot.plugins.base import BasePlugin, CommandType


class InfoPlugin(BasePlugin):
    @property
    def name(self):
        return "info"

    def enable(self):
        # Register commands
        self.register_command(CommandType.PM, "botinfo", self.botinfo, flags=["safe"])
        self.register_command(CommandType.PM, "foundabug", self.foundabug, flags=["safe"])
        self.register_command(CommandType.ALL, "commands", self.commands)
        self.register_command(CommandType.ALL, "plugins", self.plugin_list, flags=["safe"])

    def disable(self):
        # Unregister commands
        self.unregister_command(CommandType.PM, "botinfo")
        self.unregister_command(CommandType.PM, "foundabug")
        self.unregister_command(CommandType.ALL, "commands")
        self.unregister_command(CommandType.ALL, "plugins")

    def connected(self):
        pass

    def disconnected(self):
        pass

    def botinfo(self, cmdtype, cmdname, args, target, user, room):
        message = """Hello, I am ScrimBot, the Hawken Scrim Bot. I do various competitive-related and utility functions. I am run by Ashfire908.

If you need help with the bot, send a pm to Ashfire908 on the Hawken forums, talk to him on the #hawkenscrim IRC channel, or send an email to: scrimbot@hawkenwiki.com

This bot is an unofficial tool, neither run nor endorsed by Adhesive Games or Meteor Entertainment."""

        self.xmpp.send_message(cmdtype, target, message)

    def foundabug(self, cmdtype, cmdname, args, target, user, room):
        message = """If you have encounter an error with the bot, please send in an error report. Either send a pm to Ashfire908 on the Hawken forums, talk to him on the #hawkenscrim IRC channel, or send an email to: scrimbot@hawkenwiki.com

The error report should contain your callsign, what you were doing, the command you were using, what time is was (including timezone), and the error you recieved.

Not every bit of information is required, but at the very least you need to send in your callsign and the approximate time the error occured; Otherwise the error can't be found."""

        self.xmpp.send_message(cmdtype, target, message)

    def commands(self, cmdtype, cmdname, args, target, user, room):
        if len(args) > 0:
            plugin = args[0].lower()
            if plugin in self.client.plugins.keys():
                targets = self.client.plugins[plugin].registered_commands.values()
            else:
                self.xmpp.send_message(cmdtype, target, "Error: No such plugin.")
                return
        else:
            targets = itertools.chain(*self.client.commands.values())

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
            if handler.flags.b.permsreq and not self.permissions.user_check_groups(user, handler.metadata["permsreq"]):
                    continue
            # Filter out aliases
            if handler.flags.b.alias:
                continue

            # Add it to the display list
            handler_list.add(handler)

        # Display the list
        commands = [self.config.bot.command_prefix + x.cmdname for x in handler_list]
        self.xmpp.send_message(cmdtype, target, "Available commands: {0}".format(" ".join(sorted(commands))))

    def plugin_list(self, cmdtype, cmdname, args, target, user, room):
        self.xmpp.send_message(cmdtype, target, "Loaded plugins: {0}".format(", ".join(self.client.plugins.keys())))


plugin = InfoPlugin
