# -*- coding: utf-8 -*-
# Hawken Scrim Bot

import logging
import time
import sleekxmpp
import sleekxmpp.xmlstream.scheduler

from scrimbot.api import ApiClient
from scrimbot.cache import Cache
from scrimbot.command import CommandManager, CommandType
from scrimbot.config import Config
from scrimbot.party import PartyManager
from scrimbot.permissions import PermissionHandler
from scrimbot.plugins.base import PluginManager
from scrimbot.util import jid_user, default_logging

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

        # Handle the presence ourselves
        self.auto_authorize = None

        # Register the signal handlers
        self.use_signals()

        # Register the plugins that we will need
        self.register_plugin("xep_0030")  # Service Discovery
        self.register_plugin("xep_0045")  # Multi-User Chat
        self.register_plugin("xep_0199")  # XMPP Ping
        self.register_plugin("xep_0203")  # Delay
        self.register_plugin("hawken")  # Hawken
        self.register_plugin("hawken_party")  # Hawken Party

    def send_message(self, mtype, mto, mbody, now=False):
        # Override the send_message function to support PMs and parties
        if mtype == CommandType.PM:
            message = super().make_message(mto, mbody=mbody, mtype="chat")
            message.send(now)
        elif mtype == CommandType.PARTY:
            self.plugin["hawken_party"].message(mto, self.boundjid, mbody)
        else:
            raise NotImplementedError("Unsupported message type")

    def roster_list(self):
        return [jid for jid in self.client_roster if jid_user(jid) != self.boundjid.user]

    def roster_items(self):
        for jid, item in self.client_roster._jids.items():
            if jid_user(jid) != self.boundjid.user:
                yield jid, item

    def format_jid(self, user):
        return "{0}@{1}".format(user, self.boundjid.host)

    def has_jid(self, jid):
        return jid_user(jid) != self.boundjid.user and jid in self.client_roster and self.client_roster[jid]["subscription"] != "none"

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


class Scheduler(sleekxmpp.xmlstream.scheduler.Scheduler):
    def add(self, name, seconds, callback, **kwargs):
        super().add(name, seconds, callback, **kwargs)
        logger.debug("Registered task: {0}".format(name))

    def remove(self, name):
        super().remove(name)
        logger.debug("Unregistered task: {0}".format(name))


# Main Bot
class ScrimBot:
    def __init__(self, config="config.json"):
        # Init bot data
        self.scheduler = Scheduler()
        self.connected = False

        # Init the config
        self.config = Config(config)

        # Register core config
        self.config.register("bot.logging", default_logging())
        self.config.register("bot.plugins", ["admin", "info"])
        self.config.register("bot.command_prefix", "!")
        self.config.register("bot.offline", False)
        self.config.register("bot.whitelisted", False)
        self.config.register("bot.roster_update_rate", 0.05)

        # Load config
        config_loaded = self.config.load()
        if config_loaded is False:
            raise RuntimeError("Failed to load config")

        # Init the API, cache, XMPP, permissions, plugins, and commands
        self.api = ApiClient(self.config)
        self.cache = Cache(self, self.config, self.api)
        self.xmpp = ScrimBotClient(self.cache)
        self.permissions = PermissionHandler(self.config, self.xmpp)
        self.parties = PartyManager(self.config, self.api, self.cache, self.xmpp)
        self.plugins = PluginManager(self)
        self.commands = CommandManager(self.config, self.xmpp, self.permissions, self.parties, self.plugins)

        # Load plugins
        self.config.bot.plugins = list(set(self.config.bot.plugins))
        for plugin in self.config.bot.plugins:
            self.plugins.load(plugin)

        # Load the cache
        if self.cache.load() is None:
            # Save new cache file
            self.cache.save()

        # Save the config before we setup the bot
        if not self.config.save():
            raise RuntimeError("Could not save config file")

        # Setup the API and cache
        self.api.setup()
        self.cache.setup()

        # Setup the XMPP client
        self.xmpp.setup(self.api.guid, self.api.get_presence_domain(), self.api.get_presence_access())

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
        self.xmpp.add_event_handler("game_invite", self.handle_game_invite, threaded=True)

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
            elif self.config.bot.whitelisted or self.xmpp.client_roster[jid]["subscription"] == "none":
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
        if not self.connected:
            self.connected = True

            # Send presence info, retrieve roster
            self.xmpp.send_presence()
            self.xmpp.get_roster()

            # Update the roster
            self.update_roster()

            # Signal the plugins that we are connected
            self.plugins.connected()

            # CROWBAR IS READY
            logger.info("Bot connected.")

    def handle_session_end(self, event):
        if self.connected:
            self.connected = False

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
           (self.config.bot.whitelisted and not self.permissions.user_check_groups(user, ("admin", "whitelist"))):
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
        # Refuse to process chat from the bot itself
        if message["from"].user == self.xmpp.boundjid.user:
            pass
        # Drop messages that were sent while offline
        elif message["delay"]["text"] == "Offline Storage":
            pass
        # Log broadcast messages
        elif message["from"].bare == self.xmpp.boundjid.host:
            if message["subject"]:
                logger.info("Emergency broadcast received: [{0}] {1}".format(message["subject"], message["body"]))
            else:
                logger.info("Emergency broadcast received: {0}".format(message["body"]))
        # Drop messages from people not friends with
        elif not self.xmpp.has_jid(message["from"].bare):
            pass
        # Drop messages from users not allowed to send messages to the bot
        elif self.permissions.user_check_group(message["from"].user, "blacklist") or \
            (self.config.bot.whitelisted and not self.permissions.user_check_groups(message["from"].user, ("admin", "whitelist"))):
            pass
        # Check if this is a normal chat message
        elif message["type"] == "chat":
            # Strip off the command prefix, if one is set
            if message["body"].startswith(self.config.bot.command_prefix):
                body = message["body"][len(self.config.bot.command_prefix):]
            else:
                body = message["body"]

            # Pass off the message to the command handler
            self.commands.handle_command_message(CommandType.PM, body, message)

    def handle_groupchat_message(self, message):
        if message["type"] == "groupchat":
            # Refuse to process chat from the bot itself
            if message["from"].resource == self.parties.get_callsign(message["from"].bare):
                pass
            # Drop messages from blacklisted users
            elif message["stormid"] is not None and self.permissions.user_check_group(message["stormid"], "blacklist"):
                pass
            # Check if this is a command
            elif message["body"].startswith(self.config.bot.command_prefix):
                body = message["body"][len(self.config.bot.command_prefix):]

                # Pass it off to the command handler
                self.commands.handle_command_message(CommandType.PARTY, body, message)

    def handle_game_invite(self, message):
        # Refuse to process chat from the bot itself
        if message["from"].user == self.xmpp.boundjid.user:
            pass
        # Drop messages that were sent while offline
        elif message["delay"]["text"] == "Offline Storage":
            pass
        # Drop messages from people not friends with
        elif not self.xmpp.has_jid(message["from"].bare):
            pass
        # Drop messages from users not allowed to send messages to the bot
        elif self.permissions.user_check_group(message["from"].user, "blacklist") or \
            (self.config.bot.whitelisted and not self.permissions.user_check_groups(message["from"].user, ("admin", "whitelist"))):
            pass
        else:
            logger.info("Ignoring game invite from {0}.".format(message["from"].user))
            self.xmpp.send_message(CommandType.PM, message["from"], "This bot does not accept game invites.")
