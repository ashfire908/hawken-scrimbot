# -*- coding: utf-8 -*-

import shlex
import logging
import hawkenapi.exceptions
from scrimbot.util import enum, create_bitfield

CommandType = enum(ALL="all", PM="pm", PARTY="muc")
CommandFlags = create_bitfield("hidden", "safe", "permsreq", "alias", "partyfeat")

logger = logging.getLogger(__name__)


class CommandManager:
    def __init__(self, config, xmpp, permissions, parties, plugins):
        self.config = config
        self.xmpp = xmpp
        self.permissions = permissions
        self.parties = parties
        self.plugins = plugins

        self.registered = {}

    def _log_unknown_command(self, cmdtype, command, target, user, plugin=None):
        if plugin:
            if user is None:
                logger.warn("Unknown command {1} {0} called by unidentified user via {2} - target was {3}.".format(command, plugin, cmdtype, target))
            else:
                logger.info("Unknown command {1} {0} called by {3} via {2}.".format(command, plugin, cmdtype, user))
        else:
            if user is None:
                logger.warn("Unknown command {0} called by unidentified user via {1} - target was {2}.".format(command, cmdtype, target))
            else:
                logger.info("Unknown command {0} called by {2} via {1}.".format(command, cmdtype, user))

    def _handle_none_given(self, cmdtype, target):
        self.xmpp.send_message(cmdtype, target, "Error: No command given. See {0}commands for a list of commands.".format(self.config.bot.command_prefix))

    def _handle_no_match(self, cmdtype, command, target, user, plugin=None):
        if plugin:
            self.xmpp.send_message(cmdtype, target, "Error: No such command in plugin {0}. See {1}commands for a list of commands.".format(plugin, self.config.bot.command_prefix))
        else:
            self.xmpp.send_message(cmdtype, target, "Error: No such command. See {0}commands for a list of commands.".format(self.config.bot.command_prefix))

        self._log_unknown_command(cmdtype, command, target, user, plugin)

    def _handle_wrong_usage(self, cmdtype, command, target, user, types, plugin=None):
        # Format the output
        identifier = ""
        count = 0
        for rtype in types:
            if count > 0:
                identifier += " or "

            if rtype == CommandType.PM:
                identifier += "a pm"
            elif rtype == CommandType.PARTY:
                identifier += "a party"
            else:
                identifier += "<unknown>"

            count += 1

        self.xmpp.send_message(cmdtype, target, "This command can only be run from {0}.".format(identifier))
        self._log_unknown_command(cmdtype, command, target, user, plugin)

    def _handle_ambiguous(self, cmdtype, command, target, user, plugins):
        self.xmpp.send_message(cmdtype, target, "Error: Command '{0}' available in multiple plugins: {1}".format(command, ", ".join(plugins)))

        if user is None:
            logger.warn("Ambiguous command {0} called by unidentified user via {1} - target was {2}.".format(command, cmdtype, target))
        else:
            logger.info("Ambiguous command {0} called by {2} via {1}.".format(command, cmdtype, user))

    def register(self, handler):
        # Register handler
        if handler.id not in self.registered:
            # Add the handler for the command
            self.registered[handler.id] = [handler]
        else:
            # Check if the handler isn't already registered
            for registered_handler in self.registered[handler.id]:
                if registered_handler.plugin.name == handler.plugin.name:
                    raise ValueError("Handler {0} is already registered by {1}".format(handler.id, registered_handler.fullid))

            # Add the handler for the command
            self.registered[handler.id].append(handler)

        logger.debug("Registered command: {0}".format(handler.fullid))

        # Register aliases
        if handler.flags.b.alias:
            for alias in handler.flags.data.alias:
                cmdid = Command.format_id(handler.cmdtype, alias)
                if cmdid not in self.registered:
                    # Add the handler for the command
                    self.registered[cmdid] = [handler]
                else:
                    # Check if the handler isn't already registered
                    for registered_handler in self.registered[cmdid]:
                        if registered_handler.plugin.name == handler.plugin.name:
                            raise ValueError("Handler {0} is already registered by {1}".format(cmdid, registered_handler.fullid))

                    # Add the handler for the command
                    self.registered[cmdid].append(handler)

                logger.debug("Registered alias: {0} by {1}".format(cmdid, handler.fullid))

    def unregister(self, handler):
        try:
            # Remove the command from the registered commands list
            self.registered[handler.id][:] = [cmdhandler for cmdhandler in self.registered[handler.id] if cmdhandler.fullid != handler.fullid]

            # Cleanup the list if it's empty
            if len(self.registered[handler.id]) == 0:
                del self.registered[handler.id]

            logger.debug("Unregistered command: {0}".format(handler.fullid))
        except KeyError:
            pass

        # Unregister aliases
        if handler.flags.b.alias:
            for alias in handler.flags.data.alias:
                cmdid = Command.format_id(handler.cmdtype, alias)

                try:
                    # Remove the command from the registered commands list
                    self.registered[cmdid][:] = [cmdhandler for cmdhandler in self.registered[cmdid] if cmdhandler.fullid != handler.fullid]

                    # Cleanup the list if it's empty
                    if len(self.registered[cmdid]) == 0:
                        del self.registered[cmdid]

                    logger.debug("Unregistered alias: {0} by {1}".format(cmdid, handler.fullid))
                except KeyError:
                    pass

    def get_handlers(self, cmdtype, cmdname, plugin=None):
        cmdid = Command.format_id(cmdtype, cmdname)

        if not plugin:
            try:
                return self.registered[cmdid]
            except KeyError:
                return []
        else:
            try:
                return [self.plugins.active[plugin].registered["commands"][cmdid]]
            except KeyError:
                return []

    def handle_command_message(self, cmdtype, body, message):
        # Get the parameters for the message
        target = message["from"].bare
        if cmdtype == CommandType.PM:
            user = message["from"].user
            party = None
        elif cmdtype == CommandType.PARTY:
            user = message["stormid"]
            if message["from"].user in self.parties.active:
                party = self.parties.active[message["from"].user]
            else:
                # Can't identify party!
                logger.warn("Command called by {0} from unknown party - room was {1}. Rejecting!".format(user, message["from"].user))
                self.xmpp.send_message(cmdtype, target, "Error: Could not find party data. This is a bug, please report it (see {0}foundabug)!".format(self.config.bot.command_prefix))
                return
        else:
            # O_o
            raise NotImplementedError("Unsupported message type.")

        # Split the arguments
        try:
            arguments = shlex.split(body)
        except ValueError:
            self.xmpp.send_message(cmdtype, target, "Error: Invalid command given. Please check your syntax.")
            logger.info("Bad command line given by {2} via {1}: {0}".format(body, cmdtype, user))
            return

        # Verify we have at least one argument
        if len(arguments) < 1:
            # No command given
            self._handle_none_given(cmdtype, target)
            return
        # Check if the first argument is a plugin, (matches a plugin and has a argument for a command)
        elif arguments[0].lower() in self.plugins.active and len(arguments) > 1:
            plugin = arguments[0].lower()
            command = arguments[1].lower()
            arguments = arguments[2:]
        else:
            plugin = None
            command = arguments[0].lower()
            arguments = arguments[1:]

        # Get potential commands
        potential_commands = []
        potential_commands.extend(self.get_handlers(cmdtype, command, plugin))
        potential_commands.extend(self.get_handlers(CommandType.ALL, command, plugin))

        skip_usage = False
        # Only perform command filtering if the plugin wasn't explictly given
        if plugin is None and len(potential_commands) > 0:
            # Filter commands that can't run in this context
            def filter_command(handler):
                # Check if safe command
                if handler.flags.b.safe:
                    return True

                # Check if party features are required
                if handler.flags.b.partyfeat:
                    # Check the party supports the features
                    for feature in handler.flags.data.partyfeat:
                        if feature not in party.features:
                            return False

                return True

            potential_commands[:] = [handler for handler in potential_commands if filter_command(handler)]
            if len(potential_commands) == 0:
                skip_usage = True

        # Check if there are no commands available
        if len(potential_commands) < 1:
            types = set()
            if not skip_usage:
                # Search for command by any type
                for registered_commands in self.registered.values():
                    # We only really need to check the first handler for the name if it matches
                    if registered_commands[0].cmdname == command:
                        # Get the available types supported
                        for registered_command in registered_commands:
                            types.add(registered_command.cmdtype)

            if len(types) > 0:
                # Wrong message type
                self._handle_wrong_usage(cmdtype, command, target, user, types, plugin)
            else:
                # No such command
                self._handle_no_match(cmdtype, command, target, user, plugin)
        # Check if there are multiple commands
        elif len(potential_commands) > 1:
            # Ambiguous command call
            plugins = [handler.plugin.name for handler in potential_commands]
            self._handle_ambiguous(cmdtype, command, target, user, plugins)
        else:
            # Call the matching command
            self.call_command(potential_commands[0], cmdtype, command, arguments, target, user, party)

    def call_command(self, handler, cmdtype, cmdname, arguments, target, user, party):
        # Check if command is marked 'safe'
        if handler.flags.b.safe:
            assert not handler.flags.b.permsreq
            # Command is safe, bypass checks
        else:
            # Perform checks
            # Check if we can identify the user
            if user is None:
                # Can't identify user!
                logger.warn("Command {1} {0} called by unidentified user via {2} - target was {3}. Rejecting!".format(cmdname, handler.plugin.name, cmdtype, target))
                self.xmpp.send_message(cmdtype, target, "Error: Failed to identify the user calling the command. Please report your callsign and the command you were using (see {0}foundabug). This error has been logged.".format(self.config.bot.command_prefix))
                return

            # Check for offline mode
            if self.config.bot.offline and (user is None or not self.permissions.user_check_group(user, "admin")):
                # Bot is offline
                logger.info("Bot offline - rejecting command {1} {0} called by {2}.".format(cmdname, handler.plugin.name, user))
                self.xmpp.send_message(cmdtype, target, "The bot is currently in offline mode and is not accepting commands at this time. Please try again later.")
                return

            # Check if command is marked as requiring perms
            if handler.flags.b.permsreq:
                # Check if the user has the required perms
                if not self.permissions.user_check_groups(user, handler.flags.data.permsreq):
                    logger.info("Command {1} {0} called by {2} - lacking required permissions [{3}]. Rejecting!".format(cmdname, handler.plugin.name, user, ", ".join(handler.flags.data.permsreq)))
                    self.xmpp.send_message(cmdtype, target, "Error: You are not authorized to access this command.")
                    return

            # Check if party features are required
            if handler.flags.b.partyfeat:
                # Check the party supports the features
                for feature in handler.flags.data.partyfeat:
                    if feature not in party.features:
                        logger.info("Command {1} {0} called by {3} via {2} - party {4} does not support required features [{5}]. Rejecting!".format(cmdname, handler.plugin.name, cmdtype, user, party.guid, ", ".join(handler.flags.data.partyfeat)))
                        self.xmpp.send_message(cmdtype, target, "Error: The party does not support the feature(s) required by this command.")
                        return

        # Log command usage
        logger.info("Command {1} {0} called by {3} via {2}.".format(cmdname, handler.plugin.name, cmdtype, user))

        try:
            handler.call(cmdtype, cmdname, arguments, target, user, party)
        except Exception as e:
            if party is None:
                party_name = None
            else:
                party_name = party.guid

            # Log the error
            logger.exception("""Command {1} {0} (called via {2}) has failed due to an exception: {3} {4}
Handler: {5} Arguments: {6} Target: {7} User: {8} Party: {9}""".format(cmdname, handler.plugin.name, cmdtype, type(e), e, handler.fullid, arguments, target, user, party_name))

            # Report back to the user
            try:
                if isinstance(e, hawkenapi.exceptions.RetryLimitExceeded):
                    # Try using the subexception's message
                    msg = self.exception_message(e.last_exception)
                    if msg is None:
                        # Temp error encountered, retry limit reached
                        msg = "Error: The command you attempted to run has failed due to a temporary issue with the Hawken servers. Please try again later. If the error persists, please report it (see {0}foundabug)!".format(self.config.bot.command_prefix)
                else:
                        # Get the exception message
                    msg = self.exception_message(e)
                    if msg is None:
                        # Generic error
                        msg = "Error: The command you attempted to run has encountered an unhandled exception. This is a bug, please report it (see {1}foundabug)! {0} This error has been logged.".format(type(e), self.config.bot.command_prefix)
            except:
                logger.exception("Exception encountered while formatting error message to user.")
                msg = "Error: The command you attempted to run has encountered an unhandled exception. This is a bug. Such a bug, that even the proper error message cannot be displayed! Please report it! This error has been logged."

            self.xmpp.send_message(cmdtype, target, msg)

    def exception_message(self, exception):
        if isinstance(exception, (hawkenapi.exceptions.AuthenticationFailure, hawkenapi.exceptions.NotAuthenticated, hawkenapi.exceptions.NotAuthorized)):
            # Auth error encountered
            message = "Error: The command you attempted to run has failed due to a authentication failure. If the error persists, please report it (see {0}foundabug)!".format(self.config.bot.command_prefix)
        elif isinstance(exception, (hawkenapi.exceptions.NotAllowed, hawkenapi.exceptions.WrongUser, hawkenapi.exceptions.InvalidRequest, hawkenapi.exceptions.InvalidBatch)):
            # Bad request, probably a bug
            message = "Error: The command you attempted to run has failed due to an issue between the bot and the Hawken servers. This is a bug, please report it! See {0}foundabug for more information.".format(self.config.bot.command_prefix)
        elif isinstance(exception, (hawkenapi.exceptions.InternalServerError, hawkenapi.exceptions.RequestError)):
            # Request error
            message = "Error: The command you attempted to run has failed due to an issue encountered with the Hawken servers. If the error persists, please report it (see {0}foundabug)!".format(self.config.bot.command_prefix)
        elif isinstance(exception, hawkenapi.exceptions.ServiceUnavailable):
            # Service failure
            message = "Error: The command you attempted to run has failed due to the Hawken servers being unavailable. Please try again later. If the error persists, please report it (see {0}foundabug)!".format(self.config.bot.command_prefix)
        else:
            # Unknown
            message = None

        return message


