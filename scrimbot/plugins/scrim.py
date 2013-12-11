# -*- coding: utf-8 -*-

import time
import logging
import threading
from hawkenapi.sleekxmpp.party import CancelCode
from scrimbot.party import Party, DeploymentState
from scrimbot.plugins.base import BasePlugin, Command, CommandType
from scrimbot.util import jid_user

logger = logging.getLogger(__name__)


class ScrimPlugin(BasePlugin):
    def init_plugin(self):
        # Register config
        self.register_config("plugins.scrim.cleanup_period", 60 * 15)
        self.register_config("plugins.scrim.poll_limit", 30)

        # Register group
        self.register_group("scrim")

        # Register commands
        self.register_command(Command("createscrim", CommandType.PM, self.party_create, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("listscrim", CommandType.PM, self.party_list, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("invitescrim", CommandType.PM, self.party_invite, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("kickscrim", CommandType.PM, self.party_kick, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("deployscrim", CommandType.PM, self.party_deploy, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("cancelscrim", CommandType.PM, self.party_cancel, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("leavescrim", CommandType.PM, self.party_leave, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("transferscrim", CommandType.PM, self.party_transfer, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("screate", CommandType.PM, self.party_create, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("slist", CommandType.PM, self.party_list, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("sinvite", CommandType.PM, self.party_invite, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("skick", CommandType.PM, self.party_kick, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("sdeploy", CommandType.PM, self.party_deploy, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("scancel", CommandType.PM, self.party_cancel, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("sleave", CommandType.PM, self.party_leave, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("stransfer", CommandType.PM, self.party_transfer, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("invite", CommandType.PARTY, self.party_invite, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("kick", CommandType.PARTY, self.party_kick, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("deploy", CommandType.PARTY, self.party_deploy, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("cancel", CommandType.PARTY, self.party_cancel, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("leave", CommandType.PARTY, self.party_leave, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))
        self.register_command(Command("transfer", CommandType.PARTY, self.party_transfer, flags=["permsreq"], metadata={"permsreq": ["admin", "scrim"]}))

        # Setup party tracking
        self.scrims = {}
        self.scrim_count = 1
        self.cleanup_thread = None

    def connected(self):
        # Rejoin parties
        for party in self.scrims:
            if party.guid is not None:
                party.join(party.guid)

        # Start cleanup thread
        self.cleanup_thread = threading.Timer(self.config.plugins.scrim.cleanup_period, self.cleanup)
        self.cleanup_thread.start()

    def disconnected(self):
        # Stop cleanup thread
        if self.cleanup_thread is not None:
            self.cleanup_thread.cancel()

        # Leave the parties
        for party in self.scrims:
            if party.guid is not None and party.joined:
                party.leave()

    def _generate_name(self):
        name = "Scrim-{0}".format(self.scrim_count)
        self.scrim_count += 1

        return name

    def _guid_exists(self, guid):
        for jid in self.xmpp.plugin["xep_0045"].getJoinedRooms():
            if jid_user(jid) == guid:
                return True

        return False

    def _name_exists(self, name):
        for _name in self.scrims.keys():
            if _name.lower() == name:
                return True

        return False

    def _get_party_id(self, identifier):
        identifier = identifier.lower()

        # Look for party by name or guid
        for name, party in self.scrims.items():
            if name.lower() == identifier:
                # Found party by name
                return name
            if party.guid == identifier:
                # Found party by guid
                return name

        # Look for party in all parties
        for jid in self.xmpp.plugin["xep_0045"].getJoinedRooms():
            if jid_user(jid) == identifier:
                # The party exists, but it is not managed by this plugin.
                return False

        # The party does not exist
        return None

    def _handle_args_party(self, cmdtype, args, target, room):
        # Check the arguments
        if cmdtype == CommandType.PM:
            if len(args) < 1:
                self.xmpp.send_message(cmdtype, target, "Missing target party.")
                return False, None

            party = self.get_party(args[0])
        else:
            # This is a party
            party = self.get_party(room)

        # Check values given
        if party is None:
            self.xmpp.send_message(cmdtype, target, "No such party.")
        elif party is False:
            self.xmpp.send_message(cmdtype, target, "Error: The party exists, but it is not managed by the scrim plugin.")
        else:
            return True, party
        return False, None

    def _handle_args_party_user(self, cmdtype, args, target, room):
        # Check the arguments
        if cmdtype == CommandType.PM:
            if len(args) < 2:
                self.xmpp.send_message(cmdtype, target, "Missing target party and/or user.")
                return False, None, None

            target_user = self.cache.get_guid(args[1])
            party = self.get_party(args[0])
        else:
            # This is a party
            if len(args) < 1:
                self.xmpp.send_message(cmdtype, target, "Missing target user.")
                return False, None, None

            target_user = self.cache.get_guid(args[0])
            party = self.get_party(room)

        # Check values given
        if target_user is None:
            self.xmpp.send_message(cmdtype, target, "No such user.")
        elif party is None:
            self.xmpp.send_message(cmdtype, target, "No such party.")
        elif party is False:
            self.xmpp.send_message(cmdtype, target, "Error: The party exists, but it is not managed by the scrim plugin.")
        else:
            return True, target_user, party
        return False, None, None

    def _handle_args_party_server(self, cmdtype, args, target, room):
        # Check the arguments
        if cmdtype == CommandType.PM:
            if len(args) < 2:
                self.xmpp.send_message(cmdtype, target, "Missing target party and/or server.")
                return False, None, None

            server = self.api.wrapper(self.api.server_by_name, args[1])
            party = self.get_party(args[0])
        else:
            # This is a party
            if len(args) < 1:
                self.xmpp.send_message(cmdtype, target, "Missing target server.")
                return False, None, None

            server = self.api.wrapper(self.api.server_by_name, args[0])
            party = self.get_party(room)

        # Check values given
        if server is False:
            self.xmpp.send_message(cmdtype, target, "Error: Failed to load server list.")
        elif server is None:
            self.xmpp.send_message(cmdtype, target, "No such server.")
        elif party is None:
            self.xmpp.send_message(cmdtype, target, "No such party.")
        elif party is False:
            self.xmpp.send_message(cmdtype, target, "Error: The party exists, but it is not managed by the scrim plugin.")
        else:
            return True, server, party
        return False, None, None

    def create_party(self, name=None):
        # Generate the guid (and name, if needed)
        guid = Party.generate_guid()
        if name is None:
            name = self._generate_name()

        # Check if the party already exists
        assert not self._guid_exists(guid)
        if self._name_exists(name):
            return False

        # Create the party
        party = Party(self.xmpp, self.config, self.cache, self.api)
        party.create(guid)

        # Add the party to the list
        self.scrims[name] = party

        return name

    def join_party(self, guid, name=None):
        # Generate the name, if needed
        if name is None:
            name = self._generate_name()

        # Check if the party already exists
        if self._guid_exists(guid) or self._name_exists(name):
            return False

        # Join the party
        party = Party(self.xmpp, self.config, self.cache, self.api)
        party.join(guid)

        # Add the party to the list
        self.scrims[name] = party

    def get_party(self, identifier):
        # Get the party's guid
        name = self._get_party_id(identifier)

        if not name:
            return name

        return self.scrims[name]

    def leave_party(self, identifier):
        # Get the party's guid
        name = self._get_party_id(identifier)

        # Leave the party and delete it
        self.scrims[name].leave()
        del self.scrims[name]

    def cleanup(self):
        time_check = time.time() - self.config.plugins.scrim.cleanup_period

        # Check for empty parties
        targets = [k for k, v in self.scrims.items() if len(v.players) == 0 and v.create_time < time_check]

        if len(targets) > 0:
            # Purge all empty parties
            logger.info("Purging {0} empty parties.".format(len(targets)))
            for name in targets:
                self.leave_party(name)

        # Reschedule task
        self.cleanup_thread = threading.Timer(self.config.plugins.scrim.cleanup_period, self.cleanup)
        self.cleanup_thread.start()

    def party_list(self, cmdtype, cmdname, args, target, user, room):
        if len(self.scrims) > 0:
            self.xmpp.send_message(cmdtype, target, "Current parties: {0}".format(", ".join(self.scrims.keys())))
        else:
            self.xmpp.send_message(cmdtype, target, "There are no active parties.")

    def party_create(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        if len(args) > 0:
            name = args[0]
        else:
            name = None

        # Create a party
        party_name = self.create_party(name)
        if not party_name:
            # Party already exists
            self.xmpp.send_message(cmdtype, target, "Error: Party already exists!")
        else:
            # Party created
            self.xmpp.send_message(cmdtype, target, "Created new party '{0}'. Inviting you to it...".format(party_name))
            # Invite the user
            self.get_party(party_name).invite(user)

    def party_leave(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        result = self._handle_args_party(cmdtype, args, target, room)

        if result[0]:
            party = result[1]

            if cmdtype == CommandType.PM:
                self.xmpp.send_message(cmdtype, target, "Leaving the party.")
            else:
                self.xmpp.send_message(cmdtype, target, "Leaving the party, have a nice day.")

            self.leave_party(party.guid)

    def party_invite(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        result = self._handle_args_party_user(cmdtype, args, target, room)

        if result[0]:
            target_user, party = result[1:]

            # Check party state
            if party.state == DeploymentState.DEPLOYED:
                self.xmpp.send_message(cmdtype, target, "Players cannot be invited after the party has been deployed.")
            else:
                if party.state != DeploymentState.IDLE:
                    self.xmpp.send_message(cmdtype, target, "Warning: Party is currently matchmaking.")

                # Send an invite to the target
                party.invite(target_user)
                if cmdtype == CommandType.PM:
                    self.xmpp.send_message(cmdtype, target, "Invited {0} to the party.".format(self.cache.get_callsign(target_user)))

    def party_kick(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        result = self._handle_args_party_user(cmdtype, args, target, room)

        if result[0]:
            target_user, party = result[1:]

            # Check if we are kicking ourselves
            if target_user == self.api.guid:
                self.xmpp.send_message(cmdtype, target, "Refusing to kick myself.")
            # Check if the user is in the party
            elif target_user not in party.players:
                self.xmpp.send_message(cmdtype, target, "{0} is not in the party.".format(self.cache.get_callsign(target_user)))
            else:
                # Kick the player from the party
                party.kick(target_user)
                if cmdtype == CommandType.PM:
                    self.xmpp.send_message(cmdtype, target, "{0} has been kicked from the party.".format(self.cache.get_callsign(target_user)))

    def party_deploy(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        result = self._handle_args_party_server(cmdtype, args, target, room)

        if result[0]:
            server, party = result[1:]

            # Check that there are users to deploy
            if len(party.players) < 1:
                self.xmpp.send_message(cmdtype, target, "Error: There are no users in the party to deploy.")
            elif len(party.players) > server["MaxUsers"]:
                self.xmpp.send_message(cmdtype, target, "Error: The party is too large to fit on the server.")
            else:
                # Check for possible issues with the reservation
                # Server full
                user_count = len(server["Users"])
                if user_count - len(party.players) >= server["MaxUsers"]:
                    self.xmpp.send_message(cmdtype, target, "Warning: Server is full ({0}/{1}) - reservation may fail!".format(user_count, server["MaxUsers"]))

                # Notify deployment
                if cmdtype == CommandType.PM:
                    self.xmpp.send_message(cmdtype, target, "Deploying to server... Deploying to server '{0}partycancel {1}' to abort.".format(self.config.bot.command_prefix, args[0]))

                # Place the reservation
                advertisement = self.api.wrapper(self.api.matchmaking_advertisement_post_server, server["GameVersion"], server["Region"], server["Guid"], self.api.guid, list(party.players))
                party.deploy(advertisement, self.config.plugins.scrim.poll_limit)

    def party_cancel(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        result = self._handle_args_party(cmdtype, args, target, room)

        if result[0]:
            if result[1].abort(CancelCode.LEADERCANCEL):
                if cmdtype == CommandType.PM:
                    self.xmpp.send_message(cmdtype, target, "Canceled party deployment.")
            else:
                self.xmpp.send_message(cmdtype, target, "Party is not deploying - nothing to cancel.")

    def party_transfer(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        result = self._handle_args_party_user(cmdtype, args, target, room)

        if result[0]:
            target_user, party = result[1:]

            # Check if the user is in the party
            if target_user not in party.players:
                self.xmpp.send_message(cmdtype, target, "{0} is not in the party.".format(self.cache.get_callsign(target_user)))
            else:
                if cmdtype == CommandType.PM:
                    self.xmpp.send_message(cmdtype, target, "Transfering control over to {0} and leaving the party.".format(self.cache.get_callsign(target_user)))
                else:
                    self.xmpp.send_message(cmdtype, target, "Transfering control over to {0}. Have a nice day.".format(self.cache.get_callsign(target_user)))

                party.set_leader(target_user)
                self.leave_party(party.guid)

plugin = ScrimPlugin