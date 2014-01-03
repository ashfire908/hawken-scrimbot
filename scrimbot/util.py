# -*- coding: utf-8 -*-

import ctypes


def enum(**enums):
    return type('Enum', (), enums)


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


class CommittableDict(dict):
    def __init__(self, value=None):
        self._committed = True

        if value is None:
            pass
        elif isinstance(value, dict):
            for key in value:
                self.__setitem__(key, value[key])
        else:
            raise TypeError("Expected dict")

    @property
    def committed(self):
        if not self._committed:
            return False

        for subitem in self.values():
            if isinstance(subitem, CommittableDict) and not subitem.committed:
                return False

        return True

    def commit(self):
        self._committed = True

        for subitem in self.values():
            if isinstance(subitem, CommittableDict):
                subitem.commit()

    def _do_commit(method):
        def wrapper(self, *args, **kwargs):
            result = method(self, *args, **kwargs)
            self._committed = False
            return result
        return wrapper

    __delitem__ = _do_commit(dict.__delitem__)
    __setitem__ = _do_commit(dict.__setitem__)
    clear = _do_commit(dict.clear)
    pop = _do_commit(dict.pop)
    popitem = _do_commit(dict.popitem)
    setdefault = _do_commit(dict.setdefault)
    update = _do_commit(dict.update)
