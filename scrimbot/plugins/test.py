# -*- coding: utf-8 -*-

from scrimbot.plugins.base import BasePlugin, CommandType


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

    def disable(self):
        # Unregister commands
        self.unregister_command(CommandType.PM, "testexception")
        self.unregister_command(CommandType.ALL, "hammertime")
        self.unregister_command(CommandType.ALL, "callsign")
        self.unregister_command(CommandType.ALL, "guid")
        self.unregister_command(CommandType.PM, "tell")

    def connected(self):
        pass

    def disconnected(self):
        pass

    def test_exception(self, cmdtype, cmdname, args, target, user, room):
        raise Exception("Test Exception")

    def hammertime(self, cmdtype, cmdname, args, target, user, room):
        self.xmpp.send_message(cmdtype, target, "STOP! HAMMER TIME!")

    def whoami(self, cmdtype, cmdname, args, target, user, room):
        # Get the callsign
        callsign = self.cache.get_callsign(user)

        # Check if we got a callsign back
        if callsign is None:
            message = "Error: Failed to look up your callsign (corrupt account data?)"
        else:
            message = "You are '{0}'.".format(callsign)

        self.xmpp.send_message(cmdtype, target, message)

    def callsign(self, cmdtype, cmdname, args, target, user, room):
        # Check args
        if len(args) < 1:
            self.xmpp.send_message(cmdtype, target, "Missing target user guid.")
        else:
            # Get the callsign
            callsign = self.cache.get_callsign(args[0])

            # Check if we got a callsign back
            if callsign is None:
                message = "Error: No callsign found for given GUID."
            else:
                message = "User GUID resolves to '{0}'.".format(callsign)

            self.xmpp.send_message(cmdtype, target, message)

    def guid(self, cmdtype, cmdname, args, target, user, room):
        # Check args
        if len(args) < 1:
            self.xmpp.send_message(cmdtype, target, "Missing target user callsign.")
        else:
            # Get the guid
            guid = self.cache.get_guid(args[0])

            # Check if we got a guid back
            if guid is None:
                message = "Error: No user found for given callsign."
            else:
                message = "User callsign resolves to '{0}'.".format(guid)

            self.xmpp.send_message(cmdtype, target, message)

    def tell(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        if len(args) < 2:
            self.xmpp.send_message(cmdtype, target, "Missing target user and/or message.")
        else:
            callsign = args[0]
            message = " ".join(args[1:])

            # Get the user's guid
            guid = self.cache.get_guid(callsign)

            if guid is None:
                self.xmpp.send_message(cmdtype, target, "No such user exists.")
            else:
                # Send the message
                self.xmpp.send_message(CommandType.PM, "{0}@{1}".format(guid, self.xmpp.boundjid.host), message)


plugin = TestPlugin
