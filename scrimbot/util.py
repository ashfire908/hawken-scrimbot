# -*- coding: utf-8 -*-

import math
from copy import deepcopy
import ctypes
import logging.config


def enum(**enums):
    return type('Enum', (), enums)


def chunks(l, n):
    return [l[i:i + n] for i in range(0, len(l), n)]


def create_bitfield(*fields):
    field_list = []
    for field in fields:
        field_list.append((field, ctypes.c_uint8, 1))

    class Bits(ctypes.LittleEndianStructure):
        _fields_ = field_list

    class Data:
        def __init__(self, fields):
            for field in fields:
                setattr(self, field, None)

    class Flags(ctypes.Union):
        _fields_ = [("b", Bits), ("asbyte", ctypes.c_uint8)]

        def __init__(self, bits=0):
            super().__init__()

            if isinstance(bits, int):
                # Assume bits passed as int
                self.asbyte = bits
            else:
                # Assume bits passed as list of bit names
                for bit in list(bits):
                    setattr(self.b, bit, 1)

            # Create data storage
            self.data = Data(fields)

    return Flags


def jid_user(jid):
    return jid.split("@", 1)[0]


def format_dhms(seconds):
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    output = []
    if days != 0:
        if days > 1:
            output.append("{} days".format(days))
        else:
            output.append("{} day".format(days))
    if hours != 0:
        if hours > 1:
            output.append("{} hours".format(hours))
        else:
            output.append("{} hour".format(hours))
    if minutes != 0:
        if minutes > 1:
            output.append("{} minutes".format(minutes))
        else:
            output.append("{} minute".format(minutes))
    if seconds != 0:
        if seconds > 1:
            output.append("{} seconds".format(seconds))
        else:
            output.append("{} second".format(seconds))
    return " ".join(output)


class DotDict(dict):
    def __init__(self, value=None):
        if value is None:
            pass
        elif isinstance(value, dict):
            for key in value:
                self.__setitem__(key, value[key])
        else:
            raise TypeError("Expected dict")

    def __setitem__(self, key, value):
        if "." in key:
            top, rest = key.split(".", 1)
            target = self.setdefault(top, DotDict())
            if not isinstance(target, DotDict):
                raise KeyError("Cannot set '{0}' in '{1}' ({2})".format(rest, top, repr(target)))
            target[rest] = value
        else:
            if isinstance(value, dict) and not isinstance(value, DotDict):
                value = DotDict(value)
            dict.__setitem__(self, key, value)

    def __getitem__(self, key):
        if "." not in key:
            return dict.__getitem__(self, key)
        top, rest = key.split(".", 1)
        target = dict.__getitem__(self, top)
        if not isinstance(target, DotDict):
            raise KeyError("Cannot get '{0}' in '{1}' ({2})".format(rest, top, repr(target)))
        return target[rest]

    def __contains__(self, key):
        if "." not in key:
            return dict.__contains__(self, key)
        top, rest = key.split(".", 1)
        target = dict.__getitem__(self, top)
        if not isinstance(target, DotDict):
            return False
        return rest in target

    def setdefault(self, key, default):
        if key not in self:
            self[key] = default
        return self[key]

    __setattr__ = __setitem__
    __getattr__ = __getitem__


def create_committer(*types, methods=None):
    if methods is None:
        changer_methods = {"__setitem__", "__setslice__", "__delitem__", "update", "append", "extend", "add", "insert", "pop", "popitem", "remove", "setdefault", "__iadd__"}
    else:
        changer_methods = methods

    def callback_getter(obj):
        def callback(name):
            obj.committed = False
        return callback

    def proxy_decorator(func, callback):
        def wrapper(*args, **kw):
            callback(func.__name__)
            return func(*args, **kw)
        wrapper.__name__ = func.__name__
        return wrapper

    def proxy_class_factory(cls, obj):
        new_dct = cls.__dict__.copy()
        for key, value in new_dct.items():
            if key in changer_methods:
                new_dct[key] = proxy_decorator(value, callback_getter(obj))
        return type("proxy_" + cls.__name__, (cls, ), new_dct)

    class Flag(object):
        def __init__(self):
            self.commit()

        def commit(self):
            self.committed = True

    flag = Flag()
    yield flag

    for t in types:
        yield proxy_class_factory(t, flag)


