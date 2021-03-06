# -*- coding: utf-8 -*-

import ast
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin


class AdminPlugin(BasePlugin):
    @property
    def name(self):
        return "admin"

    def enable(self):
        # Register commands
        self.register_command(CommandType.PM, "authorize", self.authorize, permsreq=["admin"], alias=["auth"])
        self.register_command(CommandType.PM, "deauthorize", self.deauthorize, permsreq=["admin"], alias=["deauth"])
        self.register_command(CommandType.PM, "group", self.group, permsreq=["admin"])
        self.register_command(CommandType.PM, "usergroup", self.user_group)
        self.register_command(CommandType.PM, "load", self.plugin_load, permsreq=["admin"])
        self.register_command(CommandType.PM, "unload", self.plugin_unload, permsreq=["admin"])
        self.register_command(CommandType.PM, "save", self.save_data, permsreq=["admin"])
        self.register_command(CommandType.PM, "config", self.config, permsreq=["admin"])
        self.register_command(CommandType.PM, "shutdown", self.shutdown, permsreq=["admin"])
        self.register_command(CommandType.PM, "friends", self.friends, permsreq=["admin"])
        self.register_command(CommandType.PM, "isfriend", self.isfriend, permsreq=["admin"])
        self.register_command(CommandType.PM, "friend", self.friend, permsreq=["admin"])
        self.register_command(CommandType.PM, "unfriend", self.unfriend, permsreq=["admin"])

    def disable(self):
        pass

    def connected(self):
        pass

    def disconnected(self):
        pass

    def check_authorize_args(self, args, user):
        # Check for the right number of args
        if len(args) < 2:
            return False, "Missing target user and/or group."

        # Unpack args
        callsign, group = args[:2]
        group = group.lower()

        # Check group
        if group not in self._permissions.group_list():
            return False, "Unknown group '{0}'.".format(group)

        # Check callsign
        guid = self._api.get_user_guid(callsign)

        if guid is None:
            return False, "No such user exists."

        # Disallow a user changing their own permissions
        if guid == user:
            return False, "You cannot change the permissions on your own user."

        # Looks ok!
        return True, callsign, guid, group

    def authorize(self, cmdtype, cmdname, args, target, user, party):
        # Verify arguments
        result = self.check_authorize_args(args, user)

        if not result[0]:
            self._xmpp.send_message(cmdtype, target, result[1])
        else:
            callsign, guid, group = result[1:]

            # Check if the user is already in the group
            if self._permissions.user_check_group(guid, group):
                self._xmpp.send_message(cmdtype, target, "'{0}' is already in the '{1}' group.".format(callsign, group))
            else:
                self._permissions.user_group_add(guid, group)
                self._xmpp.send_message(cmdtype, target, "'{0}' has been added to the '{1}' group.".format(callsign, group))

    def deauthorize(self, cmdtype, cmdname, args, target, user, party):
        # Verify arguments
        result = self.check_authorize_args(args, user)

        if not result[0]:
            self._xmpp.send_message(cmdtype, target, result[1])
        else:
            callsign, guid, group = result[1:]

            # Check if the user is not in the group
            if not self._permissions.user_check_group(guid, group):
                self._xmpp.send_message(cmdtype, target, "'{0}' is not in the '{1}' group.".format(callsign, group))
            else:
                self._permissions.user_group_remove(guid, group)
                self._xmpp.send_message(cmdtype, target, "'{0}' has been removed from the '{1}' group.".format(callsign, group))

    def group(self, cmdtype, cmdname, args, target, user, party):
        # Check if we are looking up a specific group
        if len(args) > 0:
            group = args[0].lower()

            # Check group
            if group not in self._permissions.group_list():
                self._xmpp.send_message(cmdtype, target, "Unknown group '{0}'.".format(group))
            else:
                group_users = self._permissions.group_users(group)

                if len(group_users) == 0:
                    # Display the users in the group
                    self._xmpp.send_message(cmdtype, target, "No users in group '{0}'.".format(group))
                else:
                    # Convert user guids to callsigns, where possible.
                    callsign = self._api.get_user_callsign(group_users)
                    users = [callsign.get(x, x) for x in group_users]

                    # Display the users in the group
                    self._xmpp.send_message(cmdtype, target, "Users in group '{0}': {1}".format(group, ", ".join(sorted(users))))
        else:
            # Display the groups
            self._xmpp.send_message(cmdtype, target, "Groups: {0}".format(", ".join(sorted(self._permissions.group_list()))))

    def user_group(self, cmdtype, cmdname, args, target, user, party):
        # Check if we have a specific user
        if len(args) > 0:
            callsign = args[0]
            guid = self._api.get_user_guid(callsign)

            if guid is None:
                self._xmpp.send_message(cmdtype, target, "No such user exists.")
                return
        else:
            callsign = None
            guid = user

        # Get the groups
        groups = self._permissions.user_groups(guid)

        if guid == user:
            if len(groups) > 0:
                identifier = "you are"
            else:
                identifier = "You are"
        else:
            if self._permissions.user_check_group(user, "admin"):
                identifier = "'{0}' is".format(callsign)
            else:
                self._xmpp.send_message(cmdtype, target, "You are not an admin.")
                return

        # Display the groups the user is in
        if len(groups) > 0:
            self._xmpp.send_message(cmdtype, target, "Groups {0} in: {1}".format(identifier, ", ".join(sorted(groups))))
        else:
            self._xmpp.send_message(cmdtype, target, "{0} not in any groups.".format(identifier))

    def save_data(self, cmdtype, cmdname, args, target, user, party):
        self._xmpp.send_message(cmdtype, target, "Saving bot config and cache.")

        # Save the current permissions, config, and cache
        self._permissions.save()
        self._config.save()
        self._cache.save()

    def plugin_load(self, cmdtype, cmdname, args, target, user, party):
        # Check arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing plugin name.")
        else:
            # Load the given plugin
            name = args[0].lower()

            if name in self._plugins.active:
                self._xmpp.send_message(cmdtype, target, "Plugin is already loaded.")
            elif name in self._plugins.blacklist:
                self._xmpp.send_message(cmdtype, target, "Error: Specified plugin is blacklisted from being loaded.")
            else:
                if self._plugins.load(name):
                    self._xmpp.send_message(cmdtype, target, "Loaded plugin.")

                    self._config.bot.plugins = [plugin for plugin in self._plugins.active]
                    self._config.save()
                else:
                    self._xmpp.send_message(cmdtype, target, "Error: Failed to load plugin. Please check the logs for more information.")

    def plugin_unload(self, cmdtype, cmdname, args, target, user, party):
        # Check arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing plugin name.")
        else:
            # Load the given plugin
            name = args[0].lower()

            if name not in self._plugins.active:
                self._xmpp.send_message(cmdtype, target, "Plugin is not loaded.")
            else:
                if self._plugins.unload(name):
                    self._xmpp.send_message(cmdtype, target, "Unloaded plugin.")
                else:
                    self._xmpp.send_message(cmdtype, target, "Error: Failed to unload plugin. Please check the logs for more information.")

                self._config.bot.plugins = [plugin for plugin in self._plugins.active]
                self._config.save()

    def shutdown(self, cmdtype, cmdname, args, target, user, party):
        # Send out the confirm message immediately so it doesn't get lost in the shutdown
        self._xmpp.send_message(cmdtype, target, "Shutting down the bot.", now=True)
        self._client.shutdown()

    def config(self, cmdtype, cmdname, args, target, user, party):
        # Check arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing config name.")
        elif args[0] not in self._config:
            self._xmpp.send_message(cmdtype, target, "Error: No such config variable.")
        else:
            config = args[0]
            if len(args) == 1:
                # Display the config value
                self._xmpp.send_message(cmdtype, target, repr(self._config[config]))
            else:
                try:
                    value = ast.literal_eval(args[1])
                except ValueError:
                    self._xmpp.send_message(cmdtype, target, "Error: Invalid value given - must be a supported Python literal.")
                else:
                    # Set the config value
                    self._config[config] = value
                    self._xmpp.send_message(cmdtype, target, "Config value set.")

    def friends(self, cmdtype, cmdname, args, target, user, party):
        # Count the number of friends
        count = 0
        online = 0

        for jid, item in self._xmpp.roster_items():
            if item["subscription"] == "both":
                count += 1

                if len(item.resources) > 0:
                    online += 1

        self._xmpp.send_message(cmdtype, target, "Total friends: {0} Online Friends: {1}".format(count, online))

    def isfriend(self, cmdtype, cmdname, args, target, user, party):
        # Check arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing callsign.")
        else:
            guid = self._api.get_user_guid(args[0])

            if self._xmpp.has_jid(self._xmpp.format_jid(guid)):
                self._xmpp.send_message(cmdtype, target, "{0} is a friend of the bot.".format(args[0]))
            else:
                self._xmpp.send_message(cmdtype, target, "{0} is not a friend of the bot.".format(args[0]))

    def friend(self, cmdtype, cmdname, args, target, user, party):
        # Check arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing callsign.")
        else:
            guid = self._api.get_user_guid(args[0])

            if self._xmpp.add_jid(self._xmpp.format_jid(guid)):
                self._xmpp.send_message(cmdtype, target, "Added {0} as a friend.".format(args[0]))
            else:
                self._xmpp.send_message(cmdtype, target, "{0} is already a friend!".format(args[0]))

    def unfriend(self, cmdtype, cmdname, args, target, user, party):
        # Check arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing callsign.")
        else:
            guid = self._api.get_user_guid(args[0])

            self._xmpp.remove_jid(self._xmpp.format_jid(guid))
            self._xmpp.send_message(cmdtype, target, "Removed {0} as a friend.".format(args[0]))

plugin = AdminPlugin
