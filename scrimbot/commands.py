# -*- coding: utf-8 -*-
# Commands


class RequiredPerm(object):
    """Command decorator for required permissions."""
    def __init__(self, permissions):
        self.permissions = permissions

    def __call__(self, function):
        if len(self.permissions) > 0:
            function._scrimcommand_required_perms = self.permissions
            return function
        else:
            return function


class HiddenCommand(object):
    """Command decorator for hidden command."""
    def __init__(self):
        pass

    def __call__(self, function):
        function._scrimcommand_hidden = True
        return function


class SafeCommand(object):
    """Command decorator for bypassing safety checks."""
    def __init__(self):
        pass

    def __call__(self, function):
        function._scrimcommand_safe = True
        return function
