# -*- coding: utf-8 -*-

import logging
import threading
from hawkenapi.sleekxmpp.party import CancelCode
from scrimbot.party import Party, DeploymentState
from scrimbot.plugins.base import BasePlugin, Command, CommandType

logger = logging.getLogger(__name__)


class ScrimPlugin(BasePlugin):
    def init_plugin(self):
        # Init party lists
        self.parties = {}
        self.aliases = {}

        self.config.register_config("plugins.scrim.cleanup_period", 60 * 15)
        self.config.register_config("plugins.scrim.poll_limit", 30)

        # Setup cleanup thread
        self.cleanup_thread = threading.Timer(self.config.plugins.scrim.cleanup_period, self.cleanup)

        # Register group
        self.register_group("party")

        # Register commands
        self.register_command(Command("partycreate", CommandType.PM, self.party_create, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("partylist", CommandType.PM, self.party_list, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("partyinvite", CommandType.PM, self.party_invite, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("partykick", CommandType.PM, self.party_kick, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("partydeploy", CommandType.PM, self.party_deploy, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("partycancel", CommandType.PM, self.party_cancel, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("partyleave", CommandType.PM, self.party_leave, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("partytransfer", CommandType.PM, self.party_transfer, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("pcreate", CommandType.PM, self.party_create, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("plist", CommandType.PM, self.party_list, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("pinvite", CommandType.PM, self.party_invite, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("pkick", CommandType.PM, self.party_kick, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("pdeploy", CommandType.PM, self.party_deploy, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("pcancel", CommandType.PM, self.party_cancel, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("pleave", CommandType.PM, self.party_leave, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("ptransfer", CommandType.PM, self.party_transfer, flags=["permsreq", "alias"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("invite", CommandType.PARTY, self.party_invite, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("kick", CommandType.PARTY, self.party_kick, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("deploy", CommandType.PARTY, self.party_deploy, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("cancel", CommandType.PARTY, self.party_cancel, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("leave", CommandType.PARTY, self.party_leave, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))
        self.register_command(Command("transfer", CommandType.PARTY, self.party_transfer, flags=["permsreq"], metadata={"permsreq": ["admin", "party"]}))

    def start_plugin(self):
        # Start cleanup thread
        self.cleanup_thread.start()

    def _create_party(self):
        return Party(self.xmpp, self.config, self.cache, self.api)

    def _get_party_id(self, identifier):
        # Look for the party by guid
        if identifier in self.parties.keys():
            return identifier

        # Look for the party by alias
        for alias, guid in self.aliases.items():
            if alias.lower() == identifier.lower():
                # Return the guid for the alias
                return guid

        return False

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
        elif party is False:
            self.xmpp.send_message(cmdtype, target, "No such party.")
        else:
            return True, target_user, party
        return False, None, None

    def get_party(self, identifier):
        # Get the party's guid
        guid = self._get_party_id(identifier)

        if not guid:
            return False

        return self.parties[guid]

    def add_party(self, party, aliases=[]):
        # Check if the party already exists
        if party.guid in self.parties.keys():
            raise ValueError("Party already exists.")

        # Add the party to the list
        self.parties[party.guid] = party

        # Add the party aliases
        for alias in aliases:
            self.add_alias(party.guid, alias)

    def remove_party(self, identifier):
        # Get the party's guid
        guid = self._get_party_id(identifier)

        if not guid:
            raise KeyError("No such party.")

        # Leave the party and delete it
        self.parties[guid].leave()
        del self.parties[guid]

        # Delete the party aliases
        alias_list = self.get_party_aliases(guid)
        for alias in alias_list:
            self.remove_alias(alias)

    def add_alias(self, party, alias):
        if alias in self.aliases:
            raise ValueError("Alias already exists.")

        self.aliases[alias] = party

    def remove_alias(self, alias):
        try:
            del self.aliases[alias]
        except KeyError:
            pass

    def get_party_aliases(self, party):
        return [k for k, v in self.aliases.items() if v == party]

    def create_party(self, guid, aliases=None):
        # Create the party
        party = self._create_party()
        party.create(guid)

        # Add the party to the list
        self.parties[guid] = party

        # Add the aliases
        if isinstance(aliases, str):
            self.add_alias(guid, aliases)
        elif aliases is not None:
            for alias in aliases:
                self.add_alias(guid, alias)

    def join_party(self, guid, aliases=[]):
        # Create the party
        party = self._create_party()
        party.join(guid)

        # Add the party to the list
        self.parties[guid] = party

        # Add the aliases
        for alias in aliases:
            self.add_alias(guid, alias)

    def cleanup(self):
        # Check for empty parties
        targets = [k for k, v in self.parties.items() if len(v.players) == 0]

        if len(targets) > 0:
            # Purge all empty parties
            logger.info("Purging {0} empty parties.".format(len(targets)))
            for party in targets:
                self.remove_party(party)
        # Reschedule task
        self.cleanup_thread = threading.Timer(self.config.plugins.scrim.cleanup_period, self.cleanup)
        self.cleanup_thread.start()

    def party_list(self, cmdtype, cmdname, args, target, user, room):
        # Build a list of the parties
        parties = []
        guids = []
        for alias, guid in self.aliases.items():
            parties.append(alias)
            guids.append(guid)

        for guid in self.parties.keys():
            if guid not in guids:
                parties.append(guid)

        if len(parties) > 0:
            self.xmpp.send_message(cmdtype, target, "Current parties: {0}".format(", ".join(parties)))
        else:
            self.xmpp.send_message(cmdtype, target, "There are no active parties.")

    def party_create(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        if len(args) > 0:
            alias = args[0]
        else:
            alias = None

        # Create a party
        party_guid = Party.generate_guid()
        self.create_party(party_guid, alias)

        # Message the user
        if alias is None:
            message = "Created new party '{0}'. Inviting you to it...".format(party_guid)
        else:
            message = "Created new party '{1}' ({0}). Inviting you to it...".format(party_guid, alias)

        self.xmpp.send_message(cmdtype, target, message)

        # Invite the user
        self.get_party(party_guid).invite(user)

    def party_leave(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        if cmdtype == CommandType.PM:
            if len(args) < 2:
                self.xmpp.send_message(cmdtype, target, "Missing target party.")
                return

            party = self.get_party(args[0])
        else:
            # This is a party
            party = self.get_party(room)

        # Check values given
        if party is False:
            self.xmpp.send_message(cmdtype, target, "No such party.")
        else:
            if cmdtype == CommandType.PM:
                self.xmpp.send_message(cmdtype, target, "Leaving the party.")
            else:
                self.xmpp.send_message(cmdtype, target, "Leaving the party, have a nice day.")

            self.remove_party(party.guid)

    def party_invite(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        result = self._handle_args_party_user(cmdtype, args, target, room)

        if not result[0]:
            return

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

        if not result[0]:
            return

        target_user, party = result[1:]

        # Check if the user is in the party
        if target_user not in party.players:
            self.xmpp.send_message(cmdtype, target, "{0} is not in the party.".format(self.cache.get_callsign(target_user)))
        else:
            # Kick the player from the party
            party.kick(target_user)
            if cmdtype == CommandType.PM:
                self.xmpp.send_message(cmdtype, target, "{0} has been kicked from the party.".format(self.cache.get_callsign(target_user)))

    def party_deploy(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        if cmdtype == CommandType.PM:
            if len(args) < 2:
                self.xmpp.send_message(cmdtype, target, "Missing target party and/or server name.")
                return

            server_name = args[1]
            party = self.get_party(args[0])
        else:
            # This is a party
            if len(args) < 1:
                self.xmpp.send_message(cmdtype, target, "Missing target server name.")
                return

            server_name = args[0]
            party = self.get_party(room)

        # Check values given
        if party is False:
            self.xmpp.send_message(cmdtype, target, "No such party.")
        else:
            server = self.api.wrapper(self.api.server_by_name, server_name)
            if server is False:
                self.xmpp.send_message(cmdtype, target, "Error: Failed to load server list.")
            elif server is None:
                self.xmpp.send_message(cmdtype, target, "No such server.")
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
        if cmdtype == CommandType.PM:
            if len(args) < 2:
                self.xmpp.send_message(cmdtype, target, "Missing target party.")
                return

            party = self.get_party(args[0])
        else:
            # This is a party
            party = self.get_party(room)

        # Check values given
        if party is False:
            self.xmpp.send_message(cmdtype, target, "No such party.")
        else:
            result = party.abort(CancelCode.LEADERCANCEL)

            if result:
                self.xmpp.send_message(cmdtype, target, "Canceled party deployment.")
            else:
                self.xmpp.send_message(cmdtype, target, "Party is not deploying - nothing to cancel.")

    def party_transfer(self, cmdtype, cmdname, args, target, user, room):
        # Check the arguments
        result = self._handle_args_party_user(cmdtype, args, target, room)

        if not result[0]:
            return

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
            self.remove_party(party.guid)

plugin = ScrimPlugin
