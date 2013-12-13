# -*- coding: utf-8 -*-
# Hawken Scrim Bot

import importlib
import logging
import shlex
import traceback
import sleekxmpp
import hawkenapi.client
import hawkenapi.exceptions
import hawkenapi.sleekxmpp
from scrimbot.api import ApiClient
from scrimbot.cache import Cache
from scrimbot.config import Config
from scrimbot.party import Party
from scrimbot.permissions import PermissionHandler
from scrimbot.plugins.base import CommandType, Command

# Setup logging
logger = logging.getLogger(__name__)


# XMPP Client
class ScrimBotClient(sleekxmpp.ClientXMPP):
    def __init__(self):
        pass

    def setup(self, api, **kwargs):
        # Get the XMPP servers
        server = api.wrapper(api.presence_domain, api.guid)
        self.party_server = "party.{}".format(server)

        # Get the login info
        jid = "{}@{}/HawkenScrimBot".format(api.guid, server)
        auth = api.wrapper(api.presence_access, api.guid)

        # Init the client
        super().__init__(jid, auth, **kwargs)

        # Register the plugins that we will need
        self.register_plugin("xep_0030")  # Service Discovery
        self.register_plugin("xep_0045")  # Multi-User Chat
        self.register_plugin("xep_0199")  # XMPP Ping
        self.register_plugin("hawken_party")  # Hawken Party

    def send_message(self, mtype, mto, mbody):
        # Override the send_message function to support PMs and parties
        if mtype == CommandType.PM:
            super().send_message(mto=mto, mbody=mbody, mtype="chat")
        elif mtype == CommandType.PARTY:
            self.plugin["hawken_party"].message(mto, self.boundjid, mbody)
        else:
            raise NotImplementedError("Unsupported message type.")


