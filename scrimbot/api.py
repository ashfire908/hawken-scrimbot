# -*- coding: utf-8 -*-

import hawkenapi.client
from hawkenapi.interface import Session
import hawkenapi.sleekxmpp
from scrimbot.util import CaseInsensitiveDict


region_names = CaseInsensitiveDict({
    "US-East": "US East",
    "US-West": "US West",
    "US-Central": "US Central",
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
    "HawkenCoOp": "Co-Op Bot Destruction",
    "HawkenBotsTDM": "Co-Op Team Deathmatch"
})

region_map = {
    "US-East": ("USEast", "USE"),
    "US-West": ("USWest", "USW"),
    "US-Central": ("USCentral", "USC"),
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
    "HawkenCoOp": ("Co-Op", "CoOp", "COBD"),
    "HawkenBotsTDM": ("CoOpTDM", "BotsTDM")
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
        self.config.register("api.session.host", None)
        self.config.register("api.session.scheme", None)
        self.config.register("api.session.max_retries", 2)
        self.config.register("api.session.timeout", 15)
        self.config.register("api.cache.prefix", "hawkenscrimbot")
        self.config.register("api.cache.mode", None)
        self.config.register("api.cache.params", {})
        self.config.register("api.advertisement.polling_rate.server", 0.5)
        self.config.register("api.advertisement.polling_rate.matchmaking", 1)
        self.config.register("api.advertisement.polling_limit.server", 15.0)
        self.config.register("api.advertisement.polling_limit.matchmaking", 300.0)

    def setup(self):
        # Init the underlying client
        super().__init__(Session(**self.config.api.session))

        # Setup caching
        if self.config.api.cache.mode == "redis":
            import hawkenapi.cache
            self.cache = hawkenapi.cache.RedisCache(self.config.api.cache.prefix, **self.config.api.cache.params)

        # Authenticate to the API and grab the user's callsign
        self.login(self.config.api.username, self.config.api.password)
        self.callsign = self.get_user_callsign(self.guid)
