# -*- coding: utf-8 -*-

from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin
from scrimbot.util import jid_user


class AdminPlugin(BasePlugin):
    @property
    def name(self):
        return "admin"

    def enable(self):
        # Register commands
        self.register_command(CommandType.PM, "authorize", self.authorize, flags=["permsreq"], permsreq=["admin"])
        self.register_command(CommandType.PM, "auth", self.authorize, flags=["permsreq", "alias"], permsreq=["admin"])
        self.register_command(CommandType.PM, "deauthorize", self.deauthorize, flags=["permsreq"], permsreq=["admin"])
        self.register_command(CommandType.PM, "deauth", self.deauthorize, flags=["permsreq", "alias"], permsreq=["admin"])
        self.register_command(CommandType.PM, "group", self.group, flags=["permsreq"], permsreq=["admin"])
        self.register_command(CommandType.PM, "usergroup", self.user_group)
        self.register_command(CommandType.PM, "save", self.save_data, flags=["permsreq"], permsreq=["admin"])
        self.register_command(CommandType.PM, "friends", self.friends, flags=["permsreq"], permsreq=["admin"])
        self.register_command(CommandType.PM, "friendsnamed", self.friends_named, flags=["permsreq"], permsreq=["admin"])
        self.register_command(CommandType.PM, "friendscount", self.friends_count, flags=["permsreq"], permsreq=["admin"])
        self.register_command(CommandType.PM, "load", self.plugin_load, flags=["permsreq"], permsreq=["admin"])
        self.register_command(CommandType.PM, "unload", self.plugin_unload, flags=["permsreq"], permsreq=["admin"])
        self.register_command(CommandType.PM, "shutdown", self.shutdown, flags=["permsreq"], permsreq=["admin"])

    def disable(self):
        # Unregister commands
        self.unregister_command(CommandType.PM, "authorize")
        self.unregister_command(CommandType.PM, "auth")
        self.unregister_command(CommandType.PM, "deauthorize")
        self.unregister_command(CommandType.PM, "deauth")
        self.unregister_command(CommandType.PM, "group")
        self.unregister_command(CommandType.PM, "usergroup")
        self.unregister_command(CommandType.PM, "save")
        self.unregister_command(CommandType.PM, "friends")
        self.unregister_command(CommandType.PM, "friendsnamed")
        self.unregister_command(CommandType.PM, "friendscount")
        self.unregister_command(CommandType.PM, "load")
        self.unregister_command(CommandType.PM, "unload")
        self.unregister_command(CommandType.PM, "shutdown")

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
        guid = self._cache.get_guid(callsign)

        if guid is None:
            return False, "No such user exists."

        # Disallow a user changing their own permissions
        if guid == user:
            return False, "You cannot change the permissions on your own user."

        # Looks ok!
        return True, callsign, guid, group

    def authorize(self, cmdtype, cmdname, args, target, user, room):
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

    def deauthorize(self, cmdtype, cmdname, args, target, user, room):
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

    def group(self, cmdtype, cmdname, args, target, user, room):
        # Check if we are looking up a specific group
        if len(args) > 0:
            group = args[0].lower()

            # Check group
            if group not in self._permissions.group_list():
                self._xmpp.send_message(cmdtype, target, "Unknown group '{0}'.".format(group))
            else:
                # Convert user guids to callsigns, where possible.
                users = [self._cache.get_callsign(x) or x for x in self._permissions.group_users(group)]

                # Display the users in the group
                if len(users) == 0:
                    self._xmpp.send_message(cmdtype, target, "No users in group '{0}'.".format(group))
                else:
                    self._xmpp.send_message(cmdtype, target, "Users in group '{0}': {1}".format(group, ", ".join(sorted(users))))
        else:
            # Display the groups
            self._xmpp.send_message(cmdtype, target, "Groups: {0}".format(", ".join(sorted(self._permissions.group_list()))))

    def user_group(self, cmdtype, cmdname, args, target, user, room):
        # Check if we have a specific user
        if len(args) > 0:
            callsign = args[0]
            guid = self._cache.get_guid(callsign)

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

    def save_data(self, cmdtype, cmdname, args, target, user, room):
        self._xmpp.send_message(cmdtype, target, "Saving bot config and cache.")

        # Save the current permissions, config, and cache
        self._permissions.save()
        self._config.save()
        self._cache.save()

    def get_friends(self):
        return [jid_user(jid) for jid in self._xmpp.roster_list() if self._xmpp.client_roster[jid]["subscription"] != "none"]

    def friends(self, cmdtype, cmdname, args, target, user, room):
        # Get the friends list
        friends = self.get_friends()
        self._xmpp.send_message(cmdtype, target, "Friends list ({1}): {0}".format(", ".join(friends), len(friends)))

    def friends_named(self, cmdtype, cmdname, args, target, user, room):
        # Get the friends list
        friends = self.get_friends()

        # Grab all the callsigns
        names = []
        for guid in friends:
            callsign = self._cache.get_callsign(guid)
            if callsign is None:
                names.append(guid)
            else:
                names.append(callsign)

        self._xmpp.send_message(cmdtype, target, "Friends list ({1}): {0}".format(", ".join(sorted(names, key=str.lower)), len(friends)))

    def friends_count(self, cmdtype, cmdname, args, target, user, room):
        # Get the friends list total
        count = len(self.get_friends())
        self._xmpp.send_message(cmdtype, target, "Current number of friends: {0}".format(count))

    def plugin_load(self, cmdtype, cmdname, args, target, user, room):
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
                    # Start the plugin, enable it in the config and save it
                    self._plugins.active[name].connected()
                    self._config.bot.plugins.append(name)
                    self._config.save()

                    self._xmpp.send_message(cmdtype, target, "Loaded plugin.")
                else:
                    self._xmpp.send_message(cmdtype, target, "Error: Failed to load plugin. Please check the logs for more information.")

    def plugin_unload(self, cmdtype, cmdname, args, target, user, room):
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
                    # Disable the plugin in the config and save it
                    self._config.bot.plugins.remove(name)
                    self._config.save()

                    self._xmpp.send_message(cmdtype, target, "Unloaded plugin.")
                else:
                    self._xmpp.send_message(cmdtype, target, "Error: Failed to unload plugin. Please check the logs for more information.")

    def shutdown(self, cmdtype, cmdname, args, target, user, room):
        # Send out the confirm message immediately so it doesn't get lost in the shutdown
        self._xmpp.send_message(cmdtype, target, "Shutting down the bot.", now=True)
        self._client.shutdown()


plugin = AdminPlugin
