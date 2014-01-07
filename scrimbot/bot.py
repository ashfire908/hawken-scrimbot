# -*- coding: utf-8 -*-
# Hawken Scrim Bot

import logging
import time
import sleekxmpp
from sleekxmpp.xmlstream.scheduler import Scheduler

from scrimbot.api import ApiClient
from scrimbot.cache import Cache
from scrimbot.command import CommandManager, CommandType
from scrimbot.config import Config
from scrimbot.party import Party
from scrimbot.permissions import PermissionHandler
from scrimbot.plugins.base import PluginManager
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
        return [jid for jid in self.client_roster if jid_user(jid) != self.boundjid.user]

    def format_jid(self, user):
        return "{0}@{1}".format(user, self.boundjid.host)

    def has_jid(self, jid):
        return jid in self.roster_list() and self.client_roster[jid]["subscription"] != "none"

    def add_jid(self, jid):
        added = True

        # Check if the bot the user in the roster
        if not jid in self.client_roster:
            # Subscribe to the user
            self.client_roster[jid].subscribe()
        elif not self.client_roster[jid]["subscription"] in ("both", "from"):
            # Subscribe to the user
            self.client_roster[jid].subscribe()
        else:
            # We didn't add anything
            added = False

        return self.update_jid(jid) or added

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

        return updated


# Main Bot
class ScrimBot:
    def __init__(self, config_filename="config.json"):
        # Init bot data
        self.active_parties = {}
        self.scheduler = Scheduler()

        # Init the config
        self.config = Config(config_filename)

        # Register core config
        self.config.register("bot.offline", False)
        self.config.register("bot.roster_update_rate", 0.05)

        # Load config
        config_loaded = self.config.load()
        if config_loaded is False:
            raise RuntimeError("Failed to load config.")

        # Init the API, cache, XMPP, permissions, plugins, and commands
        self.api = ApiClient(self.config)
        self.cache = Cache(self, self.config, self.api)
        self.xmpp = ScrimBotClient(self.cache)
        self.permissions = PermissionHandler(self.config, self.xmpp)
        self.plugins = PluginManager(self)
        self.commands = CommandManager(self.config, self.xmpp, self.permissions, self.plugins)

        # Load plugins
        for plugin in self.config.bot.plugins:
            self.plugins.load(plugin)

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
        self.xmpp.add_event_handler("message", self.handle_chat_message, threaded=True)
        self.xmpp.add_event_handler("groupchat_message", self.handle_groupchat_message, threaded=True)

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
                # Remove user from the list so we don't try to add them later
                whitelist.remove(user)

                # Add/update the user to the roster
                if not self.xmpp.add_jid(jid):
                    # No changes were made, do not delay
                    continue
            elif self.config.bot.offline or self.xmpp.client_roster[jid]["subscription"] == "none":
                # Remove the user from the roster
                self.xmpp.remove_jid(jid)
            # Make sure the jid is up to date
            elif not self.xmpp.update_jid(jid):
                # No update was made, do not delay
                continue

            # Add a delay between removals so we don't spam the server
            time.sleep(self.config.bot.roster_update_rate)

        # Add any whitelisted users we didn't see
        for user in whitelist:
            self.xmpp.add_jid(self.xmpp.format_jid(user))

            # Add a delay between removals so we don't spam the server
            time.sleep(self.config.bot.roster_update_rate)

    def handle_session_start(self, event):
        # Signal the plugins that we are connected
        self.plugins.connected()

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
        self.plugins.disconnected()

    def handle_killed(self, event):
        logger.info("Bot shutting down.")

        # Unload the plugins
        for plugin in list(self.plugins.active):
            self.plugins.unload(plugin)

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

    def handle_chat_message(self, message):
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
                self.commands.handle_command_message(CommandType.PM, body, message)

    def handle_groupchat_message(self, message):
        if message["type"] == "groupchat":
            # Refuse to process chat from the bot itself
            if message["from"].resource == Party.get_callsign(self.xmpp, message["from"].bare):
                pass
            # Check if the user is blacklisted
            elif message["stormid"].id is not None and self.permissions.user_check_group(message["stormid"].id, "blacklist"):
                pass
            # Check if this is a command
            elif message["body"].startswith(self.config.bot.command_prefix):
                body = message["body"][len(self.config.bot.command_prefix):]

                # Pass it off to the command handler
                self.commands.handle_command_message(CommandType.PARTY, body, message)
