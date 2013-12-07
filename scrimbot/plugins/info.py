# -*- coding: utf-8 -*-

from scrimbot.plugins.base import BasePlugin, Command, CommandType


class InfoPlugin(BasePlugin):
    def init_plugin(self):
        # Register commands
        self.register_command(Command("botinfo", CommandType.PM, self.botinfo, flags=["safe"]))
        self.register_command(Command("foundabug", CommandType.PM, self.foundabug, flags=["safe"]))
        self.register_command(Command("commands", CommandType.ALL, self.commands))

    def start_plugin(self):
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
        # Build command list
        handler_list = []
        for handler in self.client.commands.values():
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
            handler_list.append(handler)

        # Display the list
        commands = [self.config.bot.command_prefix + x.cmdname for x in handler_list]
        self.xmpp.send_message(cmdtype, target, "Available commands: {0}".format(" ".join(sorted(commands))))


plugin = InfoPlugin
