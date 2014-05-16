# -*- coding: utf-8 -*-

import time
import logging
import threading
from hawkenapi.sleekxmpp.party import CancelCode
from scrimbot.cache import CacheDict
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin
from scrimbot.plugins.scrim.party import ScrimParty, DeploymentState
from scrimbot.reservations import ServerReservation, SynchronizedServerReservation
from scrimbot.util import jid_user, chunks

logger = logging.getLogger(__name__)


class ScrimPlugin(BasePlugin):
    @property
    def name(self):
        return "scrim"

    def enable(self):
        # Register config
        self.register_config("plugins.scrim.cleanup_period", 60 * 15)
        self.register_config("plugins.scrim.max_group_size", 6)

        # Register cache
        self.register_cache("scrims")

        # Register group
        self.register_group("scrim")

        # Register commands
        self.register_command(CommandType.PM, "list", self.party_list, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PM, "create", self.party_create, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PM, "join", self.party_join, flags=["permsreq"], permsreq=["admin", "scrim"])
        self.register_command(CommandType.PARTY, "invite", self.party_invite, flags=["permsreq", "partyfeat"], permsreq=["admin", "scrim"], partyfeat=["scrim"])
        self.register_command(CommandType.PARTY, "kick", self.party_kick, flags=["permsreq", "partyfeat"], permsreq=["admin", "scrim"], partyfeat=["scrim"])
        self.register_command(CommandType.PARTY, "deploy", self.party_deploy, flags=["permsreq", "partyfeat"], permsreq=["admin", "scrim"], partyfeat=["scrim"])
        self.register_command(CommandType.PARTY, "cancel", self.party_cancel, flags=["permsreq", "partyfeat"], permsreq=["admin", "scrim"], partyfeat=["scrim"])
        self.register_command(CommandType.PARTY, "leave", self.party_leave, flags=["permsreq", "partyfeat"], permsreq=["admin", "scrim"], partyfeat=["scrim"])
        self.register_command(CommandType.PARTY, "transfer", self.party_transfer, flags=["permsreq", "partyfeat"], permsreq=["admin", "scrim"], partyfeat=["scrim"])

        # Setup party tracking
        if "parties" not in self._cache["scrims"]:
            self.parties = CacheDict()

        if "count" not in self._cache["scrims"]:
            self.count = 1

    def disable(self):
        pass

    def connected(self):
        def rejoin(self, guid, name):
            party = self._parties.new(ScrimParty, guid, name)

            if not party.join():
                # Could not join
                logger.error("Failed to rejoin party {0}.".format(party.name or party.guid))
                del self._cache["scrims"]["parties"][guid]

            if len(party.players) < 1:
                # No one is in the party
                party.leave()
                logger.info("No one was in party {0} on rejoin; left party.".format(party.name or party.guid))
                del self._cache["scrims"]["parties"][guid]

        # Rejoin parties
        for guid, party in self._cache["scrims"]["parties"].items():
            if guid not in self._parties.active:
                threading.Thread(target=rejoin, args=[self, guid, party["name"]]).start()

        # Start cleanup thread
        self.register_task("cleanup_thread", self._config.plugins.scrim.cleanup_period, self.cleanup_parties, repeat=True)

    def disconnected(self):
        if "cleanup_thread" in self.registered["tasks"]:
            # Stop cleanup thread
            self.unregister_task("cleanup_thread")

    @property
    def parties(self):
        return self._cache["scrims"]["parties"]

    @parties.setter
    def parties(self, value):
        self._cache["scrims"]["parties"] = value

    @property
    def count(self):
        return self._cache["scrims"]["count"]

    @count.setter
    def count(self, value):
        self._cache["scrims"]["count"] = value

    def _generate_name(self):
        name = "Scrim-{0}".format(self.count)
        self.count += 1

        return name

    def _guid_exists(self, guid):
        for jid in self._parties.joined_rooms:
            if jid_user(jid) == guid:
                return True

        return False

    def _name_exists(self, name):
        name = name.lower()
        for party in self.parties.values():
            if party["name"].lower() == name:
                return True

        return False

    def check_party(self, party):
        if "scrim" not in party.features:
            return False
        else:
            return True

    def get_party_guid(self, identifier):
        identifier = identifier.lower()

        # Look for party by name or guid
        for guid, party in self.parties.items():
            if guid == identifier:
                # Found party by guid
                return guid
            if party["name"].lower() == identifier:
                # Found party by name
                return guid

        # The party does not exist
        return None

    def get_party(self, guid):
        try:
            party = self._parties.active[guid]
        except KeyError:
            return None
        else:
            if not self.check_party(party):
                return False
            else:
                return party

    def create_party(self, name):
        # Generate the guid (and name, if needed)
        guid = self._parties.generate_guid()

        # Check if the party already exists
        assert not self._guid_exists(guid)
        if self._name_exists(name):
            return None

        # Create the party
        party = self._parties.new(ScrimParty, guid, name)
        if party.create():
            # Add the party to the list
            self.parties[guid] = {"name": name}

            return party
        else:
            return False

    def leave_party(self, guid):
        try:
            # Get the party
            party = self._parties.active[guid]

            # Check if this is our party
            if self.check_party(party):
                # Leave the party
                party.leave()
        except KeyError:
            pass

        try:
            # Purge the party from the list
            del self.parties[guid]
        except KeyError:
            pass

    def cleanup_parties(self):
        time_check = time.time() - self._config.plugins.scrim.cleanup_period

        # Check for parties to cleanup
        targets = []
        for guid in self.parties:
            try:
                party = self._parties.active[guid]
            except KeyError:
                # Party does not actually exist, purge it
                targets.append(guid)
            else:
                if len(party.players) == 0 and party.join_time < time_check:
                    # Party is empty, purge it
                    targets.append(guid)

        if len(targets) > 0:
            # Purge all targeted parties
            logger.debug("Purging {0} empty parties.".format(len(targets)))
            for guid in targets:
                self.leave_party(guid)

    def party_list(self, cmdtype, cmdname, args, target, user, party):
        if len(self.parties) > 0:
            self._xmpp.send_message(cmdtype, target, "Current scrims: {0}".format(", ".join([v["name"] for v in self.parties.values()])))
        else:
            self._xmpp.send_message(cmdtype, target, "There are no active scrims.")

    def party_create(self, cmdtype, cmdname, args, target, user, party):
        # Check the arguments
        if len(args) > 0:
            name = args[0]
        else:
            name = self._generate_name()

        # Create a party
        party = self.create_party(name)
        if party is None:
            # Party already exists
            self._xmpp.send_message(cmdtype, target, "Error: Party already exists.")
        elif party is False:
            # Party already exists
            self._xmpp.send_message(cmdtype, target, "Error: Failed to create party.")
        else:
            # Party created
            self._xmpp.send_message(cmdtype, target, "Created new party '{0}'. Inviting you to it...".format(party.name))

            # Invite the user
            party.invite(user)

    def party_join(self, cmdtype, cmdname, args, target, user, party):
        # Check the arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing target scrim.")
        else:
            # Get the party
            party = self.get_party_guid(args[0])
            if party:
                party = self.get_party(party)

            # Check if the party exists
            if not party:
                self._xmpp.send_message(cmdtype, target, "Error: Party does not exist.")
            # Check the party state
            elif party.state == DeploymentState.DEPLOYED:
                self._xmpp.send_message(cmdtype, target, "Error: Party has already been deployed.")
            else:
                # Invite the user
                party.invite(user)

    def party_invite(self, cmdtype, cmdname, args, target, user, party):
        # Check the arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing target user.")
        else:
            target_user = self._cache.get_guid(args[0])

            # Check if the user exists
            if target_user is None:
                self._xmpp.send_message(cmdtype, target, "Error: No such user.")
            # Check the party state
            elif party.state == DeploymentState.DEPLOYED:
                self._xmpp.send_message(cmdtype, target, "Error: Players cannot be invited after the scrim has been deployed.")
            # Check if the user is in the party
            elif target_user in party.players:
                self._xmpp.send_message(cmdtype, target, "{0} is already in the party.".format(args[0]))
            else:
                if party.state != DeploymentState.IDLE:
                    self._xmpp.send_message(cmdtype, target, "Warning: Party is currently matchmaking.")

                # Send an invite to the target
                party.invite(target_user)

    def party_kick(self, cmdtype, cmdname, args, target, user, party):
        # Check the arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing target user.")
        else:
            target_user = self._cache.get_guid(args[0])

            # Check if the user exists
            if target_user is None:
                self._xmpp.send_message(cmdtype, target, "Error: No such user.")
            # Check if we are the leader
            elif not party.is_leader:
                self._xmpp.send_message(cmdtype, target, "Error: I am not the leader of the party.")
            # Check if we are kicking ourselves
            elif target_user == self._api.guid:
                self._xmpp.send_message(cmdtype, target, "Error: Refusing to kick myself.")
            # Check if the user is in the party
            elif target_user not in party.players:
                self._xmpp.send_message(cmdtype, target, "{0} is not in the party.".format(self._cache.get_callsign(target_user)))
            else:
                # Kick the player from the party
                party.kick(target_user)

    def party_deploy(self, cmdtype, cmdname, args, target, user, party):
        # Check the arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing target server.")
        # Check if we are the leader
        elif not party.is_leader:
            self._xmpp.send_message(cmdtype, target, "Error: I am not the leader of the party.")
        else:
            servers = self._api.get_server_by_name(args[0])

            # Check the given server
            if servers is False:
                self._xmpp.send_message(cmdtype, target, "Error: Failed to load server list.")
            elif len(servers) < 1:
                self._xmpp.send_message(cmdtype, target, "No such server.")
            elif len(servers) > 1:
                self._xmpp.send_message(cmdtype, target, "Error: Server name is ambiguous.")
            # Check how many users are being deployed
            elif len(party.players) < 1:
                self._xmpp.send_message(cmdtype, target, "Error: There are no users in the party to deploy.")
            elif len(party.players) > servers[0]["MaxUsers"]:
                self._xmpp.send_message(cmdtype, target, "Error: The party is too large to fit on the server.")
            else:
                if len(party.players) > self._config.plugins.scrim.max_group_size:
                    # Create main reservation
                    reservation = SynchronizedServerReservation(self._config, self._cache, self._api, servers[0])

                    # Split party into groups
                    groups = chunks(list(party.players), self._config.plugins.scrim.max_group_size)

                    # Add each group to the reservation
                    for group in groups:
                        reservation.add(group, None)
                else:
                    # Setup the reservation
                    reservation = ServerReservation(self._config, self._cache, self._api, servers[0], list(party.players), party=None)

                # Check for issues
                critical, issues = reservation.check()

                # Display issues
                for issue in issues:
                    self._xmpp.send_message(cmdtype, target, issue)

                if critical:
                    return

                # Place the reservation
                reservation.reserve()

                try:
                    # Deploy the party
                    party.deploy(reservation)
                except ValueError:
                    # Cancel the reservation
                    reservation.cancel()

    def party_cancel(self, cmdtype, cmdname, args, target, user, party):
        # Check if we are the leader
        if not party.is_leader:
            self._xmpp.send_message(cmdtype, target, "Error: I am not the leader of the party.")
        # Abort the deployment
        elif not party.abort(CancelCode.leader_action):
            # Could not abort
            self._xmpp.send_message(cmdtype, target, "Party is not deploying - nothing to cancel.")

    def party_leave(self, cmdtype, cmdname, args, target, user, party):
        self._xmpp.send_message(cmdtype, target, "Leaving the party, have a nice day.")

        party.abort(CancelCode.leader_change)
        self.leave_party(party.guid)

    def party_transfer(self, cmdtype, cmdname, args, target, user, party):
        # Check the arguments
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Missing target user.")
        else:
            target_user = self._cache.get_guid(args[0])

            # Check if the user exists
            if target_user is None:
                self._xmpp.send_message(cmdtype, target, "Error: No such user.")
            # Check if the user is in the party
            elif target_user not in party.players:
                self._xmpp.send_message(cmdtype, target, "{0} is not in the party.".format(args[0]))
            # Check if we are the leader
            elif not party.is_leader:
                self._xmpp.send_message(cmdtype, target, "Error: I am not the leader of the party.")
            else:
                self._xmpp.send_message(cmdtype, target, "Transfering control over to {0}. Have a nice day.".format(self._cache.get_callsign(target_user)))

                party.set_leader(target_user)
                self.leave_party(party.guid)
