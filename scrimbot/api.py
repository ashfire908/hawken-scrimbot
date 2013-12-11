# -*- coding: utf-8 -*-
# Hawken Scrim Bot

import hawkenapi.client


class ApiClient(hawkenapi.client.Client):
    def __init__(self, config):
        self.config = config

        # Register config values
        self.config.register_config("api.username", None)
        self.config.register_config("api.password", None)
        self.config.register_config("api.stack", None)
        self.config.register_config("api.scheme", None)
        self.config.register_config("api.retry_delay", 1)
        self.config.register_config("api.retry_max", 5)
        self.config.register_config("api.advertisement.polling_rate", 0.5)
        self.config.register_config("api.advertisement.polling_limit", 30.0)

    def setup(self):
        # Get the parameters and init the underlying client
        kwargs = {}
        if self.config.api.stack is not None:
            kwargs["stack"] = self.config.api.stack
        if self.config.api.scheme is not None:
            kwargs["scheme"] = self.config.api.scheme

        super().__init__(**kwargs)

        # Configure the automatic authentication and get the user details
        self.auto_auth(self.config.api.username, self.config.api.password)
        self.guid = self.wrapper(self.user_account, self.config.api.username)["Guid"]
        self.callsign = self.wrapper(self.user_callsign, self.guid)

    def wrapper(self, endpoint, *args, **kwargs):
        return hawkenapi.client.retry_wrapper(endpoint, self.config.api.retry_max, self.config.api.retry_delay, *args, **kwargs)