# -*- coding: utf-8 -*-
# Hawken Scrim Bot

import logging
import time
import shlex
import traceback
import importlib
import sleekxmpp
from sleekxmpp.xmlstream.scheduler import Scheduler

import hawkenapi.client
import hawkenapi.exceptions
import hawkenapi.sleekxmpp

from scrimbot.api import ApiClient
from scrimbot.cache import Cache
from scrimbot.config import Config
from scrimbot.party import Party
from scrimbot.permissions import PermissionHandler
from scrimbot.plugins.base import CommandType, Command
from scrimbot.util import jid_user

logger = logging.getLogger(__name__)


# XMPP Client
class ScrimBotClient(sleekxmpp.ClientXMPP):
    def __init__(self, cache):
        self.cache = cache

    def setup(self, user, server, auth, **kwargs):
        # Init the client
        self.party_server = "party.{}".format(server)
        jid = "{}@{}/HawkenScrimBot".format(user, server)
        super().__init__(jid, auth, sasl_mech="DIGEST-MD5", **kwargs)

        # Disable whitespace keepalives
        self.whitespace_keepalive = False

        # Register the signal handlers
        self.use_signals()

        # Register the plugins that we will need
        self.register_plugin("xep_0030")  # Service Discovery
        self.register_plugin("xep_0045")  # Multi-User Chat
        self.register_plugin("xep_0199")  # XMPP Ping
        self.register_plugin("hawken_party")  # Hawken Party

    def send_message(self, mtype, mto, mbody, now=False):
        # Override the send_message function to support PMs and parties
        if mtype == CommandType.PM:
            message = super().make_message(mto, mbody=mbody, mtype="chat")
            message.send(now)
        elif mtype == CommandType.PARTY:
            self.plugin["hawken_party"].message(mto, self.boundjid, mbody)
        else:
            raise NotImplementedError("Unsupported message type.")

    def roster_list(self):
        return [jid for jid in self.client_roster.keys() if jid_user(jid) != self.boundjid.user]

    def format_jid(self, user):
        return "{0}@{1}".format(user, self.boundjid.host)

    def has_jid(self, jid):
        return jid in self.roster_list() and self.client_roster[jid]["subscription"] != "none"

    def add_jid(self, jid):
        # Check if the bot the user in the roster
        if not jid in self.client_roster.keys():
            # Subscribe to the user
            self.client_roster[jid].subscribe()
        elif not self.client_roster[jid]["subscription"] in ("both", "from"):
            # Subscribe to the user
            self.client_roster[jid].subscribe()
        
        self.update_jid(jid)

    def remove_jid(self, jid):
        self.client_roster[jid].remove()
        self.client_roster.update(jid, subscription="remove", block=False)

    def update_jid(self, jid):
        updated = False

        # Check if the jid has a blank name
        if self.client_roster[jid]["name"] == "":
            # Update the jid with the user's callsign
            user = jid_user(jid)
            callsign = self.cache.get_callsign(user) or ""

            self.client_roster[jid]["name"] = callsign
            updated = True

        # Check if the jid is in the friends group
        if not "Friends" in self.client_roster[jid]["groups"]:
            # Add the jid to the Friends group
            self.client_roster[jid]["groups"].append("Friends")
            updated = True

        # Check if any changes were made
        if updated:
            # Post updates to the server
            iq = self.Iq()
            iq["type"] = "set"
            iq["roster"]["items"] = {jid: {"name": self.client_roster[jid]["name"],
                                           "subscription": self.client_roster[jid]["subscription"],
                                           "groups": self.client_roster[jid]["groups"]}}

            iq.send()


