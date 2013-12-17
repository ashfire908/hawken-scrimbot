# -*- coding: utf-8 -*-

import logging

logger = logging.getLogger(__name__)


class PermissionHandler:
    def __init__(self, xmpp, config):
        self.xmpp = xmpp
        self.config = config
        self._permissions = {}
        self._groups = set()

        # Register config
        self.config.register_config("bot.permissions", dict())

        # Load the permissions before we register the groups
        self.load()

        # Register core groups
        self.register_group("admin")
        self.register_group("whitelist")
        self.register_group("blacklist")

    def _update_groups(self):
        for group in self._groups:
            if group not in self._permissions:
                self._permissions[group] = []

    def load(self):
        # Filter through the config to normalize group names
        perms = {}
        for group, users in self.config.bot.permissions.items():
            perms[group.lower()] = users

        self._permissions = perms

        # Update the perms base on the groups
        self._update_groups()

    def save(self, commit=False):
        self.config.bot.permissions = self._permissions

        if commit:
            # Save the underlying config
            self.config.save()

    def register_group(self, group):
        self._groups.add(group)
        if group not in self._permissions:
            self._permissions[group] = []

        self.save()

    def unregister_group(self, group):
        self._groups.discard(group)
        # Preserve old config, don't purge group

        self.save()

    def group_list(self):
        return self._permissions

    def group_users(self, group):
        try:
            return self._permissions[group]
        except KeyError:
            return None

    def user_group_add(self, user, group):
        # Check if the user is already in the group
        if self.user_check_group(user, group):
            return False
        else:
            # Add the user to the group
            self._permissions[group].append(user)

            if group == "blacklist":
                # Remove the user
                self.xmpp.remove_jid(self.xmpp.format_jid(user))
            elif group in ("admin", "whitelist"):
                # Add the user
                self.xmpp.add_jid(self.xmpp.format_jid(user))

            # Save perms
            self.save(commit=True)
            return True

    def user_group_remove(self, user, group):
        # Check if the user is not in the group
        if not self.user_check_group(user, group):
            return False
        else:
            # Remove the user from the group
            self._permissions[group].remove(user)

            if self.config.bot.offline and group in ("admin", "whitelist") and \
               not self.user_check_groups(user, ("admin", "whitelist")):
                # Remove the user
                self.xmpp.remove_jid(self.xmpp.format_jid(user))

            # Save perms
            self.save(commit=True)
            return True

    def user_check_group(self, user, group):
        try:
            return user in self._permissions[group]
        except KeyError:
            return None

    def user_check_groups(self, user, groups):
        # Check for stupidity
        if len(groups) == 0:
            return False

        # Scan the groups for the user, stop on first match
        match = False
        for group in groups:
            if group in self._permissions:
                if user in self._permissions[group]:
                    # Found user in group
                    match = True
                    break

        return match

    def user_groups(self, user):
        # Scan the groups for the user
        groups = []
        for group, users in self._permissions.items():
            if user in users:
                # Found user in group
                groups.append(group)

        return groups
