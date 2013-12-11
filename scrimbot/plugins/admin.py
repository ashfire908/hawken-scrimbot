# -*- coding: utf-8 -*-

from scrimbot.plugins.base import BasePlugin, Command, CommandType


class AdminPlugin(BasePlugin):
    def init(self):
        # Register commands
        self.register_command(Command("authorize", CommandType.PM, self.authorize, flags=["permsreq"], metadata={"permsreq": ["admin"]}))
        self.register_command(Command("auth", CommandType.PM, self.authorize, flags=["permsreq", "alias"], metadata={"permsreq": ["admin"]}))
        self.register_command(Command("deauthorize", CommandType.PM, self.deauthorize, flags=["permsreq"], metadata={"permsreq": ["admin"]}))
        self.register_command(Command("deauth", CommandType.PM, self.deauthorize, flags=["permsreq", "alias"], metadata={"permsreq": ["admin"]}))
        self.register_command(Command("group", CommandType.PM, self.group, flags=["permsreq"], metadata={"permsreq": ["admin"]}))
        self.register_command(Command("usergroup", CommandType.PM, self.user_group))
        self.register_command(Command("save", CommandType.PM, self.save_data, flags=["permsreq"], metadata={"permsreq": ["admin"]}))
        self.register_command(Command("friends", CommandType.PM, self.friends, flags=["permsreq"], metadata={"permsreq": ["admin"]}))
        self.register_command(Command("friendsnamed", CommandType.PM, self.friends_named, flags=["permsreq"], metadata={"permsreq": ["admin"]}))
        self.register_command(Command("friendscount", CommandType.PM, self.friends_count, flags=["permsreq"], metadata={"permsreq": ["admin"]}))
        self.register_command(Command("load", CommandType.PM, self.plugin_load, flags=["permsreq"], metadata={"permsreq": ["admin"]}))
        self.register_command(Command("plugins", CommandType.PM, self.plugin_list, flags=["permsreq"], metadata={"permsreq": ["admin"]}))

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
        if group not in self.permissions.group_list():
            return False, "Unknown group '{0}'.".format(group)

        # Check callsign
        guid = self.cache.get_guid(callsign)

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
            self.xmpp.send_message(cmdtype, target, result[1])
        else:
            callsign, guid, group = result[1:]

            # Check if the user is already in the group
            if self.permissions.user_check_group(guid, group):
                self.xmpp.send_message(cmdtype, target, "'{0}' is already in the '{1}' group.".format(callsign, group))
            else:
                self.permissions.user_group_add(guid, group)
                self.xmpp.send_message(cmdtype, target, "'{0}' has been added to the '{1}' group.".format(callsign, group))

    def deauthorize(self, cmdtype, cmdname, args, target, user, room):
        # Verify arguments
        result = self.check_authorize_args(args, user)

        if not result[0]:
            self.xmpp.send_message(cmdtype, target, result[1])
        else:
            callsign, guid, group = result[1:]

            # Check if the user is not in the group
            if not self.permissions.user_check_group(guid, group):
                self.xmpp.send_message(cmdtype, target, "'{0}' is not in the '{1}' group.".format(callsign, group))
            else:
                self.permissions.user_group_remove(guid, group)
                self.xmpp.send_message(cmdtype, target, "'{0}' has been removed from the '{1}' group.".format(callsign, group))

    def group(self, cmdtype, cmdname, args, target, user, room):
        # Check if we are looking up a specific group
        if len(args) > 0:
            group = args[0].lower()

            # Check group
            if group not in self.permissions.group_list():
                self.xmpp.send_message(cmdtype, target, "Unknown group '{0}'.".format(group))
            else:
                # Convert user guids to callsigns, where possible.
                users = [self.cache.get_callsign(x) or x for x in self.permissions.group_users(group)]

                # Display the users in the group
                if len(users) == 0:
                    self.xmpp.send_message(cmdtype, target, "No users in group '{0}'.".format(group))
                else:
                    self.xmpp.send_message(cmdtype, target, "Users in group '{0}': {1}".format(group, ", ".join(sorted(users))))
        else:
            # Display the groups
            self.xmpp.send_message(cmdtype, target, "Groups: {0}".format(", ".join(sorted(self.permissions.group_list()))))

    def user_group(self, cmdtype, cmdname, args, target, user, room):
        # Check if we have a specific user
        if len(args) > 0:
            callsign = args[0]
            guid = self.cache.get_guid(callsign)

            if guid is None:
                self.xmpp.send_message(cmdtype, target, "No such user exists.")
                return
        else:
            guid = user

        # Get the groups
        groups = self.permissions.user_groups(guid)

        if guid == user:
            if len(groups) > 0:
                identifier = "you are"
            else:
                identifier = "You are"
        else:
            if self.permissions.user_check_group(user, "admin"):
                identifier = "'{0}' is".format(callsign)
            else:
                self.xmpp.send_message(cmdtype, target, "You are not an admin.")
                return

        # Display the groups the user is in
        if len(groups) > 0:
            self.xmpp.send_message(cmdtype, target, "Groups {0} in: {1}".format(identifier, ", ".join(sorted(groups))))
        else:
            self.xmpp.send_message(cmdtype, target, "{0} not in any groups.".format(identifier))

    def save_data(self, cmdtype, cmdname, args, target, user, room):
        self.xmpp.send_message(cmdtype, target, "Saving bot config and cache.")

        # Save the current permissions, config, and cache
        self.permissions.save()
        self.config.save()
        self.cache.save()

    def friends(self, cmdtype, cmdname, args, target, user, room):
        # Get the friends list
        friends = self.permissions.user_list()
        self.xmpp.send_message(cmdtype, target, "Friends list ({1}): {0}".format(", ".join(friends), len(friends)))

    def friends_named(self, cmdtype, cmdname, args, target, user, room):
        # Get the friends list
        friends = self.permissions.user_list()

        # Grab all the callsigns
        names = []
        for guid in friends:
            callsign = self.cache.get_callsign(guid)
            if callsign is None:
                names.append(guid)
            else:
                names.append(callsign)

        self.xmpp.send_message(cmdtype, target, "Friends list ({1}): {0}".format(", ".join(sorted(names, key=str.lower)), len(friends)))

    def friends_count(self, cmdtype, cmdname, args, target, user, room):
        # Get the friends list total
        count = len(self.permissions.user_list())
        self.xmpp.send_message(cmdtype, target, "Current number of friends: {0}".format(count))

    def plugin_load(self, cmdtype, cmdname, args, target, user, room):
        # Check arguments
        if len(args) < 1:
            self.xmpp.send_message(cmdtype, target, "Missing plugin name.")
        else:
            # Load the given plugin
            name = args[0].lower()

            if name in self.client.plugins.keys():
                self.xmpp.send_message(cmdtype, target, "Plugin is already loaded.")
            else:
                success, message = self.client.load_plugin(name)
                if success:
                    # Start the plugin, enable it in the config
                    self.client.plugins[name].connected()
                    self.config.bot.plugins.append(name)

                    self.xmpp.send_message(cmdtype, target, "Loaded plugin.")
                else:
                    self.xmpp.send_message(cmdtype, target, "Error: Failed to load plugin. {0}".format(message))

    def plugin_list(self, cmdtype, cmdname, args, target, user, room):
        self.xmpp.send_message(cmdtype, target, "Loaded plugins: {0}".format(", ".join(self.config.bot.plugins)))


plugin = AdminPlugin