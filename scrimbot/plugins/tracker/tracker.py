# -*- coding: utf-8 -*-

from contextlib import contextmanager
from datetime import datetime
from sqlalchemy import func, create_engine
from sqlalchemy.orm import sessionmaker
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin
from scrimbot.plugins.tracker.model import Player, User, LinkStatus


class TrackerPlugin(BasePlugin):
    @property
    def name(self):
        return "tracker"

    def enable(self):
        # Register config
        self.register_config("plugins.tracker.database_uri", None)

        # Register commands
        self.register_command(CommandType.PM, "optin", self.opt_in)
        self.register_command(CommandType.PM, "optout", self.opt_out)
        #self.register_command(CommandType.PM, "link", self.link)
        #self.register_command(CommandType.PM, "unlink", self.unlink)

        # Setup database connection
        if self._config.plugins.tracker.database_uri is None:
            raise ValueError("The database URI must be set")

        engine = create_engine(self._config.plugins.tracker.database_uri)
        self.session = sessionmaker(bind=engine)

    def disable(self):
        # Close database sessions
        self.session.close_all()

    def connected(self):
        pass

    def disconnected(self):
        pass

    @contextmanager
    def db_session(self):
        session = self.session()
        try:
            yield session
            session.commit()
        except:
            session.rollback()
            raise
        finally:
            session.close()

    def opt_in(self, cmdtype, cmdname, args, target, user, party):
        success = False
        with self.db_session() as session:
            player = session.query(Player).get(user)

            if player is None:
                self._xmpp.send_message(cmdtype, target, "The leaderboards tracker has not seen you yet. You will automatically be tracked by default the next time you are in a match.")
            elif not player.opt_out:
                self._xmpp.send_message(cmdtype, target, "You have already opted into the leaderboards.")
            else:
                player.opt_out = False
                session.add(player)
                success = True

        if success:
            self._xmpp.send_message(cmdtype, target, "You have successfully opted into the leaderboards.")

    def opt_out(self, cmdtype, cmdname, args, target, user, party):
        success = False
        with self.db_session() as session:
            player = session.query(Player).get(user)

            if player is None:
                date = datetime.now()

                player = Player()
                player.id = user
                player.first_seen = date
                player.last_seen = date
                player.opt_out = True
                session.add(player)

                success = True
            elif player.opt_out:
                self._xmpp.send_message(cmdtype, target, "You have already opted out of the leaderboards.")
            else:
                player.opt_out = True
                session.add(player)

                success = True

        if success:
            self._xmpp.send_message(cmdtype, target, "You have successfully opted out of the leaderboards.")

    def link(self, cmdtype, cmdname, args, target, user, party):
        # Check args
        if len(args) < 1:
            self._xmpp.send_message(cmdtype, target, "Error: You must specify the user you wish to link your Hawken account to.")
        elif args[0] == "":
            self._xmpp.send_message(cmdtype, target, "Error: The username cannot be blank.")
        else:
            check_user = False
            success = False
            with self.db_session() as session:
                player = session.query(Player).get(user)

                if player is None:
                    # No data
                    date = datetime.now()

                    player = Player()
                    player.id = user
                    player.first_seen = date
                    player.last_seen = date

                    check_user = True
                elif player.link_status == LinkStatus.none:
                    # No link
                    check_user = True
                elif player.link_status == LinkStatus.pending:
                    # Pending link
                    username = player.user.username
                    if username.lower() == args[0].lower():
                        self._xmpp.send_message(cmdtype, target, "You have already linked your Hawken account to {0} but the link has yet to be confirmed. To complete the process, please login to the leaderboards site and confirm the link.".format(username))
                    else:
                        self._xmpp.send_message(cmdtype, target, "Error: You already have a pending link to {0}. Please cancel the pending link before attempting to link to another user.".format(username))
                else:
                    # Confirmed link
                    username = player.user.username
                    if username.lower() == args[0].lower():
                        self._xmpp.send_message(cmdtype, target, "You have already linked your Hawken account to {0}!".format(username))
                    else:
                        self._xmpp.send_message(cmdtype, target, "Error: You have already linked your Hawken account to {0}! Please unlink from this user before attempting to link to another user.".format(username))

                if check_user:
                    user = session.query(User).filter(func.lower(User.username) == args[0].lower()).first()

                    if user is None:
                        # No user
                        self._xmpp.send_message(cmdtype, target, "Error: That user does not exist. You must first register on the leaderboards site.")
                    else:
                        # Link the account
                        player.link_status = LinkStatus.pending
                        player.link_user = user.id
                        session.add(player)

                        username = user.username
                        success = True

            if success:
                self._xmpp.send_message(cmdtype, target, "You have linked your Hawken account to {0}, but the link is pending confirmation. Please login to the leaderboards site and confirm the link.".format(username))

    def unlink(self, cmdtype, cmdname, args, target, user, party):
        success = True
        username = None
        with self.db_session() as session:
            player = session.query(Player).get(user)

            if player is None or player.link_status == LinkStatus.none:
                self._xmpp.send_message(cmdtype, target, "Your Hawken account is not linked to any user.")
            else:
                username = player.user.username

                # Unlink the player
                player.link_status = LinkStatus.none
                player.link_user = None

                success = True

        if success:
            self._xmpp.send_message(cmdtype, target, "You have unlinked your Hawken account from {0}.".format(username))
