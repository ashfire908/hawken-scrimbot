# -*- coding: utf-8 -*-

from abc import ABCMeta, abstractmethod
from scrimbot.util import enum, create_bitfield

CommandType = enum(ALL="all", PM="pm", PARTY="muc")
CommandFlags = create_bitfield("hidden", "safe", "permsreq", "alias")


class BasePlugin(metaclass=ABCMeta):
    def __init__(self, client, xmpp, config, cache, permissions, api):
        self.client = client
        self.xmpp = xmpp
        self.config = config
        self.cache = cache
        self.permissions = permissions
        self.api = api
        self.registered_commands = {}

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

    def register_config(self, path, default):
        self.config.register_config(path, default)

    def unregister_config(self, path):
        self.config.unregister_config(path)

    def register_group(self, group):
        self.permissions.register_group(group)

    def unregister_group(self, group):
        self.permissions.unregister_group(group)

    def register_command(self, cmdtype, cmdname, handler, **kwargs):
        command_handler = Command(self, cmdtype, cmdname, handler, **kwargs)

        # Register command
        if command_handler.id in self.registered_commands:
            raise ValueError("Handler {0} already registered.".format(command_handler.id))
        else:
            self.registered_commands[command_handler.id] = command_handler
            self.client.register_command(command_handler)

    def unregister_command(self, cmdtype, cmdname):
        del self.registered_commands[Command.format_id(cmdtype, cmdname)]
        self.client.unregister_command(Command.format_id(cmdtype, cmdname), Command.format_fullid(self.name, cmdtype, cmdname))

    def register_task(self, name, seconds, callback, **kwargs):
        self.client.scheduler.add(self._thread_name(name), seconds, callback, **kwargs)

    def unregister_task(self, name):
        self.client.scheduler.remove(self._thread_name(name))


class Command:
    def __init__(self, plugin, cmdtype, cmdname, handler, flags=None, metadata=None):
        self.plugin = plugin
        self.cmdtype = cmdtype
        self.cmdname = cmdname
        self.id = Command.format_id(cmdtype, cmdname)
        self.fullid = Command.format_fullid(plugin.name, cmdtype, cmdname)
        self.handler = handler

        self.flags = CommandFlags()
        if flags is not None:
            for flag in flags:
                setattr(self.flags.b, flag, 1)

        if metadata is None:
            self.metadata = {}
        else:
            self.metadata = metadata

        self._verify_flags()

    def _verify_flags(self):
        # Safe and Permission Required conflict
        if self.flags.b.safe and self.flags.b.permsreq:
            raise ValueError("Flags 'safe' and 'permsreq' cannot be enabled at once.")

    def call(self, cmdtype, cmdname, args, target, user, room=None):
        self.handler(cmdtype, cmdname, args, target, user, room)

    @staticmethod
    def format_id(cmdtype, cmdname):
        return "{0}::{1}".format(cmdtype, cmdname.lower())

    @staticmethod
    def format_fullid(plugin, cmdtype, cmdname):
        return "{0}:{1}::{2}".format(plugin, cmdtype, cmdname.lower())

    @staticmethod
    def parse_id(cmdid):
        return cmdid.split("::", 1)

    @staticmethod
    def parse_fullid(fullid):
        plugin, cmdid = fullid.split(":", 1)
        cmdtype, cmdname = Command.parse_id(cmdid)
        return plugin, cmdtype, cmdname
