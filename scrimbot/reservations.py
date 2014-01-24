# -*- coding: utf-8 -*-

import time
import math
import logging
import threading
from abc import ABCMeta, abstractmethod
import hawkenapi.exceptions
from scrimbot.util import enum

logger = logging.getLogger(__name__)

ReservationResult = enum(READY=0, CANCELED=1, TIMEOUT=2, NOTFOUND=3, ERROR=4)


class NoSuchServer(Exception):
    pass


def created(f):
    def create_required(self, *args, **kwargs):
        if not self.created:
            raise ValueError("Reservation has not been created yet")

        return f(self, *args, **kwargs)

    return create_required


def notcreated(f):
    def notcreate_required(self, *args, **kwargs):
        if self.created:
            raise ValueError("Reservation has already been created")

        return f(self, *args, **kwargs)

    return notcreate_required


class BaseReservation(metaclass=ABCMeta):
    def __init__(self, config, cache, api):
        self._config = config
        self._cache = cache
        self._api = api

        self.guid = None
        self.advertisement = None
        self.result = None

        self._poll_lock = threading.RLock()
        self._poll_thread = None

        self._canceled = threading.Event()
        self._deleted = threading.Event()
        self._finished = threading.Event()

    def _poll(self, limit):
        try:
            # Start polling the advertisement
            poll = True
            start = time.time()
            while (time.time() - start) < limit:
                with self._poll_lock:
                    # Check if the advertisement has been canceled
                    if self._canceled.is_set():
                        logger.debug("Reservation {0} has been canceled. Stopped polling.".format(self.guid))
                        self.result = ReservationResult.CANCELED
                        poll = False
                        break
                    else:
                        # Check the advertisement
                        try:
                            self.advertisement = self._api.get_advertisement(self.guid)
                        except hawkenapi.exceptions.RetryLimitExceeded:
                            # Continue polling the advertisement
                            pass
                        else:
                            # Check if the advertisement still exists
                            if self.advertisement is None:
                                # Couldn't find reservation
                                logger.warning("Reservation {0} cannot be found! Stopped polling.".format(self.guid))
                                self.result = ReservationResult.NOTFOUND
                                poll = False
                                break
                            # Check if the reservation has been completed
                            elif self.advertisement["ReadyToDeliver"]:
                                # Ready
                                self.result = ReservationResult.READY
                                poll = False
                                break

                if poll:
                    # Wait a bit before checking again
                    time.sleep(self._poll_rate())

            # Check for a timeout
            if poll:
                self.result = ReservationResult.TIMEOUT
                self.delete()
            # Check for any errors
            elif self.result != ReservationResult.READY:
                self.delete()
        except:
            self.result = ReservationResult.ERROR
            self.delete()
            raise
        finally:
            self._finished.set()

    @abstractmethod
    def _poll_rate(self):
        pass

    @abstractmethod
    def _reserve(self):
        pass

    @abstractmethod
    def check(self):
        pass

    @notcreated
    def reserve(self, limit=None):
        if limit is None:
            limit = self._config.api.advertisement.polling_limit

        # Place the reservation
        self.guid = self._reserve()

        # Setup the polling thread
        self._poll_thread = threading.Thread(target=self._poll, args=(limit, ))

    @created
    def poll(self, limit=None):
        if not self._finished.is_set():
            # Check if the polling has started, and if not start it
            if not self._poll_thread.is_alive():
                with self._poll_lock:
                    if not self._finished.is_set() and not self._poll_thread.is_alive():
                        self._poll_thread.start()

            if limit is not None:
                self._finished.wait(limit)
            else:
                self._finished.wait()

        return self.result

    @created
    def cancel(self):
        with self._poll_lock:
            # Mark as canceled
            self._canceled.set()

            # Delete advertisement
            self.delete()

    @created
    def delete(self):
        with self._poll_lock:
            if self.guid is not None and not self._deleted.is_set():
                self._api.delete_advertisement(self.guid)
                self._deleted.set()

    @property
    def created(self):
        return self.guid is not None

    @property
    def finished(self):
        return self._finished.is_set()

    @property
    def deleted(self):
        return self._deleted.is_set()


class ServerReservation(BaseReservation):
    def __init__(self, config, cache, api, server, users, party=None):
        super().__init__(config, cache, api)

        self.users = users
        self.party = party

        # Validate the number of users
        if len(self.users) < 1:
            raise ValueError("No users were given")

        # Grab the server info
        self.server = self._api.get_server(server)
        if self.server is None:
            raise NoSuchServer("The specified server does not exist")

    def _poll_rate(self):
        return self._config.api.advertisement.polling_rate.server

    def _reserve(self):
        return self._api.post_server_advertisement(self.server["GameVersion"], self.server["Region"], self.server["Guid"], self.users, self.party)

    def check(self):
        critical = False
        issues = []

        # Check for critical issues
        # Server is too small to hold the number of users
        if self.server["MaxUsers"] < len(self.users):
            issues.append("Error: There are too many users to fit into the server ({0}/{1}).".format(len(self.users), self.server["MaxUsers"]))
            critical = True
        # Check for warnings
        else:
            # Server is full
            if self.server["MaxUsers"] < (len(self.server["Users"]) + len(self.users)):
                issues.append("Warning: Server is full ({0}/{1}) - reservation may fail!".format(len(self.server["Users"]), self.server["MaxUsers"]))
            # Server outside the users's average rank
            server_level = int(self.server["DeveloperData"]["AveragePilotLevel"])
            if server_level > 0:
                try:
                    data = self._api.get_user_stats(self.users)
                except hawkenapi.exceptions.InvalidBatch:
                    # No use crying over spilled milk - just ignore the check
                    pass
                else:
                    pilot_level = int(math.fsum([int(user["Progress.Pilot.Level"]) for user in data]) / len(self.users))
                    if pilot_level - int(self._cache["globals"]["MMPilotLevelRange"]) > server_level:
                        issues.append("Warning: Server outside your skill level ({0} vs {1}) - reservation may fail!".format(pilot_level, server_level))

        return critical, issues


class MatchmakingReservation(BaseReservation):
    def __init__(self, config, cache, api, gameversion, region, users, gametype=None, party=None):
        super().__init__(config, cache, api)

        self.gameversion = gameversion
        self.region = region
        self.users = users
        self.gametype = gametype
        self.party = party

        # Validate the number of users
        if len(self.users) < 1:
            raise ValueError("No users were given")

    def _poll_rate(self):
        return self._config.api.advertisement.polling_rate.matchmaking

    def _reserve(self):
        return self._api.post_matchmaking_advertisement(self.gameversion, self.region, self.gametype, self.users, self.party)

    def check(self):
        critical = False
        issues = []

        # TODO: Perform checks

        return critical, issues