class Command:
    def __init__(self, plugin, cmdtype, cmdname, handler, **flags):
        self.plugin = plugin
        self.cmdtype = cmdtype
        self.cmdname = cmdname
        self.id = Command.format_id(cmdtype, cmdname)
        self.fullid = Command.format_fullid(plugin.name, cmdtype, cmdname)
        self.handler = handler

        self.flags = CommandFlags()
        for flag, value in flags.items():
            if value:
                setattr(self.flags.b, flag, 1)
                setattr(self.flags.data, flag, value)

        self._verify_flags()

    def _verify_flags(self):
        # Safe and Permission Required conflict
        if self.flags.b.safe and self.flags.b.permsreq:
            raise ValueError("Flags 'safe' and 'permsreq' cannot be enabled at once")

        # Safe and Permission Required conflict
        if self.flags.b.safe and self.flags.b.partyfeat:
            raise ValueError("Flags 'safe' and 'partyfeat' cannot be enabled at once")

        # Party Feature cannot be used for non-party handlers
        if self.flags.b.partyfeat and self.cmdtype != CommandType.PARTY:
            raise ValueError("Flag 'partyfeat' cannot be enabled for non-party commands")

    def call(self, cmdtype, cmdname, args, target, user, party=None):
        self.handler(cmdtype, cmdname, args, target, user, party)

    @staticmethod
    def format_id(cmdtype, cmdname):
        return "{0}::{1}".format(cmdtype, cmdname.lower())

    @staticmethod
    def format_fullid(plugin, cmdtype, cmdname):
        return "{0}:{1}::{2}".format(plugin, cmdtype, cmdname.lower())

    @staticmethod
    def parse_id(cmdid):
        return cmdid.split("::", 1)

    @staticmethod
    def parse_fullid(fullid):
        plugin, cmdid = fullid.split(":", 1)
        cmdtype, cmdname = Command.parse_id(cmdid)
        return plugin, cmdtype, cmdname
