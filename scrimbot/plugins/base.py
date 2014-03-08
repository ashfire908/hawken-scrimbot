# -*- coding: utf-8 -*-

import logging
import importlib
from abc import ABCMeta, abstractmethod
from scrimbot.command import Command

logger = logging.getLogger(__name__)


class BasePlugin(metaclass=ABCMeta):
    def __init__(self, client):
        self._client = client
        self._xmpp = client.xmpp
        self._config = client.config
        self._cache = client.cache
        self._permissions = client.permissions
        self._api = client.api
        self._plugins = client.plugins
        self._commands = client.commands
        self._parties = client.parties
        self._scheduler = client.scheduler
        self.registered = {"config": set(), "cache": set(), "groups": set(), "commands": {}, "tasks": set()}

    def _thread_name(self, name):
        return "{0}:{1}".format(self.name, name)

    @property
    @abstractmethod
    def name(self):
        pass

    @abstractmethod
    def enable(self):
        pass

    @abstractmethod
    def disable(self):
        pass

    @abstractmethod
    def connected(self):
        pass

    @abstractmethod
    def disconnected(self):
        pass

    def cleanup(self):
        # Cleanup all known registered items
        for path in self.registered["config"].copy():
            self.unregister_config(path)

        for name in self.registered["cache"].copy():
            self.unregister_cache(name)

        for group in self.registered["groups"].copy():
            self.unregister_group(group)

        for handler in self.registered["commands"].copy().values():
            self.unregister_command(handler.cmdtype, handler.cmdname)

        for task in self.registered["tasks"].copy():
            self.unregister_task(task)

    def register_config(self, path, default):
        self._config.register(path, default)
        self.registered["config"].add(path)

    def unregister_config(self, path):
        self._config.unregister(path)
        self.registered["config"].remove(path)

    def register_cache(self, name):
        self._cache.register(name)
        self.registered["cache"].add(name)

    def unregister_cache(self, name):
        self._cache.unregister(name)
        self.registered["cache"].remove(name)

    def register_group(self, group):
        self._permissions.register_group(group)
        self.registered["groups"].add(group)

    def unregister_group(self, group):
        self._permissions.unregister_group(group)
        self.registered["groups"].remove(group)

    def register_command(self, cmdtype, cmdname, handler, **kwargs):
        command_handler = Command(self, cmdtype, cmdname, handler, **kwargs)

        if command_handler.id in self.registered["commands"]:
            raise ValueError("Handler {0} already registered".format(command_handler.id))
        else:
            # Record the handler with the plugin
            self.registered["commands"][command_handler.id] = command_handler

            # Register command with the command handler
            self._commands.register(command_handler)

    def unregister_command(self, cmdtype, cmdname):
        # Get the command
        cmdid = Command.format_id(cmdtype, cmdname)
        command_handler = self.registered["commands"][cmdid]

        # Remove the command
        self._commands.unregister(command_handler)
        del self.registered["commands"][cmdid]

    def register_task(self, name, seconds, callback, **kwargs):
        self._scheduler.add(self._thread_name(name), seconds, callback, **kwargs)
        self.registered["tasks"].add(name)

    def unregister_task(self, name):
        self._scheduler.remove(self._thread_name(name))
        self.registered["tasks"].remove(name)


class PluginManager:
    def __init__(self, client):
        self.client = client

        self.active = {}
        self.blacklist = {"base", }

    def load(self, name):
        # Check if the plugin is blacklisted
        if name in self.blacklist:
            return None

        # Check if the plugin is already loaded
        if name in self.active:
            return None

        # Load the module
        target = "scrimbot.plugins.{0}".format(name)
        try:
            module = importlib.import_module(target)
        except:
            logger.exception("Failed to load plugin: {0} - Error while importing.".format(name))
            return False

        # Init the plugin
        try:
            plugin = module.plugin(self.client)
        except AttributeError:
            logger.error("Failed to load plugin: {0} - Plugin does not have a defined main class.".format(name))
            return False

        if plugin.name != name:
            logger.warning("Path for plugin {0} does not match it's name ({1}).".format(name, plugin.name))

        # Enable the plugin
        self.active[plugin.name] = plugin
        try:
            self.active[plugin.name].enable()

            if self.client.connected:
                self.active[plugin.name].connected()
        except:
            logger.exception("Failed to load plugin: {0} - Error while enabling plugin.".format(name))

            # Attempt to unload the plugin
            try:
                try:
                    self.active[plugin.name].disable()
                finally:
                    self.active[plugin.name].cleanup()
            except:
                # Welp.
                logger.exception("Failed to unload plugin after failed load!")
            finally:
                # Remove the plugin from the active list
                # Not that this will do much in the case of an error...
                del self.active[plugin.name]

            return False

        # Plugin loaded
        logger.info("Loaded plugin: {0}".format(plugin.name))

        return True

    def unload(self, name):
        # Check if the plugin is loaded
        if not name in self.active:
            return None

        # Disable plugin and remove
        error = False
        try:
            if self.client.connected:
                self.active[name].disconnected()
        except:
            logger.exception("Failed to unload plugin: {0} - Error while signaling a disconnect.".format(name))
            error = True
        finally:
            try:
                try:
                    self.active[name].disable()
                finally:
                    self.active[name].cleanup()
            except:
                logger.exception("Failed to unload plugin: {0} - Error while disabling plugin.".format(name))
                error = True
            finally:
                del self.active[name]

        if error:
            return False

        # Plugin unloaded
        logger.info("Unloaded plugin: {0}".format(name))

        return True

    def connected(self):
        for plugin in self.active.values():
            plugin.connected()

    def disconnected(self):
        for plugin in self.active.values():
            plugin.disconnected()
