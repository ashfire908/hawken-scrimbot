# -*- coding: utf-8 -*-

from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin


class TestPlugin(BasePlugin):
    @property
    def name(self):
        return "test"

    def enable(self):
        # Register commands
        self.register_command(CommandType.PM, "testexception", self.test_exception, flags=["hidden", "safe"])
        self.register_command(CommandType.ALL, "hammertime", self.hammertime, flags=["hidden", "safe"])
        self.register_command(CommandType.ALL, "whoami", self.whoami)
        self.register_command(CommandType.ALL, "callsign", self.callsign, flags=["hidden"])
        self.register_command(CommandType.ALL, "guid", self.guid, flags=["hidden"])
        self.register_command(CommandType.PM, "tell", self.tell, flags=["permsreq"], permsreq=["admin"])
        self.register_command(CommandType.PM, "friends", self.friends, flags=["hidden"])
        self.register_command(CommandType.PM, "updateglobals", self.update_globals, flags=["permsreq"], permsreq=["admin"])

    def disable(self):
        # Unregister commands
        self.unregister_command(CommandType.PM, "testexception")
        self.unregister_command(CommandType.ALL, "hammertime")
        self.unregister_command(CommandType.ALL, "whoami")
        self.unregister_command(CommandType.ALL, "callsign")
        self.unregister_command(CommandType.ALL, "guid")
        self.unregister_command(CommandType.PM, "tell")
        self.unregister_command(CommandType.PM, "friends")
        self.unregister_command(CommandType.PM, "updateglobals")

    def connected(self):
        pass

    def disconnected(self):
        pass

    def test_exception(self, cmdtype, cmdname, args, target, user, room):
        raise Exception("Test Exception")

    def hammertime(self, cmdtype, cmdname, args, target, user, room):
        self._xmpp.send_message(cmdtype, target, "STOP! HAMMER TIME!")

    def whoami(self, cmdtype, cmdname, args, target, user, room):
        # Get the callsign
        callsign = self._cache.get_callsign(user)

        # Check if we got a callsign back
        if callsign is None:
            message = "Error: Failed to look up your callsign."
        else:
            message = "You are '{0}'.".format(callsign)

        self._xmpp.send_message(cmdtype, target, message)

    def callsign(self, cmdtype, cmdname, args, target, user, room):
        # Check args
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing target user guid.")
        else:
            # Get the callsign
            callsign = self._cache.get_callsign(args[0])

            # Check if we got a callsign back
            if callsign is None:
                message = "Error: No callsign found for given GUID."
            else:
                message = "User GUID resolves to '{0}'.".format(callsign)

            self._xmpp.send_message(cmdtype, target, message)

    def guid(self, cmdtype, cmdname, args, target, user, room):
        # Check args
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing target user callsign.")
        else:
            # Get the guid
            guid = self._cache.get_guid(args[0])

            # Check if we got a guid back
            if guid is None:
                message = "Error: No user found for given callsign."
            else:
                message = "User callsign resolves to '{0}'.".format(guid)

            self._xmpp.send_message(cmdtype, target, message)

    def tell(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        if len(args) < 2:
            self._xmpp.send_message(cmdtype, target, "Missing target user and/or message.")
        else:
            callsign = args[0]
            message = " ".join(args[1:])

            # Get the user's guid
            guid = self._cache.get_guid(callsign)

            if guid is None:
                self._xmpp.send_message(cmdtype, target, "No such user exists.")
            else:
                # Send the message
                self._xmpp.send_message(CommandType.PM, "{0}@{1}".format(guid, self._xmpp.boundjid.host), message)
                self._xmpp.send_message(cmdtype, target, "Message sent.")

    def friends(self, cmdtype, cmdname, args, target, user, room):
        # Count the number of friends
        count = 0
        online = 0
        for jid in self._xmpp.roster_list():
            if self._xmpp.client_roster[jid]["subscription"] != "none":
                count += 1

            if len(self._xmpp.client_roster[jid].resources) > 0:
                online += 1

        self._xmpp.send_message(cmdtype, target, "Total friends: {0} Online Friends: {1}".format(count, online))

    def update_globals(self, cmdtype, cmdname, args, target, user, room):
        # Update the globals cache

        self._cache.globals_update()
        self._xmpp.send_message(cmdtype, target, "Updated globals cache.")


plugin = TestPlugin
