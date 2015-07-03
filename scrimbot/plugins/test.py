# -*- coding: utf-8 -*-

from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin


class TestPlugin(BasePlugin):
    @property
    def name(self):
        return "test"

    def enable(self):
        # Register commands
        self.register_command(CommandType.PM, "testexception", self.test_exception, hidden=True, safe=True)
        self.register_command(CommandType.ALL, "callsign", self.callsign, hidden=True)
        self.register_command(CommandType.ALL, "guid", self.guid, hidden=True)
        self.register_command(CommandType.PM, "tell", self.tell, permsreq=["admin"])
        self.register_command(CommandType.PM, "updateglobals", self.update_globals, permsreq=["admin"])
        self.register_command(CommandType.PM, "reconnect", self.reconnect, permsreq=["admin"])

    def disable(self):
        pass

    def connected(self):
        pass

    def disconnected(self):
        pass

    def test_exception(self, cmdtype, cmdname, args, target, user, party):
        raise Exception("Test Exception")

    def callsign(self, cmdtype, cmdname, args, target, user, party):
        # Check args
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing target user guid.")
        else:
            # Get the callsign
            callsign = self._api.get_user_callsign(args[0])

            # Check if we got a callsign back
            if callsign is None:
                message = "Error: No callsign found for given GUID."
            else:
                message = "User GUID resolves to '{0}'.".format(callsign)

            self._xmpp.send_message(cmdtype, target, message)

    def guid(self, cmdtype, cmdname, args, target, user, party):
        # Check args
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing target user callsign.")
        else:
            # Get the guid
            guid = self._api.get_user_guid(args[0])

            # Check if we got a guid back
            if guid is None:
                message = "Error: No user found for given callsign."
            else:
                message = "User callsign resolves to '{0}'.".format(guid)

            self._xmpp.send_message(cmdtype, target, message)

    def tell(self, cmdtype, cmdname, args, target, user, party):
        # Check the arguments
        if len(args) < 2:
            self._xmpp.send_message(cmdtype, target, "Missing target user and/or message.")
        else:
            callsign = args[0]
            message = " ".join(args[1:])

            # Get the user's guid
            guid = self._api.get_user_guid(callsign)

            if guid is None:
                self._xmpp.send_message(cmdtype, target, "No such user exists.")
            else:
                # Send the message
                self._xmpp.send_message(CommandType.PM, "{0}@{1}".format(guid, self._xmpp.boundjid.host), message)
                self._xmpp.send_message(cmdtype, target, "Message sent.")

    def update_globals(self, cmdtype, cmdname, args, target, user, party):
        # Update the globals cache
        self._cache.globals_update()

        self._xmpp.send_message(cmdtype, target, "Updated globals cache.")

    def reconnect(self, cmdtype, cmdname, args, target, user, party):
        self._xmpp.send_message(cmdtype, target, "Reconnecting to chat...", now=True)

        # Reconnect
        self._xmpp.disconnect(reconnect=True)


plugin = TestPlugin
