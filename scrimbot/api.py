# -*- coding: utf-8 -*-

import hawkenapi
import hawkenapi.sleekxmpp
from scrimbot.util import CaseInsensitiveDict


region_names = CaseInsensitiveDict({
    "US-East": "US East",
    "US-West": "US West",
    "UK": "UK",
    "Japan": "Asia North",
    "Singapore": "Asia South",
    "Australia": "Oceania",
    "Comp-US-East": "Comp US East",
    "Comp-US-West": "Comp US West"
})

map_names = CaseInsensitiveDict({
    "VS-Alleys": "Uptown",
    "VS-Andromeda": "Prosk",
    "VS-Bunker": "Bunker",
    "VS-Facility": "Facility",
    "VS-LastEco": "Last Eco",
    "VS-Sahara": "Bazaar",
    "VS-Titan": "Origin",
    "VS-Valkirie": "Front Line",
    "VS-Wreckage": "Wreckage",
    "CO-Facility": "Co-Op Facility",
    "CO-Valkirie": "Co-Op Front Line"
})

gametype_names = CaseInsensitiveDict({
    "HawkenTDM": "Team Deathmatch",
    "HawkenDM": "Deathmatch",
    "HawkenSG": "Siege",
    "HawkenMA": "Missile Assault",
    "HawkenCoOp": "Co-Op Bot Destruction"
})


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
        self.config.register("api.advertisement.polling_limit.server", 15.0)
        self.config.register("api.advertisement.polling_limit.matchmaking", 300.0)

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
