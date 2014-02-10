# -*- coding: utf-8 -*-

import itertools
import time
import logging
import threading
import concurrent.futures
from abc import ABCMeta, abstractmethod
import hawkenapi.exceptions
from scrimbot.util import enum, gen_composite_player, calc_fitness

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

        self._exception = None

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
        except Exception as e:
            self.result = ReservationResult.ERROR
            self.delete()
            self._exception = e
        finally:
            self._finished.set()

    @abstractmethod
    def _poll_rate(self):
        pass

    @abstractmethod
    def _poll_limit(self):
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
            limit = self._poll_limit()

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

        # Raise the exception encountered during polling
        if self.result == ReservationResult.ERROR:
            raise self._exception

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

        if isinstance(server, str):
            # Grab the server info
            self.server = self._api.get_server(server)
            if self.server is None:
                raise NoSuchServer("The specified server does not exist")
        else:
            # Assume it's a server object
            self.server = server

    def _poll_rate(self):
        return self._config.api.advertisement.polling_rate.server

    def _poll_limit(self):
        return self._config.api.advertisement.polling_limit.server

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
                issues.append("Warning: Server does not have enough room for all players ({0}/{1}) - reservation may fail!".format(len(self.server["Users"]) + len(self.users), self.server["MaxUsers"]))
            # Server outside the users's fitness range
            if int(self.server["DeveloperData"]["AveragePilotLevel"]) > 0 and int(self.server["ServerRanking"]) > 0:
                try:
                    data = self._api.get_user_stats(self.users)
                except hawkenapi.exceptions.InvalidBatch:
                    # No use crying over spilled milk - just ignore the check
                    pass
                else:
                    composite = gen_composite_player(data, ("GameMode.All.TotalMatches", "MatchMaking.Rating", "Progress.Pilot.Level"))
                    score, health, rating, details = calc_fitness(self._cache["globals"], composite, self.server)
                    if rating == 0:
                        issues.append("Warning: Server outside player fitness range ({0}) - reservation may fail!".format(health))

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

    def _poll_limit(self):
        return self._config.api.advertisement.polling_limit.matchmaking

    def _reserve(self):
        return self._api.post_matchmaking_advertisement(self.gameversion, self.region, self.gametype, self.users, self.party)

    def check(self):
        critical = False
        issues = []

        # TODO: Perform checks

        return critical, issues


class SynchronizedReservation(metaclass=ABCMeta):
    def __init__(self):
        self.reservations = []

        self._created = threading.Event()

    def _add(self, reservation):
        if reservation in self.reservations:
            raise ValueError("Reservation already added")

        self.reservations.append(reservation)

    def _remove(self, reservation):
        self.reservations.remove(reservation)

    @abstractmethod
    def check(self):
        pass

    @notcreated
    def reserve(self, limit=None):
        # Mark as created
        self._created.set()

        exception = None

        # Setup a task pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.reservations)) as executor:
            # Submit the tasks
            reservations = {executor.submit(reservation.reserve, limit=limit): reservation for reservation in self.reservations}

            # Check the results as they come in
            for future in concurrent.futures.as_completed(reservations):
                try:
                    # Check the result
                    future.result()
                except Exception as e:
                    logger.exception("Exception while placing reservations.")

                    # If this is the first exception, save the exception and cancel the other reservations
                    if exception is None:
                        exception = e
                        self.delete()

        # Check if there was an exception
        if exception is not None:
            raise exception

    @created
    def poll(self, limit=None):
        abort = False
        exception = None
        return_code = ReservationResult.READY

        # Setup a task pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.reservations)) as executor:
            # Submit the tasks
            reservations = {executor.submit(reservation.poll, limit=limit): reservation for reservation in self.reservations}

            # Check the results as they come in
            for future in concurrent.futures.as_completed(reservations):
                # Check the result
                try:
                    code = future.result()
                except Exception as e:
                    logger.exception("Exception while polling reservations.")
                    # If this is the first exception, mark as aborted, save the exception and cancel the other reservations
                    if not abort:
                        abort = True
                        exception = e
                        self.cancel()

                # Check if we have aborted
                if not abort:
                    # Check if the reservation was not successful
                    if code != ReservationResult.READY:
                        abort = True
                        return_code = code
                        self.cancel()

        if exception is not None:
            raise exception

        return return_code

    @created
    def cancel(self):
        # Setup a task pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.reservations)) as executor:
            # Submit the tasks
            for reservation in self.reservations:
                executor.submit(reservation.cancel)

    @created
    def delete(self):
        # Setup a task pool
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.reservations)) as executor:
            # Submit the tasks
            for reservation in self.reservations:
                executor.submit(reservation.delete)

    @property
    def created(self):
        return self._created.is_set()

    @property
    def finished(self):
        finished = False

        for reservation in self.reservations:
            if not reservation.finished:
                return False
            finished = True

        return finished

    @property
    def deleted(self):
        deleted = False

        for reservation in self.reservations:
            if not reservation.deleted:
                return False
            deleted = True

        return deleted

    @property
    @abstractmethod
    def advertisement(self):
        pass


class SynchronizedServerReservation(SynchronizedReservation):
    def __init__(self, config, cache, api, server):
        super().__init__()

        self._config = config
        self._cache = cache
        self._api = api

        self.server = server
        self.user_groups = []

        if isinstance(server, str):
            # Grab the server info
            self.server = self._api.get_server(server)
            if self.server is None:
                raise NoSuchServer("The specified server does not exist")
        else:
            # Assume it's a server object
            self.server = server

    @notcreated
    def add(self, users, party=None):
        reservation = ServerReservation(self._config, self._cache, self._api, self.server, users, party)
        self._add(reservation)
        self.user_groups.append(users)

    @notcreated
    def remove(self, users, party):
        raise NotImplementedError("Removing user groups is not implemented")

    def check(self):
        critical = False
        issues = []

        user_count = sum([len(users) for users in self.user_groups])

        # Check for critical issues
        # Server is too small to hold the number of users
        if self.server["MaxUsers"] < user_count:
            issues.append("Error: There are too many users to fit into the server ({0}/{1}).".format(user_count, self.server["MaxUsers"]))
            critical = True
        # Check for warnings
        else:
            # Server is full
            if self.server["MaxUsers"] < (len(self.server["Users"]) + user_count):
                issues.append("Warning: Server does not have enough room for all players ({0}/{1}) - reservation may fail!".format(len(self.server["Users"]) + user_count, self.server["MaxUsers"]))

            # Load user data
            try:
                userdata = {user["Guid"]: user for user in self._api.get_user_stats(set(itertools.chain.from_iterable(self.user_groups)))}
            except hawkenapi.exceptions.InvalidBatch:
                # No use crying over spilled milk - just ignore the check
                pass
            else:
                data = []
                for group in self.user_groups:
                    data.append([userdata[user] for user in group])

                composites = [gen_composite_player(group, ("GameMode.All.TotalMatches", "MatchMaking.Rating", "Progress.Pilot.Level")) for group in data]

                # Server outside the group fitness level
                if int(self.server["DeveloperData"]["AveragePilotLevel"]) > 0 and int(self.server["ServerRanking"]) > 0:
                    for composite in composites:
                        score, health, rating, details = calc_fitness(self._cache["globals"], composite, self.server)
                        if rating == 0:
                            issues.append("Warning: Server outside a group's fitness range ({0}) - reservation may fail!".format(health))

        return critical, issues

    @property
    def advertisement(self):
        try:
            return self.reservations[0].advertisement
        except KeyError:
            return None
