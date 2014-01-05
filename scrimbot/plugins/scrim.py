# -*- coding: utf-8 -*-

import time
import logging
from hawkenapi.sleekxmpp.party import CancelCode
from scrimbot.party import Party, DeploymentState
from scrimbot.plugins.base import BasePlugin, CommandType
from scrimbot.reservations import ServerReservation
from scrimbot.util import jid_user

logger = logging.getLogger(__name__)


class ScrimPlugin(BasePlugin):
    @property
    def name(self):
        return "scrim"

    def enable(self):
        # Register config
        self.register_config("plugins.scrim.cleanup_period", 60 * 15)
        self.register_config("plugins.scrim.polling_limit", 30)

        # Register group
        self.register_group("scrim")

        # Register commands
        self.register_command(CommandType.PM, "create", self.party_create, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PM, "list", self.party_list, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PM, "invite", self.party_invite, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PM, "kick", self.party_kick, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PM, "deploy", self.party_deploy, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PM, "cancel", self.party_cancel, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PM, "leave", self.party_leave, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PM, "transfer", self.party_transfer, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PARTY, "invite", self.party_invite, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PARTY, "kick", self.party_kick, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PARTY, "deploy", self.party_deploy, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PARTY, "cancel", self.party_cancel, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PARTY, "leave", self.party_leave, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PARTY, "transfer", self.party_transfer, flags=["permsreq"], permsreq=["admin", "scrim"])

        # Setup party tracking
        self.scrims = {}
        self.scrim_count = 1

    def disable(self):
        # Unregister config
        self.unregister_config("plugins.scrim.cleanup_period")
        self.unregister_config("plugins.scrim.polling_limit")

        # Unregister group
        self.unregister_group("scrim")

        # Unregister commands
        self.unregister_command(CommandType.PM, "create")
        self.unregister_command(CommandType.PM, "list")
        self.unregister_command(CommandType.PM, "invite")
        self.unregister_command(CommandType.PM, "kick")
        self.unregister_command(CommandType.PM, "deploy")
        self.unregister_command(CommandType.PM, "cancel")
        self.unregister_command(CommandType.PM, "leave")
        self.unregister_command(CommandType.PM, "transfer")
        self.unregister_command(CommandType.PARTY, "invite")
        self.unregister_command(CommandType.PARTY, "kick")
        self.unregister_command(CommandType.PARTY, "deploy")
        self.unregister_command(CommandType.PARTY, "cancel")
        self.unregister_command(CommandType.PARTY, "leave")
        self.unregister_command(CommandType.PARTY, "transfer")

    def connected(self):
        # Rejoin parties
        for party in self.scrims.values():
            if party.guid is not None:
                party.join(party.guid)
                party.messaage("Rejoined after getting disconnected, please restore leader status or tell me to leave.")

        # Start cleanup thread
        self.register_task("cleanup_thread", self.config.plugins.scrim.cleanup_period, self.cleanup, repeat=True)

    def disconnected(self):
        # Stop cleanup thread
        self.unregister_task("cleanup_thread")

    def _generate_name(self):
        name = "Scrim-{0}".format(self.scrim_count)
        self.scrim_count += 1

        return name

    def _guid_exists(self, guid):
        for jid in Party.get_joined_rooms(self.xmpp):
            if jid_user(jid) == guid:
                return True

        return False

    def _name_exists(self, name):
        for _name in self.scrims:
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
        party = Party(self.client, self.xmpp, self.config, self.cache, self.api)
        party.create(guid)

        # Add the party to the list
        self.scrims[name] = party

        return name

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

    def party_list(self, cmdtype, cmdname, args, target, user, room):
        if len(self.scrims) > 0:
            self.xmpp.send_message(cmdtype, target, "Current parties: {0}".format(", ".join(self.scrims)))
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
                self.xmpp.send_message(cmdtype, target, "Error: Players cannot be invited after the party has been deployed.")
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

            # Check if we are the leader
            if not party.is_leader():
                self.xmpp.send_message(cmdtype, target, "Error: I am not the leader of the party.")
            # Check if we are kicking ourselves
            elif target_user == self.api.guid:
                self.xmpp.send_message(cmdtype, target, "Error: Refusing to kick myself.")
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

            # Check if we are the leader
            if not party.is_leader():
                self.xmpp.send_message(cmdtype, target, "Error: I am not the leader of the party.")
            # Check that there are users to deploy
            elif len(party.players) < 1:
                self.xmpp.send_message(cmdtype, target, "Error: There are no users in the party to deploy.")
            elif len(party.players) > server["MaxUsers"]:
                self.xmpp.send_message(cmdtype, target, "Error: The party is too large to fit on the server.")
            else:
                # Setup the reservation
                reservation = ServerReservation(self.config, self.cache, self.api, server["Guid"], list(party.players), party=None)

                # Check for issues
                critical, issues = reservation.check()

                for issue in issues:
                    self.xmpp.send_message(cmdtype, target, issue)

                if critical:
                    return

                # Notify deployment
                if cmdtype == CommandType.PM:
                    self.xmpp.send_message(cmdtype, target, "Deploying to server... '{0}scrim cancel {1}' to abort.".format(self.config.bot.command_prefix, args[0]))

                # Place the reservation
                reservation.reserve(limit=self.config.plugins.scrim.polling_limit)

                try:
                    party.deploy(reservation)
                except ValueError:
                    reservation.cancel()

    def party_cancel(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        result = self._handle_args_party(cmdtype, args, target, room)

        if result[0]:
            party = result[1]

            # Check if we are the leader
            if not party.is_leader():
                self.xmpp.send_message(cmdtype, target, "Error: I am not the leader of the party.")
            elif party.abort(CancelCode.LEADERCANCEL):
                if cmdtype == CommandType.PM:
                    self.xmpp.send_message(cmdtype, target, "Canceled party deployment.")
            else:
                self.xmpp.send_message(cmdtype, target, "Party is not deploying - nothing to cancel.")

    def party_transfer(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        result = self._handle_args_party_user(cmdtype, args, target, room)

        if result[0]:
            target_user, party = result[1:]

            # Check if we are the leader
            if not party.is_leader():
                self.xmpp.send_message(cmdtype, target, "Error: I am not the leader of the party.")
            # Check if the user is in the party
            elif target_user not in party.players:
                self.xmpp.send_message(cmdtype, target, "{0} is not in the party.".format(self.cache.get_callsign(target_user)))
            else:
                if cmdtype == CommandType.PM:
                    self.xmpp.send_message(cmdtype, target, "Transfering control over to {0} and leaving the party.".format(self.cache.get_callsign(target_user)))
                else:
                    self.xmpp.send_message(cmdtype, target, "Transfering control over to {0}. Have a nice day.".format(self.cache.get_callsign(target_user)))

                party.set_leader(target_user)
                self.leave_party(party.guid)


plugin = ScrimPlugin