# Main Bot
class ScrimBot:
    def __init__(self, config_filename="config.json"):
        # Init plugin/command data
        self.plugins = {}
        self.commands = {}

        # Init the config
        self.config = Config(config_filename)

        # Load config
        config_loaded = self.config.load()
        if config_loaded is False:
            raise RuntimeError("Failed to load config.")

        # Init the API client, XMPP client, permissions, and cache
        self.api = ApiClient(self.config)
        self.xmpp = ScrimBotClient()
        self.permissions = PermissionHandler(self.xmpp, self.config)
        self.cache = Cache(self.config, self.api)

        # Load plugins
        for plugin in self.config.bot.plugins:
            self.load_plugin(plugin)

        # Load the cache
        if self.cache.load() is None:
            # Save new cache file
            self.cache.save()

        # Save the config before we setup the bot
        if not self.config.save():
            raise RuntimeError("Could not save config file.")

        # Setup the API, XMPP and cache
        self.api.setup()
        self.xmpp.setup(self.api)
        self.cache.setup()

        # Register event handlers
        self.xmpp.add_event_handler("session_start", self.handle_session_start)
        self.xmpp.add_event_handler("message", self.handle_message, threaded=True)
        self.xmpp.add_event_handler("groupchat_message", self.handle_groupchat_message, threaded=True)

    def load_plugin(self, name):
        # Load the module
        target = "scrimbot.plugins.{0}".format(name)
        try:
            module = importlib.import_module(target)
        except ImportError:
            logger.info("Failed to load plugin: {0}\n{1}".format(name, traceback.format_exc()))
            return False
        else:
            # Init the plugin
            plugin = module.plugin(self, self.xmpp, self.config, self.cache, self.permissions, self.api)
            self.plugins[plugin.name] = plugin
            self.plugins[plugin.name].enable()

            logger.info("Loaded plugin: {0}".format(plugin.name))

            return True

    def unload_plugin(self, name):
        if not name in self.plugins.keys():
            return False

        # Disable plugin and remove
        self.plugins[name].disable()
        del self.plugins[name]

        logger.info("Unloaded plugin: {0}".format(name))

        return True

    def register_command(self, handler):
        # Add the handler for the command
        if handler.id not in self.commands:
            self.commands[handler.id] = [handler]
        else:
            # Check if the handler isn't already registered
            for registered_handler in self.commands[handler.id]:
                if registered_handler.fullid == handler.fullid:
                    raise ValueError("Handler {0} is already registered".format(handler.fullid))

            self.commands[handler.id].append(handler)

    def unregister_command(self, handler_id, full_id):
        # Remove the command from the registered commands list
        self.commands[handler_id][:] = [handler for handler in self.commands[handler_id] if handler.fullid == full_id]

        # Cleanup the list if it's empty
        if len(self.commands[handler_id]) == 0:
            del self.commands[handler_id]

    def connect(self, *args, **kwargs):
        return self.xmpp.connect(*args, **kwargs)

    def process(self, *args, **kwargs):
        return self.xmpp.process(*args, **kwargs)

    def disconnect(self, *args, **kwargs):
        return self.xmpp.disconnect(*args, **kwargs)

    def shutdown(self):
        logging.info("Shutting down.")
        self.config.save()
        self.cache.save()
        self.disconnect(wait=True)

    def handle_session_start(self, event):
        # Signal the plugins that we are connected
        for plugin in self.plugins.values():
            plugin.connected()

        # Check for offline mode
        if self.config.bot.offline:
            logger.warning("Offline mode enabled.")
            self.xmpp.auto_authorize = False
            self.xmpp.auto_subscribe = False

        # Send presence info, retrieve roster
        self.xmpp.send_presence()
        self.xmpp.get_roster()

        # Update the whitelist
        self.permissions.update_whitelist()

        # CROWBAR IS READY
        logger.info("Bot connected and ready.")

    def handle_session_stop(self, event):
        # Signal the plugins that we are not connected anymore
        for plugin in self.plugins.values():
            plugin.disconnected()

    def handle_message(self, message):
        # Check if the user is allowed to send messages to the bot
        if (self.config.bot.offline and not self.permissions.user_check_groups(message["from"].user, ("admin", "whitelist"))) or \
           self.permissions.user_check_group(message["from"].user, "blacklist"):
            # Ignore it
            pass
        elif message["type"] == "chat":
            # Drop messages from people not friends with
            if not self.permissions.has_user(message["from"].user):
                pass
            # Refuse to process chat from the bot itself
            elif message["from"].user == self.xmpp.boundjid.user:
                pass
            # Pass off the message to the command handler
            else:
                # Strip off the command prefix, if one is set
                if message["body"].startswith(self.config.bot.command_prefix):
                    body = message["body"][len(self.config.bot.command_prefix):]
                else:
                    body = message["body"]
                self.handle_command(CommandType.PM, body, message)

    def handle_groupchat_message(self, message):
        if message["type"] == "groupchat":
            # Refuse to process chat from the bot itself
            if message["from"].resource == Party.our_callsign(self.xmpp, message["from"].bare):
                pass
            # Check if this is a command
            elif message["body"].startswith(self.config.bot.command_prefix):
                body = message["body"][len(self.config.bot.command_prefix):]

                # Pass it off to the command handler
                self.handle_command(CommandType.PARTY, body, message)

    def handle_command(self, cmdtype, body, message):
        # Get the parameters for the message
        target = message["from"].bare
        if cmdtype == CommandType.PM:
            user = message["from"].user
            room = None
        elif cmdtype == CommandType.PARTY:
            user = message["stormid"].id
            room = message["from"].user
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
            self.handle_command_none_given(cmdtype, target, user)
        # Check if the first argument is a plugin, (matches a plugin and has a argument for a command)
        elif arguments[0].lower() in self.plugins and len(arguments) > 1:
            plugin = arguments[0].lower()
            command = arguments[1].lower()

            # Get command ids
            cmdid = Command.format_id(cmdtype, command)
            cmdid_all = Command.format_id(CommandType.ALL, command)

            # Check for the command (same type)
            if cmdid in self.plugins[plugin].registered_commands:
                self.handle_command_wrapper(self.plugins[plugin].registered_commands[cmdid], cmdtype, command, arguments[2:], target, user, room)
            # Check for the command (all type)
            elif cmdid_all in self.plugins[plugin].registered_commands:
                self.handle_command_wrapper(self.plugins[plugin].registered_commands[cmdid_all], cmdtype, command, arguments[2:], target, user, room)
            else:
                # Check for the commmand (by name)
                for registered_command in self.plugins[plugin].registered_commands.values():
                    if registered_command.cmdname == command:
                        self.handle_command_wrong_usage(cmdtype, command, registered_command.cmdtype, target, user)
                        return

                # No such command
                self.handle_command_plugin_no_match(cmdtype, plugin, command, target, user)
        else:
            # Handle command without specified plugin
            command = arguments[0].lower()

            # Get command ids
            cmdid = Command.format_id(cmdtype, command)
            cmdid_all = Command.format_id(CommandType.ALL, command)

            # Check for mixed same type and all type handlers
            if cmdid in self.commands and cmdid_all in self.commands:
                self.handle_command_ambiguous(cmdtype, command, target, user)
            # Check for the command (same type)
            elif cmdid in self.commands:
                if len(self.commands[cmdid]) > 1:
                    self.handle_command_ambiguous(cmdtype, command, target, user)
                else:
                    self.handle_command_wrapper(self.commands[cmdid][0], cmdtype, command, arguments[1:], target, user, room)
            # Check for the command (all type)
            elif cmdid_all in self.commands:
                if len(self.commands[cmdid_all]) > 1:
                    self.handle_command_ambiguous(cmdtype, command, target, user)
                else:
                    self.handle_command_wrapper(self.commands[cmdid_all][0], cmdtype, command, arguments[1:], target, user, room)
            else:
                # Check for the commmand (by name)
                types = set()
                for registered_commands in self.commands.values():
                    if registered_commands[0].cmdname == command:
                        for registered_command in registered_commands:
                            types.add(registered_command.cmdtype)

                if len(types) > 0:
                    # Wrong message type
                    self.handle_command_wrong_usage(cmdtype, command, types, target, user)
                else:
                    # No such command
                    self.handle_command_no_match(cmdtype, command, target, user)

    def handle_command_none_given(self, cmdtype, target, user):
        self.xmpp.send_message(cmdtype, target, "Error: No command given. See {0}commands for a list of commands.".format(self.config.bot.command_prefix))

    def handle_command_no_match(self, cmdtype, command, target, user):
        self.xmpp.send_message(cmdtype, target, "Error: No such command. See {0}commands for a list of commands.".format(self.config.bot.command_prefix))

        if user is None:
            logger.warn("Unknown command {0} called by unidentified user via {1} - target was {2}.".format(command, cmdtype, target))
        else:
            logger.info("Unknown command {0} called by {2} via {1}.".format(command, cmdtype, user))

    def handle_command_ambiguous(self, cmdtype, command, target, user):
        plugins = []
        for handlers in self.commands.values():
            for handler in handlers:
                if handler.cmdname == command:
                    plugins.append(handler.plugin.name)
        self.xmpp.send_message(cmdtype, target, "Error: Command '{0}' available in multiple plugins: {1}".format(command, ", ".join(plugins)))

        if user is None:
            logger.info("Ambiguous command {0} called by unidentified user via {1} - target was {2}.".format(command, cmdtype, target))
        else:
            logger.info("Ambiguous command {0} called by {2} via {1}.".format(command, cmdtype, user))

    def handle_command_wrong_usage(self, cmdtype, command, requiredtype, target, user):
        if isinstance(requiredtype, str):
            requiredtype = [requiredtype]

        # Format the output
        identifier = ""
        count = 0
        for reqtype in requiredtype:
            if count > 0:
                identifier += " or "

            if reqtype == CommandType.PM:
                identifier += "a pm"
            elif reqtype == CommandType.PARTY:
                identifier += "a party"
            else:
                identifier += "<unknown>"

            count += 1

        self.xmpp.send_message(cmdtype, target, "This command can only be run from {0}.".format(identifier))
        if user is None:
            logger.info("Unknown command {0} called by unidentified user via {1} - target was {2}.".format(command, cmdtype, target))
        else:
            logger.info("Unknown command {0} called by {2} via {1}.".format(command, cmdtype, user))

    def handle_command_plugin_no_match(self, cmdtype, plugin, command, target, user):
        self.xmpp.send_message(cmdtype, target, "Error: No such command in plugin {0}. See {1}commands for a list of commands.".format(plugin, self.config.bot.command_prefix))

        if user is None:
            logger.warn("Unknown command {0} for plugin {1} called by unidentified user via {2} - target was {3}.".format(command, plugin, cmdtype, target))
        else:
            logger.info("Unknown command {0} for plugin {1} called by {3} via {2}.".format(command, plugin, cmdtype, user))

    def handle_command_wrapper(self, handler, cmdtype, cmdname, arguments, target, user, room):
        # Check if command is marked 'safe'
        if handler.flags.b.safe:
            assert not handler.flags.b.permsreq
            # Command is safe, bypass checks
            dochecks = False
        else:
            dochecks = True

        if dochecks:
            if user is None:
                # Can't identify user!
                logger.warn("Command {0} called by unidentified user via {1} - target was {2}. Rejecting!".format(cmdname, cmdtype, target))
                self.xmpp.send_message(cmdtype, target, "Error: Failed to identify the user calling the command. Please report your callsign and the command you were using (see {0}foundabug). This error has been logged.".format(self.config.bot.command_prefix))
                return

            # Check if command is marked as requiring perms
            if handler.flags.b.permsreq:
                # Check if the user has the required perms
                if not self.permissions.user_check_groups(user, handler.metadata["permsreq"]):
                    logger.info("Command {0} called by {1} - lacking required permissions [{2}]. Rejecting!".format(cmdname, user, ", ".join(handler.metadata["permsreq"])))
                    self.xmpp.send_message(cmdtype, target, "Error: You are not authorized to access this command.")
                    return

        # Log command usage
        logger.info("Command {0} called by {2} via {1}.".format(cmdname, cmdtype, user))

        try:
            handler.call(cmdtype, cmdname, arguments, target, user, room)
        except Exception as e:
            # Generate the trackback
            exception = traceback.format_exc()

            # Log the error
            logger.error("""Command {0} (called via {1}) has failed due to an exception: {2} {3}
Handler: {4} Arguments: {5} Target: {6} User: {7} Room: {8}
{9}""".format(cmdname, cmdtype, type(e), e, handler.id, arguments, target, user, room, exception))

            # Report back to the user
            if isinstance(e, hawkenapi.exceptions.RetryLimitExceeded):
                # Temp error encountered, retry limit reached
                msg = "Error: The command you attempted to run has failed due to a temporary issue with the Hawken servers. Please try again later. If the error persists, please report it (see {0}foundabug)!".format(self.config.bot.command_prefix)
            elif isinstance(e, (hawkenapi.exceptions.AuthenticationFailure, hawkenapi.exceptions.NotAuthenticated, hawkenapi.exceptions.NotAuthorized)):
                # Auth error encountered
                msg = "Error: The command you attempted to run has failed due to a authentication failure. If the error persists, please report it (see {0}foundabug)!".format(self.config.bot.command_prefix)
            elif isinstance(e, (hawkenapi.exceptions.NotAllowed, hawkenapi.exceptions.WrongOwner, hawkenapi.exceptions.InvalidRequest, hawkenapi.exceptions.InvalidBatch)):
                # Bad request, probably a bug
                msg = "Error: The command you attempted to run has failed due to an issue between the bot and the Hawken servers. This is most likely a bug! Please report it! See {0}foundabug for more information.".format(self.config.bot.command_prefix)
            else:
                msg = "Error: The command you attempted to run has encountered an unhandled exception, please report it (see {1}foundabug). {0} This error has been logged.".format(type(e), self.config.bot.command_prefix)
            self.xmpp.send_message(cmdtype, target, msg)
