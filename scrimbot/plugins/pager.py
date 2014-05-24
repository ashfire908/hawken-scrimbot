# -*- coding: utf-8 -*-

import logging
import smtplib
import urllib.request
import urllib.parse
from email.mime.text import MIMEText
from scrimbot.command import CommandType
from scrimbot.plugins.base import BasePlugin

logger = logging.getLogger(__name__)


class PagerPlugin(BasePlugin):
    @property
    def name(self):
        return "pager"

    def enable(self):
        # Register config
        self.register_config("plugins.page.email_host", "localhost")
        self.register_config("plugins.page.email_from", "scrimbot@ashfire908.com")
        self.register_config("plugins.page.ashfire908", None)
        self.register_config("plugins.page.defter", None)

        # Register commands
        self.register_command(CommandType.PM, "page", self.page, hidden=True)

    def disable(self):
        pass

    def connected(self):
        pass

    def disconnected(self):
        pass

    def email_page(self, f, t, message):
        msg = MIMEText(message)
        msg["Subject"] = "Page from {0}".format(f)
        msg["From"] = self._config.plugins.page.email_from
        msg["To"] = t

        s = smtplib.SMTP(self._config.plugins.page.email_host)
        s.send_message(msg)
        s.quit()

    def hipchat_proxied(self, f, t, message):
        urllib.request.urlopen(t + urllib.parse.quote("Page from {0}: {1}".format(f, message))).close()

    def page(self, cmdtype, cmdname, args, target, user, party):
        # Check args
        if len(args) < 2:
            self._xmpp.send_message(cmdtype, target, "Missing page target.")
        else:
            msg_target = args[0].lower()
            message = " ".join(args[1:])
            f = self._cache.get_callsign(user) or user
            if msg_target == "ashfire908":
                if self._config.plugins.page.ashfire908 is None:
                    raise Exception("No page target for ashfire908")

                self.email_page(f, self._config.plugins.page.ashfire908, message)
            elif msg_target == "defter":
                if self._config.plugins.page.defter is None:
                    raise Exception("No page target for defter")

                self.hipchat_proxied(f, self._config.plugins.page.defter, message)
            else:
                self._xmpp.send_message(cmdtype, target, "Error: Unknown page target.")
                return

            logger.info("{0} has paged {1} with the message: {2}".format(f, msg_target, message))
            self._xmpp.send_message(cmdtype, target, "Paged {0}: {1}".format(msg_target, message))


plugin = PagerPlugin
