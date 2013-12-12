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
        self._handler_mapping = {}

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

    def register_command(self, handler):
        self.client.register_command(handler)

    def unregister_command(self, handler_id):
        self.client.unregister_command(handler_id)


class Command:
    def __init__(self, cmdtype, cmdname, handler, flags=None, metadata={}):
        self.cmdtype = cmdtype
        self.cmdname = cmdname
        self.id = Command.format_id(cmdtype, cmdname)
        self.handler = handler

        self.flags = CommandFlags()
        if flags is not None:
            for flag in flags:
                setattr(self.flags.b, flag, 1)

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
    def parse_id(cmdid):
        return cmdid.split("::")
