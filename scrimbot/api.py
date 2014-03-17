# -*- coding: utf-8 -*-

import hawkenapi.client
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

region_map = {
    "US-East": ("USEast", "USE"),
    "US-West": ("USWest", "USW"),
    "UK": ("UK", ),
    "Japan": ("AsiaNorth", "AN"),
    "Singapore": ("AsiaSouth", "AS"),
    "Australia": ("Oceania", ),
    "Comp-US-East": ("CompUSEast", "CompUSE"),
    "Comp-US-West": ("CompUSWest", "CompUSW")
}

map_map = {
    "VS-Alleys": ("Uptown", "Alleys"),
    "VS-Andromeda": ("Prosk", "Andromeda"),
    "VS-Bunker": ("Bunker", ),
    "VS-Facility": ("Facility", ),
    "VS-LastEco": ("LastEco", ),
    "VS-Sahara": ("Bazaar", "Sahara"),
    "VS-Titan": ("Origin", "Titan"),
    "VS-Valkirie": ("FrontLine", "Valkirie"),
    "VS-Wreckage": ("Wreckage", ),
    "CO-Facility": ("Co-OpFacility", "CoOpFacility"),
    "CO-Valkirie": ("Co-OpFrontLine", "CoOpFrontLine", "Co-OpValkirie", "CoOpValkirie")
}

gametype_map = {
    "HawkenTDM": ("TeamDeathmatch", "TDM"),
    "HawkenDM": ("Deathmatch", "DM"),
    "HawkenSG": ("Siege", "SG"),
    "HawkenMA": ("MissileAssault", "MA"),
    "HawkenCoOp": ("Co-Op", "CoOp", "COBD")
}


def get_mapping(target, mapping):
    target = target.lower()

    for k in mapping.keys():
        if k.lower() == target:
            return k

    for k, v in mapping.items():
        for name in v:
            if name.lower() == target:
                return k

    return None


def get_region(name):
    return get_mapping(name, region_map)


def get_map(name):
    return get_mapping(name, map_map)


def get_gametype(name):
    return get_mapping(name, gametype_map)


class ApiClient(hawkenapi.client.Client):
    def __init__(self, config):
        self.config = config

        # Register config values
        self.config.register("api.username", None)
        self.config.register("api.password", None)
        self.config.register("api.host", None)
        self.config.register("api.scheme", None)
        self.config.register("api.retry_max", 2)
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
            kwargs["max_retries"] = self.config.api.retry_max

        super().__init__(**kwargs)

        # Authenticate to the API and grab the user's callsign
        self.login(self.config.api.username, self.config.api.password)
        self.callsign = self.get_user_callsign(self.guid)
