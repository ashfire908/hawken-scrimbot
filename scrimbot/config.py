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

        # Register core config
        self.register_config("bot.log_level", "INFO")
        self.register_config("bot.command_prefix", "!")
        self.register_config("bot.plugins", ["admin", "info"])

    def __getitem__(self, key):
        return self._config[key]

    def __setitem__(self, key, value):
        self._config[key] = value

    def __contains__(self, item):
        return item in self._config

    def __getattr__(self, key):
        return self.__getitem__(key)

    def _load_config(self, data, path=[]):
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
            config_file = open(self.filename, "r")
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
                logger.error("Failed to read config file: {0}".format(e))
                return False

        # Load in the config
        self._load_config(config)

        # Update the logging settings
        logging.getLogger().setLevel(self.bot.log_level)

        return True

    def save(self):
        logger.info("Saving config.")

        # Write the config to file
        try:
            config_file = open(self.filename, "w")
            try:
                json.dump(self._config, config_file, indent=2, sort_keys=True)
            finally:
                config_file.close()
        except IOError as e:
            # Error
            logger.error("Failed to write config file: {0}".format(e))
            return False

        return True

    def register_config(self, path, value):
        try:
            if path not in self._config:
                self._config[path] = value
        except KeyError:
            self._config[path] = value

    def unregister_config(self, path):
        # Since we wish to preserve the old config, we need not do anything
        pass
