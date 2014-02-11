# -*- coding: utf-8 -*-

import errno
import json
import logging
from scrimbot.util import DotDict

logger = logging.getLogger(__name__)


class Config:
    def __init__(self, filename):
        self.filename = filename
        self._config = DotDict()

    def __getitem__(self, key):
        return self._config[key]

    def __setitem__(self, key, value):
        self._config[key] = value

    def __contains__(self, item):
        return item in self._config

    def __getattr__(self, key):
        return self.__getitem__(key)

    def _load_config(self, data, path=None):
        if path is None:
            path = []

        # Merge and store config
        for k, v in data.items():
            if len(path) < 1:
                newpath = [k]
            else:
                newpath = path[:]
                newpath.append(k)
            if isinstance(v, dict):
                self._load_config(v, newpath)
            else:
                self._config[".".join(newpath)] = v

    def load(self):
        logger.info("Loading config.")

        # Read the config file
        try:
            config_file = open(self.filename)
            try:
                config = json.load(config_file)
            finally:
                config_file.close()
        except IOError as e:
            if e.errno == errno.ENOENT:
                # File not found, soft error
                logger.warn("Could not find config file.")
                return None
            else:
                # Other error, fail
                logger.exception("Failed to read config file!")
                return False
        except ValueError:
            # Failed to parse and load JSON
            logger.exception("Failed to load config file! (Corrupt data?)")
            return False

        # Load in the config
        self._load_config(config)

        return True

    def save(self):
        logger.info("Saving config.")

        # Serialize the config
        try:
            output = json.dumps(self._config, indent=2, sort_keys=True)
        except ValueError:
            # Failed to serialize the config to JSON
            logger.exception("Failed to serialize the config to JSON!")
            return False

        # Write the config to file
        try:
            with open(self.filename, "w") as config_file:
                config_file.write(output)
        except IOError:
            # Error
            logger.exception("Failed to write config file!")
            return False

        return True

    def register(self, path, value):
        try:
            if path not in self._config:
                self._config[path] = value
        except KeyError:
            self._config[path] = value

        logger.debug("Registered config: {0}".format(path))

    def unregister(self, path):
        # Since we wish to preserve the old config, we need not do anything
        logger.debug("Unregistered config: {0}".format(path))
