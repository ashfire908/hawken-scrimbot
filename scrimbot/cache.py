# -*- coding: utf-8 -*-

import errno
import json
import logging

logger = logging.getLogger(__name__)


class Cache:
    def __init__(self, client, config, api):
        self.client = client
        self.config = config
        self.api = api
        self._cache = {}
        self._registered_cache = set()

        # Register settings
        self.config.register_config("cache.filename", "cache.json")
        self.config.register_config("cache.save_period", 60 * 30)
        self.config.register_config("cache.globals_period", 60 * 60 * 12)

        # Register core cache variables
        self.register_cache("callsign")
        self.register_cache("guid")
        self.register_cache("globals")

    def __getitem__(self, key):
        return self._cache[key]

    def __setitem__(self, key, value):
        self._cache[key] = value

    def __contains__(self, item):
        return item in self._cache

    def __delitem__(self, key):
        del self._cache[key]

    def _verify_cache(self):
        for name in self._registered_cache:
            if name not in self._cache:
                self._cache[name] = {}

    def setup(self):
        # Do an initial globals update
        self.globals_update()

        # Setup update threads
        self.client.scheduler.add("globals_update", self.config.cache.globals_period, self.globals_update, repeat=True)
        self.client.scheduler.add("cache_save", self.config.cache.save_period, self.cache_save, repeat=True)

    def load(self):
        logger.info("Loading cache.")

        # Read the cache file
        try:
            cache_file = open(self.config.cache.filename)
            try:
                cache = json.load(cache_file)
            finally:
                cache_file.close()
        except IOError as e:
            if e.errno == errno.ENOENT:
                # File not found, soft error
                logger.warn("Could not find cache file.")
                return None
            else:
                # Other error, fail
                logger.error("Failed to read cache file: {0}".format(e))
                return False

        self._cache = cache

        # Verify the new cache data
        self._verify_cache()

        return True

    def save(self):
        logger.info("Saving cache.")

        # Write the cache to file
        try:
            cache_file = open(self.config.cache.filename, "w")
            try:
                json.dump(self._cache, cache_file)
            finally:
                cache_file.close()
        except IOError as e:
            # Error
            logger.error("Failed to write cache file: {0}".format(e))
            return False

        return True

    def register_cache(self, name):
        self._registered_cache.add(name)

        if name not in self._cache:
            self._cache[name] = {}

    def cache_save(self):
        # Save the cache
        self.save()

    def get_callsign(self, guid):
        # Check cache
        if guid in self["callsign"]:
            return self["callsign"][guid]

        # Fetch callsign
        callsign = self.api.wrapper(self.api.user_callsign, guid)

        if callsign is not None:
            # Cache the callsign
            self["callsign"][guid] = callsign

            # Purge any temp cache we had for the GUID
            try:
                del self["guid"][callsign.lower()]
            except KeyError:
                pass
        else:
            logger.warning("No callsign listed for {0}.".format(guid))

        return callsign

    def get_guid(self, callsign):
        # Case insensitive search
        callsign = callsign.lower()

        # Check GUID cache
        if callsign in self["guid"]:
            return self["guid"][callsign]

        # Check callsign cache
        for guid, cs in self["callsign"].items():
            if cs.lower() == callsign:
                return guid

        # Fetch GUID
        guid = self.api.wrapper(self.api.user_guid, callsign)

        if guid is not None:
            # Cache the GUID
            self["guid"][callsign] = guid

        return guid

    def globals_update(self):
        logger.info("Updating globals.")

        # Get the global item, update settings
        self["globals"] = self.api.wrapper(self.api.game_items, "ff7aa68d-d450-44c3-86f0-a403e87b0f64")
