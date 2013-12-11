# -*- coding: utf-8 -*-

from scrimbot.plugins.base import BasePlugin, Command, CommandType


class TestPlugin(BasePlugin):
    def init(self):
        # Register commands
        self.register_command(Command("testexception", CommandType.PM, self.test_exception, flags=["hidden", "safe"]))
        self.register_command(Command("hammertime", CommandType.PM, self.hammertime, flags=["hidden", "safe"]))
        self.register_command(Command("whoami", CommandType.ALL, self.whoami))
        self.register_command(Command("tell", CommandType.PM, self.tell, flags=["permsreq"], metadata={"permsreq": ["admin"]}))

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

    def tell(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        if len(args) < 2:
            self.xmpp.send_message(cmdtype, target, "Missing target user and/or message")
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
