# -*- coding: utf-8 -*-

from abc import ABCMeta, abstractmethod
from scrimbot.util import enum, create_bitfield

CommandType = enum(ALL="all", PM="pm", PARTY="muc")
CommandFlags = create_bitfield("hidden", "safe", "permsreq", "alias")


def format_command_id(cmdtype, cmdname):
    return "{0}::{1}".format(cmdtype, cmdname.lower())


def parse_command_id(cmdid):
    return cmdid.split("::")


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
    def init_plugin(self):
        pass

    @abstractmethod
    def start_plugin(self):
        pass

    def register_command(self, handler):
        self.client.register_command(handler)

    def register_group(self, group):
        self.permissions.register_group(group)


class Command:
    def __init__(self, cmdname, cmdtype, handler, flags=None, metadata={}):
        self.cmdname = cmdname
        self.cmdtype = cmdtype
        self.id = format_command_id(cmdtype, cmdname)
        self.handler = handler

        self.flags = CommandFlags()
        if flags is not None:
            for flag in flags:
                setattr(self.flags.b, flag, 1)

        self.metadata = metadata

    def call(self, cmdname, cmdtype, args, target, user, room=None):
        self.handler(cmdname, cmdtype, args, target, user, room)