def default_logging():
    config = {
        "formatters": {
            "console": {
                "format": "%(levelname)-8s %(name)s %(message)s"
            },
            "file": {
                "format": "%(asctime)-15s %(levelname)-8s %(name)s %(message)s"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "console",
                "level": "ERROR"
            },
            "file": {
                "class": "logging.handlers.TimedRotatingFileHandler",
                "formatter": "file",
                "level": "INFO",
                "filename": "logs/scrimbot.log",
                "when": "midnight"
            }
        }
    }

    return config


def setup_logging(config):
    # Add base config
    config["root"] = {
        "handlers": ["console", "file"],
        "level": "NOTSET"
    }
    config["version"] = 1
    config["disable_existing_loggers"] = False

    # Load config
    logging.config.dictConfig(config)


def stat_analysis(data, stat):
    # Get the list of stats
    stats = {"list": [item[stat] for item in data if stat in item and item[stat] is not None]}

    if len(stats["list"]) > 0:
        # Calculate min/max/mean
        stats["max"] = max(stats["list"])
        stats["min"] = min(stats["list"])
        stats["mean"] = math.fsum(stats["list"]) / len(stats["list"])

        # Calculate standard deviation
        stddev_list = [(item - stats["mean"]) ** 2 for item in stats["list"]]
        if len(stddev_list) > 0:
            stats["stddev"] = math.sqrt(math.fsum(stddev_list) / len(stddev_list))

        return stats
    else:
        # Can't pull stats out of thin air
        return False


def calc_fitness(globals_info, player, server):
    # Get shared values
    weight_rank = int(globals_info["MMGlickoWeight"])
    weight_level = int(globals_info["MMPilotLevelWeight"])
    min_matches = int(globals_info["NoobHandicapCutoff"])
    avg_level = int(server["DeveloperData"]["AveragePilotLevel"])

    # Get threshold
    threshold = {}
    threshold["rank"] = weight_rank * int(globals_info["MMSkillRange"])
    threshold["level"] = weight_level * int(globals_info["MMPilotLevelRange"])
    threshold["sum"] = sum(threshold.values())

    # Calculate handicap
    matches = min(min_matches, abs(min(0, int(player["GameMode.All.TotalMatches"]) - min_matches)))
    handicap = matches * int(globals_info["NoobHandicapSize"])

    # Get adjusted player rating
    rank = player["MatchMaking.Rating"] - handicap

    # Calculate score
    score = {}
    score["rank"] = (server["ServerRanking"] - rank) * weight_rank
    score["level"] = (avg_level - int(player["Progress.Pilot.Level"])) * weight_level
    score["sum"] = sum(score.values())

    # Calculate health
    health = int((abs(score["sum"]) * 100) / threshold["sum"])

    # Calculate rating
    if avg_level <= 0 or server["ServerRanking"] <= 0:
        rating = 3
    elif abs(score["sum"]) > threshold["sum"]:
        rating = 0
    elif health > int(globals_info["BrowserMedium"]):
        rating = 1
    elif health > int(globals_info["BrowserGood"]):
        rating = 2
    else:
        rating = 3

    details = {
        "threshold": threshold,
        "handicap": handicap,
        "score": score,
        "health": health,
        "rating": rating
    }

    return score["sum"], health, rating, details


def gen_composite_player(players, fields):
    composite = {}

    for field in fields:
        composite[field] = math.fsum([user[field] for user in players]) / len(players)

    return composite


def get_bracket(number, bracket):
    x = math.floor(number / bracket)
    low = x * bracket
    high = (x + 1) * bracket

    return low, high
