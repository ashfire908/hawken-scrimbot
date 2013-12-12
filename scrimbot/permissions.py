# -*- coding: utf-8 -*-

import logging
import time
from scrimbot.util import jid_user

logger = logging.getLogger(__name__)


class PermissionHandler:
    def __init__(self, xmpp, config):
        self.xmpp = xmpp
        self.config = config
        self._permissions = {}
        self._groups = set()

        # Register config
        self.config.register_config("bot.permissions", dict())
        self.config.register_config("bot.offline", False)
        self.config.register_config("bot.roster_update_rate", 0.05)

        # Load the permissions before we register the groups
        self.load()

        # Register core groups
        self.register_group("admin")
        self.register_group("whitelist")

    def _update_groups(self):
        for group in self._groups:
            if group not in self._permissions.keys():
                self._permissions[group] = []

    def load(self):
        # Filter through the config to normalize group names
        perms = {}
        for group, users in self.config.bot.permissions.items():
            perms[group.lower()] = users

        self._permissions = perms

        # Update the perms base on the groups
        self._update_groups()

    def save(self):
        self.config.bot.permissions = self._permissions

    def register_group(self, group):
        self._groups.add(group)
        if group not in self._permissions.keys():
            self._permissions[group] = []

        self.save()

    def unregister_group(self, group):
        self._groups.discard(group)
        # Preserve old config, don't purge group

        self.save()

    def group_list(self):
        return self._permissions.keys()

    def group_users(self, group):
        try:
            return self._permissions[group]
        except KeyError:
            return None

    def has_user(self, user):
        # Generate the JID
        jid = "{0}@{1}".format(user, self.xmpp.boundjid.host)

        return jid in self.xmpp.client_roster.keys()

    def user_list(self):
        return [jid_user(jid) for jid in self.xmpp.client_roster.keys() if jid_user(jid) != self.xmpp.boundjid.user]

    def user_group_add(self, user, group):
        # Check if the user is already in the group
        if self.user_check_group(user, group):
            return False
        else:
            # Add the user to the group
            self._permissions[group].append(user)

            if group in ("admin", "whitelist"):
                # Whitelist the user
                self.user_whitelist(user)

            # Save perms
            self.save()
            return True

    def user_group_remove(self, user, group):
        # Check if the user is not in the group
        if not self.user_check_group(user, group):
            return False
        else:
            # Remove the user from the group
            self._permissions[group].remove(user)

            if group in ("admin", "whitelist") and not self.user_check_groups(user, ("admin", "whitelist")):
                # Dewhitelist the user
                self.user_dewhitelist(user)

            # Save perms
            self.save()
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
            if group in self._permissions.keys():
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

    def user_whitelist(self, user):
        found = False
        # Check the roster for the user
        for jid in self.xmpp.client_roster.keys():
            if user == jid_user(jid):
                # Set the user as whitelisted
                self.xmpp.client_roster[jid]["whitelisted"] = True

                found = True
                break

        if not found:
            jid = "{0}@{1}".format(user, self.xmpp.boundjid.host)

            # Add the user as whitelisted
            self.xmpp.client_roster.add(jid, whitelisted=True)

    def user_dewhitelist(self, user):
        # Check the roster for the user
        for jid in self.xmpp.client_roster.keys():
            if user == jid_user(jid):
                if not self.config.bot.offline:
                    # Unwhitelist the user
                    self.xmpp.client_roster[jid]["whitelisted"] = False
                else:
                    # Unwhitelist the user and remove them
                    self.xmpp.client_roster[jid].remove()
                    self.xmpp.client_roster.update(jid, subscription="remove", block=False)
                break

    def update_whitelist(self):
        logger.info("Updating roster.")

        # Generate the whitelist
        whitelist = set(self.group_users("admin") + self.group_users("whitelist"))

        # Update the existing roster entries
        for jid in self.xmpp.client_roster.keys():
            user = jid_user(jid)

            # Ignore the bot
            if user == self.xmpp.boundjid.user:
                continue

            # Check if the user is on the list
            if user in whitelist:
                # Make sure the user is whitelisted
                self.user_whitelist(user)

                # Remove user so we don't try to add them later
                whitelist.remove(user)

            elif self.config.bot.offline:
                # Remove unwhitelisted user
                self.user_dewhitelist(user)
            else:
                # Continue without delay
                continue

            # Add a delay between removals so we don't spam the server
            time.sleep(self.config.bot.roster_update_rate)

        # Whitelist any users we didn't see
        for user in whitelist:
            self.user_whitelist(user)

            # Add a delay between removals so we don't spam the server
            time.sleep(self.config.bot.roster_update_rate)
