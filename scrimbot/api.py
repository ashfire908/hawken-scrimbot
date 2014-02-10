# -*- coding: utf-8 -*-

import hawkenapi
import hawkenapi.sleekxmpp


class ApiClient(hawkenapi.Client):
    def __init__(self, config):
        self.config = config

        # Register config values
        self.config.register("api.username", None)
        self.config.register("api.password", None)
        self.config.register("api.host", None)
        self.config.register("api.scheme", None)
        self.config.register("api.retry_max", 5)
        self.config.register("api.retry_delay", 1)
        self.config.register("api.advertisement.polling_rate.server", 0.5)
        self.config.register("api.advertisement.polling_rate.matchmaking", 1)
        self.config.register("api.advertisement.polling_limit", 30.0)

    def setup(self):
        # Get the parameters and init the underlying client
        kwargs = {}
        if self.config.api.host is not None:
            kwargs["host"] = self.config.api.host
        if self.config.api.scheme is not None:
            kwargs["scheme"] = self.config.api.scheme
        if self.config.api.retry_max is not None:
            kwargs["retry_attempts"] = self.config.api.retry_max
        if self.config.api.retry_delay is not None:
            kwargs["retry_delay"] = self.config.api.retry_delay

        super().__init__(**kwargs)

        # Authenticate to the API and grab the user's callsign
        self.login(self.config.api.username, self.config.api.password)
        self.callsign = self.get_user_callsign(self.guid)
