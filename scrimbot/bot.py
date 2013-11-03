# -*- coding: utf-8 -*-
# Hawken Scrim Bot


import logging
import errno
import time
import math
import json
import os.path
import threading
from copy import deepcopy
import sleekxmpp

import hawkenapi.client
import hawkenapi.sleekxmpp
from hawkenapi.exceptions import InvalidBatch

from scrimbot.commands import RequiredPerm, HiddenCommand
from scrimbot.party import Party


# Bot class
class ScrimBot(sleekxmpp.ClientXMPP):
    def __init__(self, username=None, password=None, config_path=None):
        # Init cache, storage, base settings, etc
        self.callsigns = {}
        self.reservations = {}
        self.registered_commands = {}
        self.mmr_usage = {}
        self.parties = {}
        self.party_alias = {}
        self.config_filename = "config.json"
        self.config_path = config_path or "."

        # Default config
        self.advertisement_poll_limit = 30.0
        self.advertisement_poll_rate = 0.5
        self.command_prefix = "!"
        self.perms_init(("admin", "spectator", "mmr", "party"))
        self.bot_offline = False
        self.own_guid = None
        self.own_password = None
        self.mmr_limit = -1
        self.mmr_period = 60 * 60 * 6
        self.mmr_restricted = False
        self.sr_min = 2
        self.globals_period = 60 * 60 * 12
        self.spec_rankrange = 8
        self.party_cleanup_period = 60 * 15

        # Load config
        if not self._config_load() and username is None:
            raise RuntimeError("Failed to load config and no login given.")
        if username is not None and password is not None:
            self.own_guid = username
            self.own_password = password
        elif (username is None and self.own_guid is None) or (password is None and self.own_password is None):
            raise RuntimeError("No login given via arguments or config.")

        # Init API
        self.hawken_api = hawkenapi.client.Client()
        self.hawken_api.auto_auth(self.own_guid, self.own_password)
        self.own_callsign = self.hawken_api.user_callsign(self.own_guid)

        # Init client
        self.xmpp_server = self.hawken_api.presence_domain(self.own_guid)
        self.xmpp_server_party = "party.{}".format(self.xmpp_server)

        # Setup client
        jid = "{}@{}/HawkenScrimBot".format(self.own_guid, self.xmpp_server)
        xmpp_auth = self.hawken_api.presence_access(self.own_guid)
        super(ScrimBot, self).__init__(jid, xmpp_auth)

        # Event handlers
        self.add_event_handler("session_start", self.bot_start)
        self.add_event_handler("message", self.handle_message, threaded=True)
        self.add_event_handler("groupchat_message", self.handle_groupchat_message, threaded=True)

        # Command handlers
        # Meta/Utilities
        self.add_command_handler("pm::botinfo", self.command_botinfo)
        self.add_command_handler("pm::commands", self.command_commands)
        self.add_command_handler("muc::commands", self.command_commands)
        self.add_command_handler("pm::whoami", self.command_whoami)
        self.add_command_handler("muc::whoami", self.command_whoami)
        self.add_command_handler("pm::hammertime", self.command_hammertime)
        # Tests
        self.add_command_handler("pm::testexception", self.command_testexception)
        self.add_command_handler("pm::saveconfig", self.command_save_config)
        self.add_command_handler("pm::tell", self.command_tell)
        # Permission management
        self.add_command_handler("pm::authorize", self.command_authorize)
        self.add_command_handler("pm::deauthorize", self.command_authorize)
        self.add_command_handler("pm::group", self.command_group)
        self.add_command_handler("pm::usergroup", self.command_user_group)
        # MMR and rankings
        self.add_command_handler("pm::mmr", self.command_mmr)
        self.add_command_handler("pm::rawmmr", self.command_mmr)
        self.add_command_handler("pm::elo", self.command_elo)
        self.add_command_handler("pm::serverrank", self.command_server_rank)
        self.add_command_handler("pm::serverrankdetail", self.command_server_rank_detailed)
        self.add_command_handler("pm::sr", self.command_server_rank)
        self.add_command_handler("pm::srd", self.command_server_rank_detailed)
        # Match/Server
        self.add_command_handler("pm::spectate", self.command_spectate)
        self.add_command_handler("pm::spec", self.command_spectate)
        # Party
        self.add_command_handler("pm::party", self.command_party)
        self.add_command_handler("pm::partylist", self.command_party_list)
        self.add_command_handler("pm::partyinvite", self.command_party_invite)
        self.add_command_handler("pm::partykick", self.command_party_kick)
        self.add_command_handler("pm::partydeploy", self.command_party_deploy)
        self.add_command_handler("pm::partycancel", self.command_party_cancel)
        self.add_command_handler("pm::partyconfirm", self.command_party_confirm)
        self.add_command_handler("pm::partyleave", self.command_party_leave)
        self.add_command_handler("pm::partytransfer", self.command_party_transfer)
        self.add_command_handler("pm::plist", self.command_party_list)
        self.add_command_handler("pm::pinvite", self.command_party_invite)
        self.add_command_handler("pm::pkick", self.command_party_kick)
        self.add_command_handler("pm::pdeploy", self.command_party_deploy)
        self.add_command_handler("pm::pcancel", self.command_party_cancel)
        self.add_command_handler("pm::pconfirm", self.command_party_confirm)
        self.add_command_handler("pm::pleave", self.command_party_leave)
        self.add_command_handler("pm::ptransfer", self.command_party_transfer)
        # Party (from party)
        self.add_command_handler("muc::invite", self.command_party_invite)
        self.add_command_handler("muc::kick", self.command_party_kick)
        self.add_command_handler("muc::deploy", self.command_party_deploy)
        self.add_command_handler("muc::cancel", self.command_party_cancel)
        self.add_command_handler("muc::confirm", self.command_party_confirm)
        self.add_command_handler("muc::leave", self.command_party_leave)
        self.add_command_handler("muc::transfer", self.command_party_transfer)

        # Plugins
        self.register_plugin("xep_0030")  # Service Discovery
        self.register_plugin("xep_0045")  # Multi-User Chat
        self.register_plugin("xep_0199")  # XMPP Ping
        self.register_plugin("hawken_party")  # Hawken Party

        # Setup timers
        self.mmr_reset_thread = threading.Timer(self.mmr_period, self.reset_mmr)
        self.mmr_reset_thread.start()
        self.globals_update_thread = threading.Timer(self.globals_period, self.globals_update)
        self.globals_update_thread.start()
        self.party_cleanup_thread = threading.Timer(self.party_cleanup_period, self.party_cleanup)
        self.party_cleanup_thread.start()

    def _config_filename(self):
        filename = os.path.join(self.config_path, self.config_filename)
        logging.debug("Config filename: {}".format(filename))
        return filename

    def _config_load(self):
        logging.info("Loading the bot config.")

        # Read the config
        try:
            config_file = open(self._config_filename(), "r")
            try:
                data = config_file.read()
            finally:
                config_file.close()
        except IOError as ex:
            if ex.errno == errno.ENOENT:
                # File not found, write out the config.
                logging.info("No config file found, creating one.")
                self._config_save()
                return None
            else:
                logging.error("Failed to load config file: {0} {1}".format(type(ex), ex))
                return False
        config = json.loads(data)

        # Load in the config (fail permissively)
        polling = config.get("advertisement_polling", None)
        if polling is not None:
            self.advertisement_poll_limit = polling.get("limit", self.advertisement_poll_limit)
            self.advertisement_poll_rate = polling.get("rate", self.advertisement_poll_rate)
        self.command_prefix = config.get("command_prefix", self.command_prefix)
        self.bot_offline = config.get("offline", self.bot_offline)
        self.own_guid = config.get("api_username", self.own_guid)
        self.own_password = config.get("api_password", self.own_password)
        self.mmr_limit = config.get("mmr_limit", self.mmr_limit)
        self.mmr_period = config.get("mmr_period", self.mmr_period)
        self.mmr_restricted = config.get("mmr_restricted", self.mmr_restricted)
        self.sr_min = config.get("sr_min", self.sr_min)
        self.globals_period = config.get("globals_period", self.globals_period)
        self.party_cleanup_period = config.get("party_cleanup_period", self.party_cleanup_period)

        # Logging
        if "log_level" in config.keys():
            logging.getLogger().setLevel(config.get("log_level"))

        # Merge in the permissions
        if "permissions" in config.keys():
            self.permissions = dict(list(self.permissions.items()) + list(config["permissions"].items()))

        return True

    def _config_save(self):
        logging.debug("Saving the bot config.")

        # Logging
        log_level = logging.getLevelName(logging.getLogger().getEffectiveLevel())

        # Create the config structure, populate
        config = {
            "advertisement_polling": {
                "limit": self.advertisement_poll_limit,
                "rate": self.advertisement_poll_rate
            },
            "api_username": self.own_guid,
            "api_password": self.own_password,
            "command_prefix": self.command_prefix,
            "log_level": log_level,
            "offline": self.bot_offline,
            "permissions": self.permissions,
            "mmr_limit": self.mmr_limit,
            "mmr_period": self.mmr_period,
            "mmr_restricted": self.mmr_restricted,
            "sr_min": self.sr_min,
            "globals_period": self.globals_period,
            "party_cleanup_period": self.party_cleanup_period
        }

        # Write the config
        try:
            config_file = open(self._config_filename(), "w")
            try:
                json.dump(config, config_file, indent=2, sort_keys=True)
            finally:
                config_file.close()
        except IOError as ex:
            logging.error("Failed to save config file: {0} {1}".format(type(ex), ex))
            return False
        return True

    def send_chat_message(self, mto=None, mbody=None):
        # Fixes messages getting displayed as System Messages/Emergency Broadcasts
        self.send_message(mto=mto, mbody=mbody, mtype="chat")

    def send_group_message(self, mto=None, mbody=None):
        # Handle the backend nastyness
        self.plugin["hawken_party"].message(mto, self.boundjid.full, self.own_guid, mbody)

    def perms_init(self, groups):
        # Roundabout way of creating the attribute
        try:
            if self.permissions is None:
                self.permissions = {}
        except AttributeError:
            self.permissions = {}

        # Build the base permissions
        for group in groups:
            if group not in self.permissions.keys():
                self.permissions[group] = []

    def perms_group(self, group):
        try:
            return self.permissions[group]
        except KeyError:
            return None

    def perms_groups(self):
        return self.permissions.keys()

    def perms_user_group(self, guid, group):
        try:
            return guid in self.permissions[group]
        except KeyError:
            return None

    def perms_user_check_groups(self, guid, groups):
        # Check for stupidity
        if len(groups) == 0:
            return False

        # Scan the groups for the user, stop on match
        match = False
        for group, users in self.permissions.items():
            if group in groups and guid in users:
                # Found user in group
                match = True
                break

        return match

    def perms_user_groups(self, guid):
        # Scan the groups for the user
        groups = []
        for group, users in self.permissions.items():
            if guid in users:
                # Found user in group
                groups.append(group)

        return groups

    def perms_group_user_add(self, group, user):
        try:
            # Check if the user is already in the group
            if user in self.permissions[group]:
                return False
            else:
                # Add the user to the group
                self.permissions[group].append(user)

                # Save config
                self._config_save()
                return True
        except:
            return None

    def perms_group_user_remove(self, group, user):
        try:
            # Check if the user is not in the group
            if user not in self.permissions[group]:
                return False
            else:
                # Remove the user from the group
                self.permissions[group].remove(user)

                # Save config
                self._config_save()
                return True
        except:
            return None

    def is_friend(self, guid):
        # Generate the JID
        jid = "{0}@{1}".format(guid, self.xmpp_server)

        return jid in self.client_roster.keys()

    def add_command_handler(self, command, handler):
        self.registered_commands[command.lower()] = handler

    def get_cached_callsign(self, guid):
        # Check cache for callsign
        if guid in self.callsigns.keys():
            return self.callsigns[guid]

        # Fetch callsign
        callsign = self.hawken_api.user_callsign(guid)
        if callsign is not None:
            # Cache callsign
            self.callsigns[guid] = callsign

        return callsign

    def get_cached_guid(self, callsign):
        # Case insensitive search
        callsign = callsign.lower()

        # Check cache for guid
        for guid, cs in self.callsigns.items():
            if cs.lower() == callsign:
                return guid

        # Fetch GUID
        guid = self.hawken_api.user_guid(callsign)
        # TODO: Do we want to cache a case-insensitive callsign here?

        return guid

    def party_get(self, identifier):
        # Look for the party by guid
        if identifier in self.parties.keys():
            return self.parties[identifier]

        # Look for a matching alias
        for alias, guid in self.party_alias.items():
            if alias.lower() == identifier.lower():
                return self.parties[guid]

        # Could not find party
        return False

    def party_create(self, guid, alias=None):
        # Create the party
        self.parties[guid] = Party(self, guid, self.own_guid, self.own_callsign)
        self.parties[guid].create()

        # Add an alias, if given
        if alias is not None:
            self.party_alias[alias] = guid

    def party_join(self, guid, alias=None):
        # Join the party
        self.parties[guid] = Party(self, guid, self.own_guid, self.own_callsign)
        self.parties[guid].join()

        # Add an alias, if given
        if alias is not None:
            self.party_alias[alias] = guid

    def party_leave(self, guid, leader=None):
        # Abort any deployment in progress
        self.parties[guid].abort()

        # Transfer to a new leader, if given
        if leader is not None:
            self.parties[guid].leader_set(leader)

        # Leave the party and forget about it
        self.parties[guid].leave()
        del self.parties[guid]

        # Purge any aliases
        targets = [alias for alias, party in self.parties.items() if party == guid]
        for alias in targets:
            del self.party_alias[alias]

    def reservation_init(self, guid):
        template = {
            "advertisements": [],
            "saved": None
        }
        if not guid in self.reservations:
            self.reservations[guid] = template

    def reservation_has(self, owner):
        # If the owner has a record and advertisements stored
        return owner in self.reservations.keys() and len(self.reservations[owner]["advertisements"]) > 0

    def reservation_has_saved(self, owner):
        # If the owner has a record and a saved server
        return owner in self.reservations.keys() and self.reservations[owner]["saved"] is not None

    def reservation_get(self, owner):
        # Check if there actually is a active reservation
        if self.reservation_has(owner):
            return self.reservations[owner]["advertisements"]
        return []

    def reservation_get_current(self, owner):
        # Check if there actually is a active reservation
        if self.reservation_has(owner):
            return self.reservations[owner]["advertisements"][-1]
        return None

    def reservation_get_saved(self, owner):
        # Check if there actually is a saved server
        if self.reservation_has_saved(owner):
            return self.reservations[owner]["saved"]
        return None

    def reservation_add(self, owner, advertisement):
        # Init owner; check for duplicate advertisements
        self.reservation_init(owner)
        if advertisement in self.reservations[owner]["advertisements"]:
            return False

        # Save advertisement
        self.reservations[owner]["advertisements"].append(advertisement)
        return True

    def reservation_set_saved(self, owner, server):
        # Init owner
        self.reservation_init(owner)

        # Save server
        self.reservations[owner]["saved"] = server
        return True

    def reservation_delete(self, owner, advertisement):
        # Check that the advertisement exists
        if self.reservation_has(owner) and advertisement in self.reservations[owner]["advertisements"]:
            # Delete the reservation
            self.reservations[owner]["advertisements"].remove(advertisement)
            self.hawken_api.matchmaking_advertisement_delete(advertisement)
            return True
        return False

    def reservation_delete_current(self, owner):
        return self.reservation_delete(owner, self.reservation_get_current(owner))

    def reservation_post_server(self, owner, server, users=None, party=False):
        # Autoset users, if needed
        if users is None and not party:
            users = [owner]

        # Post the advertisement
        if party:
            advertisement = self.hawken_api.matchmaking_advertisement_post_server(server["GameVersion"], server["Region"], server["Guid"], self.own_guid, users, owner)
        else:
            advertisement = self.hawken_api.matchmaking_advertisement_post_server(server["GameVersion"], server["Region"], server["Guid"], self.own_guid, users)

        # Record the advertisement
        self.reservation_add(owner, advertisement)

    def reservation_clear(self, owner):
        # Check that there is actually some data before trying to remove it
        if owner in self.reservations.keys():
            # Delete each of the advertisements stored
            for advertisement in self.reservation_get(owner):
                self.reservation_delete(owner, advertisement)

            # Drop data stored
            del self.reservations[owner]

    def update_roster(self):
        logging.info("Updating roster.")
        # Process roster list
        whitelist = set(self.perms_group("admin") + self.perms_group("whitelist"))
        for jid in self.client_roster.keys():
            user = jid.split("@", 1)[0]
            # Check if the user is on the list
            if user in whitelist:
                # Remove user so we don't try to add them later
                whitelist.remove(user)
                # Make sure the user is whitelisted the user
                self.client_roster[jid]["whitelisted"] = True
            elif self.bot_offline:
                # gtfo <3
                self.client_roster[jid].remove()

            # Add a delay between removals so we don't spam the server
            time.sleep(0.05)
        # Whitelist any users we didn't see
        for user in whitelist:
            jid = "@".join((user, self.xmpp_server))
            self.client_roster.add(jid, whitelisted=True)

            # Add a delay between removals so we don't spam the server
            time.sleep(0.05)

    def user_whitelist(self, user):
        found = False
        # Check the roster for the user
        for jid in self.client_roster.keys():
            if user == jid.split("@", 1)[0]:
                # Set the user as whitelisted
                self.client_roster[jid]["whitelisted"] = True
                found = True
                break

        if not found:
            # Add the user as whitelisted
            self.client_roster.add("{}@{}".format(user, self.xmpp_server), whitelisted=True)

    def user_dewhitelist(self, user):
        # Check the roster for the user
        for jid in self.client_roster.keys():
            if user == jid.split("@", 1)[0]:
                # Set the user as whitelisted
                self.client_roster[jid]["whitelisted"] = False

                # Remove the user if the bot is in offline mode
                if self.bot_offline:
                    self.client_roster[jid].remove()
                break

        # If we got here, either way the user is unwhitelisted

    def server_mmr_statistics(self, users):
        # TODO: Redo the loop so this isn't needed or such
        users = deepcopy(users)
        mmr = {}

        # Calculate min/max/mean
        mmr["list"] = [user["mmr"] for user in users.values() if user["mmr"] is not None]
        if len(mmr["list"]) > 0:
            mmr["max"] = max(mmr["list"])
            mmr["min"] = min(mmr["list"])
            mmr["mean"] = math.fsum(mmr["list"])/float(len(mmr["list"]))

            # Process each user's stats
            for user in users.values():
                # Check if they have an mmr
                if not user["mmr"] is None:
                    # Calculate the deviation
                    user["deviation"] = user["mmr"] - mmr["mean"]  # Server MMR can be fixed

            # Calculate standard deviation
            stddev_list = [user["deviation"] ** 2 for user in users.values() if "deviation" in user]
            if len(stddev_list) > 0:
                mmr["stddev"] = math.sqrt(math.fsum(stddev_list)/float(len(stddev_list)))

            return mmr
        else:
            # Can't pull mmr out of thin air
            return False

    def poll_reservation(self, target, user):
        # Get the advertisement
        advertisement = self.reservation_get_current(user)

        # Begin polling the advertisement
        start_time = time.time()
        timeout = True
        while (time.time() - start_time) < self.advertisement_poll_limit:
            # Check the advertisement
            advertisement_info = self.hawken_api.matchmaking_advertisement(advertisement)
            # Verify the advertisement still exists
            if advertisement_info is None:
                # Verify the advertisement hasn't been canceled
                if not self.reservation_has(user):
                    logging.debug("Reservation for user '{0}' has been canceled - stopped polling.".format(user))
                    timeout = False
                    break
                else:
                    # Couldn't find reservation
                    self.send_chat_message(mto=target, mbody="Error: Could not retrieve advertisement - expired? Stopped polling for reservation.")
                    timeout = False
                    break
            else:
                # Check if the reservation has been completed
                if advertisement_info["ReadyToDeliver"]:
                    # Get the server name
                    try:
                        server_name = self.hawken_api.server_list(advertisement_info["AssignedServerGuid"])["ServerName"]
                    except KeyError:
                        server_name = "<unknown>"

                    message = "\nReservation for server '{2}' complete.\nServer IP: {0}:{1}.\n\nUse '{3}spectate confirm' after joining the server, or '{3}spectate cancel' if you do not plan on joining the server."
                    self.send_chat_message(mto=target, mbody=message.format(advertisement_info["AssignedServerIp"].strip(r"\n"), advertisement_info["AssignedServerPort"], server_name, self.command_prefix))
                    timeout = False
                    break

            # Sleep a bit before requesting again.
            time.sleep(self.advertisement_poll_rate)

        if timeout:
            self.reservation_delete(user, advertisement)
            self.send_chat_message(mto=target, mbody="Time limit reached - reservation canceled.")

    def poll_party_reservation(self, party):
        # Get the advertisement
        advertisement = self.party_get(party).reservation

        # Set the output target
        target = "{0}@{1}".format(party, self.xmpp_server_party)

        # Begin polling the advertisement
        start_time = time.time()
        abort = True
        while (time.time() - start_time) < self.advertisement_poll_limit:
            # Check the advertisement
            advertisement_info = self.hawken_api.matchmaking_advertisement(advertisement)
            # Verify the advertisement still exists
            if advertisement_info is None:
                # Verify the advertisement hasn't been canceled
                if not self.party_get(party).is_matchmaking():
                    logging.debug("Reservation for party '{0}' has been canceled - stopped polling.".format(party))
                    abort = True
                    break
                else:
                    # Couldn't find reservation
                    self.send_group_message(mto=target, mbody="Error: Could not retrieve advertisement - expired? Stopped deployment.")
                    abort = True
                    break
            else:
                # Check if the reservation has been completed
                if advertisement_info["ReadyToDeliver"]:
                    # Signal to deploy
                    self.party_get(party).deploy_start(advertisement_info["AssignedServerGuid"], advertisement_info["AssignedServerIp"].strip(r"\n"), advertisement_info["AssignedServerPort"])
                    abort = False
                    break

            # Wait a bit before requesting again.
            time.sleep(self.advertisement_poll_rate)

        if abort:
            self.party_get(party).abort()
            self.send_group_message(mto=target, mbody="Time limit reached - deployment aborted.")

    def reset_mmr(self):
        logging.info("Resetting MMR usage.")
        # A loop would probably be better here
        self.mmr_usage = dict.fromkeys(self.mmr_usage, 0)
        # Reschedule task
        self.mmr_reset_thread = threading.Timer(self.mmr_period, self.reset_mmr)
        self.mmr_reset_thread.start()

    def globals_update(self):
        logging.info("Updating globals.")
        # Get the global item, update settings
        global_data = self.hawken_api.game_items("ff7aa68d-d450-44c3-86f0-a403e87b0f64")
        self.spec_rankrange = global_data["MMPilotLevelRange"]
        # Reschedule task
        self.globals_update_thread = threading.Timer(self.globals_period, self.globals_update)
        self.globals_update_thread.start()

    def party_cleanup(self):
        logging.info("Purging empty parties.")
        # Purge all empty parties
        targets = [k for k, v in self.parties.items() if len(v.players) == 0]
        for guid in targets:
            self.party_leave(guid)
        # Reschedule task
        self.party_cleanup_thread = threading.Timer(self.party_cleanup_period, self.party_cleanup)
        self.party_cleanup_thread.start()

    def format_dhms(self, seconds):
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        output = []
        if days != 0:
            output.append("{} day".format(days))
        if hours != 0:
            output.append("{} hour".format(hours))
        if minutes != 0:
            output.append("{} minute".format(minutes))
        if seconds != 0:
            output.append("{} second".format(seconds))
        return" ".join(output)

    def command_botinfo(self, command, arguments, target, user):
        message = """Hello, I am ScrimBot, the Hawken Scrim Bot. I do various competitive-related and utility functions. I am run by Ashfire908.

If you need help with the bot, talk to Ashfire908 on the #hawkenscrim IRC channel, or send an email to: scrimbot@hawkenwiki.com

This bot is an unofficial tool, neither run nor endorsed by Adhesive Games or Meteor Entertainment."""
        self.send_chat_message(mto=target, mbody=message)

    @HiddenCommand()
    @RequiredPerm(("admin", ))
    def command_testexception(self, command, arguments, target, user):
        # Verify the user is an admin
        if not self.perms_user_group(user, "admin"):
            self.send_chat_message(mto=target, mbody="You are not an admin.")
        else:
            # Test - raise exception
            raise Exception("test error msg")

    @HiddenCommand()
    @RequiredPerm(("admin", ))
    def command_tell(self, command, arguments, target, user):
        # Verify the user is an admin
        if not self.perms_user_group(user, "admin"):
            self.send_chat_message(mto=target, mbody="You are not an admin.")
        else:
            # Check the arguments
            if len(arguments) < 1:
                self.send_chat_message(mto=target, mbody="Missing arguments: <user> <message>")
            else:
                callsign = arguments[0]
                message = " ".join(arguments[1:])

                # Get the user's guid
                guid = self.get_cached_guid(callsign)

                if guid is None:
                    self.send_chat_message(mto=target, mbody="Error: No such user.")
                else:
                    # Send the message
                    msg_target = "{0}@{1}".format(guid, self.xmpp_server)
                    self.send_chat_message(mto=msg_target, mbody=message)

    def command_commands(self, command, arguments, target, user, room=False):
        # Get a list of available commands
        command_list = []
        for command, handler in self.registered_commands.items():
            try:
                # Check for required perms
                if not self.perms_user_check_groups(user, handler._scrimcommand_required_perms):
                    # User does not have the perms to view this command
                    continue
            except AttributeError:
                pass

            try:
                # Check if hidden
                if handler._scrimcommand_hidden:
                    # Command is marked as hidden
                    continue
            except AttributeError:
                pass

            command_list.append(command)

        if room is False:
            commands = [self.command_prefix + x[4:] for x in command_list if x.find("pm::") == 0]
            self.send_chat_message(mto=target, mbody="Currently loaded commands: {0}".format(" ".join(sorted(commands))))
        else:
            commands = [self.command_prefix + x[5:] for x in command_list if x.find("muc::") == 0]
            self.send_group_message(mto=target, mbody="Currently loaded commands: {0}".format(" ".join(sorted(commands))))

    def command_whoami(self, command, arguments, target, user, room=False):
        # Get the user's callsign
        callsign = self.get_cached_callsign(user)

        if callsign is None:
            # No callsign - display error
            message = "Error: Failed to look up your callsign - possible corrupt account data?"
        else:
            # Display callsign
            message = "You are '{}'.".format(callsign)

        if not room:
            self.send_chat_message(mto=target, mbody=message)
        else:
            self.send_group_message(mto=target, mbody=message)

    @RequiredPerm(("admin", "mmr"))
    def command_mmr(self, command, arguments, target, user):
        # Check if the user is authorized to use the mmr mode
        if self.mmr_restricted and not self.perms_user_check_groups(user, ("admin", "mmr")):
            self.send_chat_message(mto=target, mbody="You are not authorized to lookup mmr.")
            return

        # Determine the requested user
        if len(arguments) > 0:
            target_user = self.get_cached_guid(arguments[0])
            identifier = "{}'s".format(arguments[0])
        else:
            target_user = user
            identifier = "Your"

        # Check if the limit is active
        limit_active = not self.perms_user_group(user, "admin") and self.mmr_limit != -1

        # Check the user is not over their limit
        if limit_active:
            try:
                if self.mmr_usage[user] >= self.mmr_limit:
                    # Refuse request
                    self.send_chat_message(mto=target, mbody="You have reached your limit of mmr requests for the current {} period.".format(self.format_dhms(self.mmr_period)))
                    return
            except KeyError:
                # No count set, just ignore
                pass

        # Verify the user is allowed to look up this person's mmr
        if target_user != user and not self.perms_user_group(user, "admin"):
            self.send_chat_message(mto=target, mbody="You are not an admin.")
        # Verify this is a real user
        elif not target_user:
            self.send_chat_message(mto=target, mbody="No such user.")
        else:
            # Get the user's stats
            stats = self.hawken_api.user_stats(target_user)

            if stats is None:
                # Failed to load data
                self.send_chat_message(mto=target, mbody="Error: Failed to look up {} stats.".format(identifier))
            elif "MatchMaking.Rating" not in stats.keys():
                # No MMR recorded
                self.send_chat_message(mto=target, mbody="Error: {} does not appear to have a MMR.".format(identifier))
            else:
                if limit_active:
                    # Record request
                    try:
                        self.mmr_usage[user] = self.mmr_usage[user] + 1
                    except KeyError:
                        self.mmr_usage[user] = 1

                # Determine if the full mmr should be shown
                if command == "rawmmr":
                    rating = stats["MatchMaking.Rating"]
                else:
                    rating = int(stats["MatchMaking.Rating"])

                # Display user's MMR
                if limit_active:
                    self.send_chat_message(mto=target, mbody="{0} MMR is {1}. ({2} out of {3} requests)".format(identifier, rating, self.mmr_usage[user], self.mmr_limit))
                else:
                    self.send_chat_message(mto=target, mbody="{0} MMR is {1}.".format(identifier, rating))

    @HiddenCommand()
    def command_elo(self, command, arguments, target, user):
        # Easter egg
        self.send_chat_message(mto=target, mbody="Fuck off. (use !mmr)")

    def command_server_rank(self, command, arguments, target, user):
        # Find the server the user is on
        server = self.hawken_api.user_server(user)

        # Check if they are actually on a server
        if server is None:
            self.send_chat_message(mto=target, mbody="You are not on a server.")
        else:
            # Load the server info
            server_info = self.hawken_api.server_list(server[0])

            if server_info is None:
                # Failed to load server info
                self.send_chat_message(mto=target, mbody="Error: Failed to load server info.")
            elif len(server_info["Users"]) < 1:
                # No one is on the server
                self.send_chat_message(mto=target, mbody="No one is on the server '{0[ServerName]}'.".format(server_info))
            elif len(server_info["Users"]) < self.sr_min and not self.perms_user_group(user, "admin"):
                # Not enough people on the server
                self.send_chat_message(mto=target, mbody="There needs to be at least {0} people on the server to use this command.".format(self.sr_min))
            else:
                # Display the standard server rank
                message = "Ranking info for {0[ServerName]}: MMR Average: {0[ServerRanking]}, Average Pilot Level: {0[DeveloperData][AveragePilotLevel]}".format(server_info)
                self.send_chat_message(mto=target, mbody=message)

    def command_server_rank_detailed(self, command, arguments, target, user):
        # Find the server the user is on
        server = self.hawken_api.user_server(user)

        # Check if they are actually on a server
        if server is None:
            self.send_chat_message(mto=target, mbody="You are not on a server.")
        else:
            # Load the server info
            server_info = self.hawken_api.server_list(server[0])

            if server_info is None:
                # Failed to load server info
                self.send_chat_message(mto=target, mbody="Error: Failed to load server info.")
            elif len(server_info["Users"]) < 1:
                # No one is on the server
                self.send_chat_message(mto=target, mbody="No one is on {0[ServerName]}.".format(server_info))
            elif len(server_info["Users"]) < self.sr_min and not self.perms_user_group(user, "admin"):
                # Not enough people on the server
                self.send_chat_message(mto=target, mbody="There needs to be at least {0} people on the server to use this command.".format(self.sr_min))
            else:
                # Load the MMR for all the players on the server
                try:
                    data = self.hawken_api.user_stats(server_info["Users"])
                except InvalidBatch:
                    self.send_chat_message(mto=target, mbody="Error: Failed to load player data.")
                else:
                    users = {}
                    for user_data in data:
                        try:
                            mmr = user_data["MatchMaking.Rating"]
                        except KeyError:
                            # Handle a quirk of the API where users have no mmr
                            mmr = None

                        users[user_data["Guid"]] = {"mmr": mmr}

                    # Process stats, display
                    mmr_info = self.server_mmr_statistics(users)

                    if not mmr_info:
                        # No one with an mmr
                        self.send_chat_message(mto=target, mbody="No one on {0[ServerName]} has an mmr.".format(server_info))
                    else:
                        message = "MMR breakdown for {0[ServerName]}: Average MMR: {1[mean]:.2f}, Max MMR: {1[max]:.2f}, Min MMR: {1[min]:.2f}, Standard deviation {1[stddev]:.3f}".format(server_info, mmr_info)
                        self.send_chat_message(mto=target, mbody=message)

    @RequiredPerm(("admin", "spectator"))
    def command_spectate(self, command, arguments, target, user):
        # Check if the user is authorized to even think about using spectator mode
        if not self.perms_user_check_groups(user, ("admin", "spectator")):
            self.send_chat_message(mto=target, mbody="You are not authorized to spectate.")
        # Validate arguments
        elif len(arguments) < 1:
            self.send_chat_message(mto=target, mbody="Missing target server name or subcommand.")
        # Handle subcommands
        # Cancel/Ok
        elif arguments[0] in "cancel":
            # Delete the server reservation (as it's fulfilled now)
            if self.reservation_delete_current(user):
                self.send_chat_message(mto=target, mbody="Canceled pending server reservation.")
            else:
                self.send_chat_message(mto=target, mbody="No reservation found to cancel.")
        elif arguments[0] in "confirm":
            # Grab the reservation for the user
            reservation = self.reservation_get_current(user)
            if reservation is None:
                # No reservation found
                self.send_chat_message(mto=target, mbody="No reservation found to confirm.")
            else:
                # Load the advertisement
                advertisement = self.hawken_api.matchmaking_advertisement(reservation)

                if advertisement is None:
                    # Couldn't find the advertisement
                    self.send_chat_message(mto=target, mbody="Error: Failed to load reservation info - advertisement probably expired.")
                else:
                    # Save the advertisement server for later use
                    result = self.reservation_set_saved(user, advertisement["AssignedServerGuid"])
                    self.send_chat_message(mto=target, mbody="Reservation confirmed; saved for future use.")

                # Delete the server reservation (as it's fulfilled now)
                self.reservation_delete_current(user)
        # Save current
        elif arguments[0] == "save":
            # Get the user's current server
            server = self.hawken_api.user_server(user)

            # Check if they are actually on a server
            if server is None:
                self.send_chat_message(mto=target, mbody="You are not on a server.")
            else:
                result = self.reservation_set_saved(user, server[0])

                if result is True:
                    self.send_chat_message(mto=target, mbody="Current server saved for future use.")
                else:
                    logging.warn("Command spectate savecurrent returned non-true on advertisement save - this should not happen.")
                    self.send_chat_message(mto=target, mbody="Error: Failed to save current server for future use. (This is a bug, please report it.)")
        # Clear
        elif arguments[0] == "clear":
            # Clear the advertisement info for the user
            self.reservation_clear(user)
            self.send_chat_message(mto=target, mbody="Cleared stored reservation info for your user.")
        # Renew
        elif arguments[0] == "renew":
            # Check if the user has a saved advertisement
            if not self.reservation_has_saved(user):
                self.send_chat_message(mto=target, mbody="No saved reservation on file.")
            else:
                # Get the server info
                server = self.hawken_api.server_list(self.reservation_get_saved(user))
                # Check we got a server
                if server is None:
                    self.send_chat_message(mto=target, mbody="Error: Could not find server from the last reservation.")
                else:
                    # Place the reservation
                    self.reservation_post_server(user, server)

                    self.send_chat_message(mto=target, mbody="Renewing server reservation, waiting for response... use '{0}{1} cancel' to abort.".format(self.command_prefix, command))
                    self.poll_reservation(target, user)
        # Handle normal server requests
        else:
            # Get the server info
            server = self.hawken_api.server_by_name(arguments[0])

            # Verify the info
            if server is False:
                self.send_chat_message(mto=target, mbody="Error: Failed to load server list.")
            elif server is None:
                self.send_chat_message(mto=target, mbody="Error: Could not find server '{0}'.".format(arguments[0]))
            else:
                # Check for possible issues with the reservation
                # Server full
                user_count = len(server["Users"])
                if user_count >= server["MaxUsers"]:
                    self.send_chat_message(mto=target, mbody="Warning: Server is full ({0}/{1}) - reservation may fail!".format(user_count, server["MaxUsers"]))
                # Server outside user's rank
                server_level = int(server["DeveloperData"]["AveragePilotLevel"])
                if server_level != 0:
                    user_stats = self.hawken_api.user_stats(user)
                    if user_stats is not None:
                        user_level = int(user_stats["Progress.Pilot.Level"])
                        if user_level + self.spec_rankrange <= server_level or \
                           user_level - self.spec_rankrange >= server_level:
                            self.send_chat_message(mto=target, mbody="Warning: Server outside your skill level ({1} vs {0}) - reservation may fail!".format(user_level, server_level))

                # Place the reservation
                self.reservation_post_server(user, server)

                self.send_chat_message(mto=target, mbody="Placing server reservation, waiting for response... use '{0}{1} cancel' to abort.".format(self.command_prefix, command))
                self.poll_reservation(target, user)

    @RequiredPerm(("admin", ))
    def command_authorize(self, command, arguments, target, user):
        # Verify the user is an admin
        if not self.perms_user_group(user, "admin"):
            self.send_chat_message(mto=target, mbody="You are not an admin.")
        # Verify arguments count
        elif len(arguments) != 2:
            self.send_chat_message(mto=target, mbody="Missing arguments. Syntax: <user> <group>")
        else:
            # Grab the arguments
            target_callsign, group = arguments
            group = group.lower()

            # Get the target's guid
            target_guid = self.get_cached_guid(target_callsign)

            # Check the user exists
            if target_guid is None:
                self.send_chat_message(mto=target, mbody="No such user exists.")
            # Can't change the permissions of your own user
            elif target_guid == user:
                self.send_chat_message(mto=target, mbody="You cannot change the permissions on your own user.")
            # Check the group type
            elif group not in self.perms_groups():
                self.send_chat_message(mto=target, mbody="Unknown group '{0}'.".format(group))
            else:
                if command == "authorize":
                    # Check if the user is already in the group
                    if self.perms_user_group(group, target_guid):
                        self.send_chat_message(mto=target, mbody="'{0}' is already in the '{1}' group.".format(target_callsign, group))
                    else:
                        update_whitelist = group in ("admin", "whitelist") and not self.perms_user_check_groups(target_guid, ("admin", "whitelist"))
                        self.perms_group_user_add(group, target_guid)
                        self.send_chat_message(mto=target, mbody="'{0}' has been added to the '{1}' group.".format(target_callsign, group))
                        if update_whitelist:
                            self.user_whitelist(target_guid)
                            self.send_chat_message(mto=target, mbody="Whitelist updated.")
                else:
                    # Check if the user is not in the group
                    if self.perms_user_group(group, target_guid):
                        self.send_chat_message(mto=target, mbody="'{0}' is not in the '{1}' group.".format(target_callsign, group))
                    else:
                        self.perms_group_user_remove(group, target_guid)
                        self.send_chat_message(mto=target, mbody="'{0}' has been removed from the '{1}' group.".format(target_callsign, group))
                        if group in ("admin", "whitelist") and not self.perms_user_check_groups(target_guid, ("admin", "whitelist")):
                            self.user_dewhitelist(target_guid)
                            self.send_chat_message(mto=target, mbody="Whitelist updated.")

    @RequiredPerm(("admin", ))
    def command_group(self, command, arguments, target, user):
        # Verify the user is an admin
        if not self.perms_user_group(user, "admin"):
            self.send_chat_message(mto=target, mbody="You are not an admin.")
        # Check if we are looking up a specific group
        elif len(arguments) > 0:
            group = arguments[0].lower()
            # Verify we have a valid group
            if group not in self.perms_groups():
                self.send_chat_message(mto=target, mbody="Unknown group '{0}'.".format(group))
            else:
                # Convert guids to callsigns, where possible.
                users = [self.get_cached_callsign(x) or x for x in self.perms_group(group)]
                # Display the users in the group
                if len(users) == 0:
                    self.send_chat_message(mto=target, mbody="No users in group '{0}'.".format(group))
                else:
                    self.send_chat_message(mto=target, mbody="Users in group '{0}': {1}".format(group, ", ".join(sorted(users))))
        else:
            # Display the groups
            self.send_chat_message(mto=target, mbody="Groups: {0}".format(", ".join(sorted(self.perms_groups()))))

    def command_user_group(self, command, arguments, target, user):
        # Check if we have a specific user
        if len(arguments) > 0:
            target_callsign = arguments[0]
            target_guid = self.get_cached_guid(target_callsign)
            if target_guid is None:
                self.send_chat_message(mto=target, mbody="No such user exists.")
                return
            # Check if requesting another user, if so verify the user is an admin
            elif target_guid != user and not self.perms_user_group(user, "admin"):
                self.send_chat_message(mto=target, mbody="You are not an admin.")
                return
            elif target_guid == user:
                identifier = "you are"
            else:
                identifier = "'{0}' is".format(target_callsign)
        else:
            target_guid = user
            identifier = "you are"

        # Display the groups the user is in
        groups = self.perms_user_groups(target_guid)
        if len(groups) > 0:
            self.send_chat_message(mto=target, mbody="Groups {0} in: {1}".format(identifier, ", ".join(sorted(groups))))
        else:
            self.send_chat_message(mto=target, mbody="{0} not in any groups.".format(identifier))

    @HiddenCommand()
    @RequiredPerm(("admin", ))
    def command_save_config(self, command, arguments, target, user):
        # Verify the user is an admin
        if not self.perms_user_group(user, "admin"):
            self.send_chat_message(mto=target, mbody="You are not an admin.")
        else:
            # Save the current config
            self._config_save()
            self.send_chat_message(mto=target, mbody="Bot config saved.")

    @HiddenCommand()
    def command_hammertime(self, command, arguments, target, user):
        self.send_chat_message(mto=target, mbody="STOP! HAMMER TIME!")

    @RequiredPerm(("admin", "party"))
    def command_party(self, command, arguments, target, user):
        # Verify the user is able to lead parties
        if not self.perms_user_check_groups(user, ("admin", "party")):
            self.send_chat_message(mto=target, mbody="You are not authorized to manage a party.")
        else:
            if len(arguments) > 0:
                alias = arguments[0]
            else:
                alias = None

            # Create a party
            party_guid = Party.generate_guid()
            self.party_create(party_guid, alias)

            # Message the user
            if alias is None:
                message = "Created new party '{0}'. Inviting you to it...".format(party_guid)
            else:
                message = "Created new party '{1}' ({0}). Inviting you to it...".format(party_guid, alias)

            self.send_chat_message(mto=target, mbody=message)

            # Invite the user
            self.parties[party_guid].invite(target, self.get_cached_callsign(user))

    @RequiredPerm(("admin", "party"))
    def command_party_list(self, command, arguments, target, user):
        # Verify the user is able to lead parties
        if not self.perms_user_check_groups(user, ("admin", "party")):
            self.send_chat_message(mto=target, mbody="You are not authorized to manage a party.")
        else:
            # Display aliases in favor of guids
            parties = []
            guids = []
            for alias, guid in self.party_alias.items():
                parties.append(alias)
                guids.append(guid)

            for guid in self.parties.keys():
                if guid not in guids:
                    parties.append(guid)

            self.send_chat_message(mto=target, mbody="Current parties: {0}".format(", ".join(parties)))

    @RequiredPerm(("admin", "party"))
    def command_party_invite(self, command, arguments, target, user, room=None):
        # Verify the user is able to lead parties
        if not self.perms_user_check_groups(user, ("admin", "party")):
            if room is None:
                self.send_chat_message(mto=target, mbody="You are not authorized to manage a party.")
            else:
                self.send_group_message(mto=target, mbody="You are not authorized to manage a party.")
        else:
            if room is not None and len(arguments) < 1:
                self.send_group_message(mto=target, mbody="Missing target user.")
            elif room is None and len(arguments) < 2:
                self.send_chat_message(mto=target, mbody="Missing target user and/or party.")
            else:
                # Get the target
                target_user = self.get_cached_guid(arguments[0])
                if room is None:
                    party = self.party_get(arguments[1])
                else:
                    party = self.party_get(room)

                # Check party
                if party is False:
                    # Can't get here from a party
                    self.send_chat_message(mto=target, mbody="No such party.")
                # Check user
                elif target_user is None:
                    if room is None:
                        self.send_chat_message(mto=target, mbody="No such user.")
                    else:
                        self.send_group_message(mto=target, mbody="No such user.")
                else:
                    # Check party state
                    if party.is_matchmaking():
                        if room is None:
                            self.send_chat_message(mto=target, mbody="Warning: Party is currently matchmaking.")
                        else:
                            self.send_group_message(mto=target, mbody="Warning: Party is currently matchmaking.")

                    # Send an invite to the target
                    party.invite("{0}@{1}".format(target_user, self.xmpp_server), self.get_cached_callsign(target_user))
                    if room is None:
                        self.send_chat_message(mto=target, mbody="Invited {0} to the party.".format(self.get_cached_callsign(target_user)))

    @RequiredPerm(("admin", "party"))
    def command_party_kick(self, command, arguments, target, user, room=None):
        # Verify the user is able to lead parties
        if not self.perms_user_check_groups(user, ("admin", "party")):
            if room is None:
                self.send_chat_message(mto=target, mbody="You are not authorized to manage a party.")
            else:
                self.send_group_message(mto=target, mbody="You are not authorized to manage a party.")
        else:
            if room is not None and len(arguments) < 1:
                self.send_group_message(mto=target, mbody="Missing target player.")
            elif room is None and len(arguments) < 2:
                self.send_chat_message(mto=target, mbody="Missing target player and/or party.")
            else:
                target_callsign = arguments[0]
                target_user = self.get_cached_guid(target_callsign)
                if room is None:
                    party = self.party_get(arguments[1])
                else:
                    party = self.party_get(room)

                # Check party
                if party is False:
                    # Can't get here from a party
                    self.send_chat_message(mto=target, mbody="No such party.")
                # Check player
                elif target_user is None:
                    if room is None:
                        self.send_chat_message(mto=target, mbody="No such player.")
                    else:
                        self.send_group_message(mto=target, mbody="No such player.")
                elif target_user not in party.players:
                    message = "{0} is not in the party.".format(target_callsign)
                    if room is None:
                        self.send_chat_message(mto=target, mbody=message)
                    else:
                        self.send_group_message(mto=target, mbody=message)
                else:
                    if room is None:
                        self.send_chat_message(mto=target, mbody="Kicking {0} from the party.".format(target_callsign))

                    party.kick(target_callsign)

    @RequiredPerm(("admin", "party"))
    def command_party_deploy(self, command, arguments, target, user, room=None):
        # Verify the user is able to lead parties
        if not self.perms_user_check_groups(user, ("admin", "party")):
            if room is None:
                self.send_chat_message(mto=target, mbody="You are not authorized to manage a party.")
            else:
                self.send_group_message(mto=target, mbody="You are not authorized to manage a party.")
        else:
            if room is not None and len(arguments) < 1:
                self.send_group_message(mto=target, mbody="Missing target server name.")
            elif room is None and len(arguments) < 2:
                self.send_chat_message(mto=target, mbody="Missing target server name and/or party.")
            else:
                # Get the server info
                server = self.hawken_api.server_by_name(arguments[0])

                if room is None:
                    party = self.party_get(arguments[1])
                else:
                    party = self.party_get(room)

                # Check party
                if party is False:
                    # Can't get here from a party
                    self.send_chat_message(mto=target, mbody="No such party.")
                # Check server
                elif server is False:
                    if room is None:
                        self.send_chat_message(mto=target, mbody="Error: Failed to load server list.")
                    else:
                        self.send_group_message(mto=target, mbody="Error: Failed to load server list.")
                elif server is None:
                    if room is None:
                        self.send_chat_message(mto=target, mbody="Error: Could not find server '{0}'.".format(arguments[0]))
                    else:
                        self.send_group_message(mto=target, mbody="Error: Could not find server '{0}'.".format(arguments[0]))
                else:
                    # Check for possible issues with the reservation
                    # Server full
                    user_count = len(server["Users"])
                    if user_count - len(party.players) >= server["MaxUsers"]:
                        message = "Warning: Server is full ({0}/{1}) - reservation may fail!".format(user_count, server["MaxUsers"])
                        if room is None:
                            self.send_chat_message(mto=target, mbody=message)
                        else:
                            self.send_group_message(mto=target, mbody=message)

                    # Notify deployment
                    if room is None:
                        self.send_chat_message(mto=target, mbody="Deploying to server... Deploying to server '{0}{1} cancel {2}' to abort.".format(self.command_prefix, command, arguments[1]))
                    else:
                        self.send_group_message(mto=target, mbody="Deploying party to server... '{0}cancel' to abort.".format(self.command_prefix))

                    # Place the reservation
                    advertisement = self.hawken_api.matchmaking_advertisement_post_server(server["GameVersion"], server["Region"], server["Guid"], self.own_guid, list(party.players))
                    party.matchmaking_start(advertisement)
                    self.poll_party_reservation(party.guid)

    @RequiredPerm(("admin", "party"))
    def command_party_cancel(self, command, arguments, target, user, room=None):
        # Verify the user is able to lead parties
        if not self.perms_user_check_groups(user, ("admin", "party")):
            if room is None:
                self.send_chat_message(mto=target, mbody="You are not authorized to manage a party.")
            else:
                self.send_group_message(mto=target, mbody="You are not authorized to manage a party.")
        else:
            if room is None and len(arguments) < 1:
                self.send_chat_message(mto=target, mbody="Missing target party.")
            else:
                if room is None:
                    party = self.party_get(arguments[0])
                else:
                    party = self.party_get(room)

                # Check party
                if party is False:
                    # Can't get here from a party
                    self.send_chat_message(mto=target, mbody="No such party.")

                if party.is_matchmaking():
                    # Abort the party
                    party.abort()
                    if room is None:
                        self.send_chat_message(mto=target, mbody="Canceled party matchmaking.")
                else:
                    if room is None:
                        self.send_chat_message(mto=target, mbody="Party is not matchmaking - nothing to cancel.")
                    else:
                        self.send_group_message(mto=target, mbody="Party is not matchmaking - nothing to cancel.")

    @RequiredPerm(("admin", "party"))
    def command_party_confirm(self, command, arguments, target, user, room=None):
        # Verify the user is able to lead parties
        if not self.perms_user_check_groups(user, ("admin", "party")):
            if room is None:
                self.send_chat_message(mto=target, mbody="You are not authorized to manage a party.")
            else:
                self.send_group_message(mto=target, mbody="You are not authorized to manage a party.")
        else:
            if room is None and len(arguments) < 1:
                self.send_chat_message(mto=target, mbody="Missing target party.")
            else:
                if room is None:
                    party = self.party_get(arguments[0])
                else:
                    party = self.party_get(room)

                # Check party
                if party is False:
                    # Can't get here from a party
                    self.send_chat_message(mto=target, mbody="No such party.")

                if party.is_matchmaking():
                    party.confirm()
                    if room is None:
                        self.send_chat_message(mto=target, mbody="Confirmed match. Standing by for next deployment.")
                    else:
                        self.send_group_message(mto=target, mbody="Confirmed match. Standing by for next deployment.")
                else:
                    if room is None:
                        self.send_chat_message(mto=target, mbody="Party is not matchmaking - nothing to confirm.")
                    else:
                        self.send_group_message(mto=target, mbody="Party is not matchmaking - nothing to confirm.")

    @RequiredPerm(("admin", "party"))
    def command_party_leave(self, command, arguments, target, user, room=None):
        # Verify the user is able to lead parties
        if not self.perms_user_check_groups(user, ("admin", "party")):
            if room is None:
                self.send_chat_message(mto=target, mbody="You are not authorized to manage a party.")
            else:
                self.send_group_message(mto=target, mbody="You are not authorized to manage a party.")
        else:
            if room is None and len(arguments) < 1:
                self.send_chat_message(mto=target, mbody="Missing target party.")
            else:
                if room is None:
                    party = self.party_get(arguments[0])
                else:
                    party = self.party_get(room)

                # Check party
                if party is False:
                    # Can't get here from a party
                    self.send_chat_message(mto=target, mbody="No such party.")
                # Check player
                else:
                    if room is None:
                        self.send_chat_message(mto=target, mbody="Leaving the party.")
                    else:
                        self.send_group_message(mto=target, mbody="Leaving the party, have a good day.")

                    self.party_leave(party.guid)

    @RequiredPerm(("admin", "party"))
    def command_party_transfer(self, command, arguments, target, user, room=None):
        # Verify the user is able to lead parties
        if not self.perms_user_check_groups(user, ("admin", "party")):
            if room is None:
                self.send_chat_message(mto=target, mbody="You are not authorized to manage a party.")
            else:
                self.send_group_message(mto=target, mbody="You are not authorized to manage a party.")
        else:
            if room is not None and len(arguments) < 1:
                self.send_group_message(mto=target, mbody="Missing target player.")
            elif room is None and len(arguments) < 2:
                self.send_chat_message(mto=target, mbody="Missing target player and/or party.")
            else:
                target_callsign = arguments[0]
                target_user = self.get_cached_guid(target_callsign)
                if room is None:
                    party = self.party_get(arguments[1])
                else:
                    party = self.party_get(room)

                # Check party
                if party is False:
                    # Can't get here from a party
                    self.send_chat_message(mto=target, mbody="No such party.")
                # Check player
                elif target_user is None:
                    if room is None:
                        self.send_chat_message(mto=target, mbody="No such player.")
                    else:
                        self.send_group_message(mto=target, mbody="No such player.")
                elif target_user not in party.players:
                    message = "{0} is not in the party.".format(target_callsign)
                    if room is None:
                        self.send_chat_message(mto=target, mbody=message)
                    else:
                        self.send_group_message(mto=target, mbody=message)
                else:
                    if room is None:
                        self.send_chat_message(mto=target, mbody="Transfering control over to {0} and leaving the party.".format(target_callsign))
                    else:
                        self.send_group_message(mto=target, mbody="Transfering control over to {0}. Have a good day.".format(target_callsign))

                    self.party_leave(party.guid, target_callsign)

    def bot_start(self, event):
        # Send presence info, retrieve roster
        self.send_presence()
        self.get_roster()

        if self.bot_offline:
            logging.warning("Offline mode enabled.")
            self.auto_authorize = False
            self.auto_subscribe = False
            self.update_roster()

        # CROWBAR IS READY
        logging.info("Bot connected and ready.")

    def handle_message(self, message):
        # Check if the bot is in offline mode, and if so, if the user is whitelisted
        if self.bot_offline and not self.perms_user_check_groups(message["from"].user, ("admin", "whitelist")):
            # Ignore it, we are offline
            pass
        elif message["type"] == "chat":
            # Drop messages from people not friends with
            if not self.is_friend(message["from"].user):
                pass
            # Refuse to take chat from the bot (loop prevention)
            elif message["from"].user == self.own_guid:
                pass
            # Ignore the bot's own default response
            elif message["body"] == "Beep boop.":
                pass
            # Check if this is a command
            elif message["body"][0] == self.command_prefix:
                # Pass it off to the handler
                self.handle_command(message["body"][1:], message)
            else:
                # BOOP
                message.reply("Beep boop.").send()

    def handle_groupchat_message(self, message):
        if message["type"] == "groupchat":
            # Refuse to take chat from the bot (loop prevention)
            if message["from"].resource == self.own_callsign:
                pass
            # Ignore the bot's own default response
            elif message["body"] == "Beep boop.":
                pass
            # Check if this is a command
            elif message["body"][0] == self.command_prefix:
                # Pass it off to the handler
                self.handle_command(message["body"][1:], message, True)

    def handle_command(self, args, message, party=False):
        # Split the arguments
        command, *arguments = args.split(" ")

        # Get the targeted handler name
        if not party:
            command_target = "pm::{0}".format(command.lower())
        else:
            command_target = "muc::{0}".format(command.lower())

        # Check if there is a handler registered
        if command_target not in self.registered_commands.keys():
            # No handler
            if not party:
                self.send_chat_message(mto=message["from"].bare, mbody="Error: No such command.")
            else:
                self.send_group_message(mto=message["from"].bare, mbody="Error: No such command.")
        else:
            # Fire off the handler
            handler = self.registered_commands[command_target]
            if not party:
                # Signature: handler(command, args, target, user)
                logging.info("Command {0} called by {1}".format(command, message["from"].user))
                try:
                    handler(command, arguments, message["from"].bare, message["from"].user)
                except Exception as ex:
                    logging.error("Command {0} has failed due to an exception: {1} {2}".format(command, type(ex), ex))
                    self.send_chat_message(mto=message["from"].bare, mbody="Error: The command you attempted to run has encountered an unhandled exception. {0} This error has been logged.".format(type(ex)))
                    raise
            else:
                # Signature: handler(command, args, target, user, room)
                logging.info("Command {0} called by {1}".format(command, message["stormid"].id))
                try:
                    handler(command, arguments, message["from"].bare, message["stormid"].id, message["from"].user)
                except Exception as ex:
                    logging.error("Command {0} has failed due to an exception: {1} {2}".format(command, type(ex), ex))
                    self.send_group_message(mto=message["from"].bare, mbody="Error: The command you attempted to run has encountered an unhandled exception. {0} This error has been logged.".format(type(ex)))
                    raise
