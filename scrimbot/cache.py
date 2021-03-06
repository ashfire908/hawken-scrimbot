# -*- coding: utf-8 -*-

import errno
import json
import logging
from scrimbot.util import create_committer

logger = logging.getLogger(__name__)

cache_flag, CacheList, CacheDict = create_committer(list, dict)


class Cache:
    def __init__(self, client, config, api):
        self.client = client
        self.config = config
        self.api = api
        self._cache = CacheDict()
        self._registered_cache = set()

        # Register settings
        self.config.register("cache.filename", "cache.json")
        self.config.register("cache.save_period", 60 * 30)
        self.config.register("cache.globals_period", 60 * 60 * 12)

        # Register core cache variables
        self.register("callsign")
        self.register("guid")
        self.register("globals")

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
            if name not in self:
                self[name] = CacheDict()

        for callsign in self["callsign"].values():
            if callsign.lower() in self["guid"]:
                del self["guid"][callsign.lower()]

    def _as_committable(self, obj):
        if isinstance(obj, dict):
            return CacheDict(obj)
        elif isinstance(obj, list):
            return CacheList(obj)
        else:
            return obj

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
                cache = json.load(cache_file, object_hook=self._as_committable)
            finally:
                cache_file.close()
        except IOError as e:
            if e.errno == errno.ENOENT:
                # File not found, soft error
                logger.warn("Could not find the cache file.")
                return None
            else:
                # Other error, fail
                logger.exception("Failed to read the cache file.")
                return False
        except ValueError:
            # Failed to parse and load JSON
            logger.exception("Failed to load the cache file.")
            return False

        self._cache.update(cache)
        cache_flag.commit()

        # Verify the new cache data
        self._verify_cache()

        return True

    def save(self):
        # Verify the cache
        self._verify_cache()

        # Check if there are any changes to commit
        if cache_flag.committed:
            return True

        logger.info("Saving cache.")

        # Serialize the cache
        try:
            output = json.dumps(self._cache)
        except ValueError:
            # Failed to serialize the cache
            logger.exception("Failed to serialize the cache.")
            return False

        # Write the cache to file
        try:
            with open(self.config.cache.filename, "w") as cache_file:
                cache_file.write(output)
        except IOError:
            # Error
            logger.exception("Failed to write the cache file.")
            return False

        cache_flag.commit()
        return True

    def register(self, name):
        self._registered_cache.add(name)

        if name not in self:
            self[name] = CacheDict()

        logger.debug("Registered cache: {0}".format(name))

    def unregister(self, name):
        # Since we wish to preserve the old cache, we need not do anything
        logger.debug("Unregistered cache: {0}".format(name))

    def globals_update(self):
        logger.info("Updating globals.")

        # Get the global item, update settings
        self["globals"].update(self.api.get_game_items("ff7aa68d-d450-44c3-86f0-a403e87b0f64"))

    def cache_save(self):
        # Save the cache
        self.save()