# Main Bot
class ScrimBot:
    def __init__(self, config_filename="config.json"):
        # Init bot data
        self.plugins = {}
        self.commands = {}
        self.active_parties = {}
        self.scheduler = Scheduler()

        # Init the config
        self.config = Config(config_filename)

        # Register core config
        self.config.register_config("bot.offline", False)
        self.config.register_config("bot.roster_update_rate", 0.05)

        # Load config
        config_loaded = self.config.load()
        if config_loaded is False:
            raise RuntimeError("Failed to load config.")

        # Init the API, cache, XMPP, and permissions
        self.api = ApiClient(self.config)
        self.cache = Cache(self, self.config, self.api)
        self.xmpp = ScrimBotClient(self.cache)
        self.permissions = PermissionHandler(self.xmpp, self.config)

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

        # Setup the API and cache
        self.api.setup()
        self.cache.setup()

        # Setup the XMPP client
        self.xmpp.setup(self.api.guid, self.api.wrapper(self.api.presence_domain, self.api.guid),
                        self.api.wrapper(self.api.presence_access, self.api.guid))

        # Attach the scheduler to the xmpp stop event and start processing
        self.scheduler.stop = self.xmpp.stop
        self.scheduler.process()

        # Register event handlers
        self.xmpp.add_event_handler("session_start", self.handle_session_start)
        self.xmpp.add_event_handler("session_end", self.handle_session_end)
        self.xmpp.add_event_handler("killed", self.handle_killed)
        self.xmpp.add_event_handler("roster_subscription_request", self.handle_subscription_request)
        self.xmpp.add_event_handler("roster_subscription_remove", self.handle_subscription_remove)
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
        self.plugins[name].disconnected()
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
        self.commands[handler_id][:] = [handler for handler in self.commands[handler_id] if handler.fullid != full_id]

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
        self.xmpp.abort()

    def update_roster(self):
        logger.info("Updating roster.")

        # Generate the whitelist and blacklist
        whitelist = set(self.permissions.group_users("admin") + self.permissions.group_users("whitelist"))
        blacklist = self.permissions.group_users("blacklist")

        # Update the existing roster entries
        for jid in self.xmpp.roster_list():
            user = jid_user(jid)

            # Check if the user is on the blacklist
            if user in blacklist:
                # Remove the user from the roster
                self.xmpp.remove_jid(jid)
            # Check if the user is on the list
            elif user in whitelist:
                # Add/update the user to the roster
                self.xmpp.add_jid(jid)

                # Remove user so we don't try to add them later
                whitelist.remove(user)
            elif self.config.bot.offline or self.xmpp.client_roster[jid]["subscription"] == "none":
                # Remove the user from the roster
                self.xmpp.remove_jid(jid)
            else:
                # Make sure the jid is up to date
                self.xmpp.update_jid(jid)

            # Add a delay between removals so we don't spam the server
            time.sleep(self.config.bot.roster_update_rate)

        # Add any whitelisted users we didn't see
        for user in whitelist:
            self.xmpp.add_jid(self.xmpp.format_jid(user))

            # Add a delay between removals so we don't spam the server
            time.sleep(self.config.bot.roster_update_rate)

    def handle_session_start(self, event):
        # Signal the plugins that we are connected
        for plugin in self.plugins.values():
            plugin.connected()

        # Handle the presence ourselves
        self.xmpp.auto_authorize = None

        # Send presence info, retrieve roster
        self.xmpp.send_presence()
        self.xmpp.get_roster()

        # Update the roster
        self.update_roster()

        # CROWBAR IS READY
        logger.info("Bot connected and ready.")

    def handle_session_end(self, event):
        logger.info("Bot disconnected.")

        # Signal the plugins that we are not connected anymore
        for plugin in self.plugins.values():
            plugin.disconnected()

    def handle_killed(self, event):
        logger.info("Bot shutting down.")

        # Unload the plugins
        for plugin in list(self.plugins.keys()):
            self.unload_plugin(plugin)

        # Save the config and cache
        self.config.save()
        self.cache.save()

    def handle_subscription_request(self, presence):
        roster_item = self.xmpp.client_roster[presence["from"]]
        user = presence["from"].user

        # Check if we should accept the subscription from the user
        if self.permissions.user_check_group(user, "blacklist") or \
           (self.config.bot.offline and not self.permissions.user_check_groups(user, ("admin", "whitelist"))):
            # Reject the subscription and remove the user
            roster_item.unauthorize()
            self.xmpp.remove_jid(presence["from"].bare)
        else:
            # Accept the subscription and add the jid
            roster_item.authorize()
            self.xmpp.add_jid(presence["from"].bare)

    def handle_subscription_remove(self, presence):
        # Remove the user from the roster
        # This is to save space on the roster as the bot handles a bunch of different users
        self.xmpp.remove_jid(presence["from"].bare)

    def handle_message(self, message):
        # Check if the user is allowed to send messages to the bot
        if self.permissions.user_check_group(message["from"].user, "blacklist") or \
           (self.config.bot.offline and not self.permissions.user_check_groups(message["from"].user, ("admin", "whitelist"))):
            # Ignore it
            pass
        elif message["type"] == "chat":
            # Drop messages from people not friends with
            if not self.xmpp.has_jid(message["from"].bare):
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
            # Check if the user is blacklisted
            elif message["stormid"].id is not None and self.permissions.user_check_group(message["stormid"].id, "blacklist"):
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
            logger.warn("Ambiguous command {0} called by unidentified user via {1} - target was {2}.".format(command, cmdtype, target))
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
            logger.warn("Unknown command {0} called by unidentified user via {1} - target was {2}.".format(command, cmdtype, target))
        else:
            logger.info("Unknown command {0} called by {2} via {1}.".format(command, cmdtype, user))

    def handle_command_plugin_no_match(self, cmdtype, plugin, command, target, user):
        self.xmpp.send_message(cmdtype, target, "Error: No such command in plugin {0}. See {1}commands for a list of commands.".format(plugin, self.config.bot.command_prefix))

        if user is None:
            logger.warn("Unknown command {1} {0} called by unidentified user via {2} - target was {3}.".format(command, plugin, cmdtype, target))
        else:
            logger.info("Unknown command {1} {0} called by {3} via {2}.".format(command, plugin, cmdtype, user))

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
                logger.warn("Command {1} {0} called by unidentified user via {2} - target was {3}. Rejecting!".format(cmdname, handler.plugin.name, cmdtype, target))
                self.xmpp.send_message(cmdtype, target, "Error: Failed to identify the user calling the command. Please report your callsign and the command you were using (see {0}foundabug). This error has been logged.".format(self.config.bot.command_prefix))
                return

            # Check if command is marked as requiring perms
            if handler.flags.b.permsreq:
                # Check if the user has the required perms
                if not self.permissions.user_check_groups(user, handler.metadata["permsreq"]):
                    logger.info("Command {1} {0} called by {2} - lacking required permissions [{3}]. Rejecting!".format(cmdname, handler.plugin.name, user, ", ".join(handler.metadata["permsreq"])))
                    self.xmpp.send_message(cmdtype, target, "Error: You are not authorized to access this command.")
                    return

        # Log command usage
        logger.info("Command {1} {0} called by {3} via {2}.".format(cmdname, handler.plugin.name, cmdtype, user))

        try:
            handler.call(cmdtype, cmdname, arguments, target, user, room)
        except Exception as e:
            # Generate the trackback
            exception = traceback.format_exc()

            # Log the error
            logger.error("""Command {1} {0} (called via {2}) has failed due to an exception: {3} {4}
Handler: {5} Arguments: {6} Target: {7} User: {8} Room: {9}
{10}""".format(cmdname, handler.plugin.name, cmdtype, type(e), e, handler.fullid, arguments, target, user, room, exception))

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
