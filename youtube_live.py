#!/usr/bin/env python3
"""YouTube Live Monitor for Universal Devices IoX."""

import threading
import time
from datetime import datetime, timezone

import udi_interface
from youtube_monitor import check_stream
from youtube_oauth import YouTubeOAuth, install_oauth_log_filter

LOGGER = udi_interface.LOGGER

controller = None
youtube_oauth = None


class YouTubeController(udi_interface.Node):
    id = "youtubectrl"

    drivers = [
        {"driver": "ST", "value": 0, "uom": 25},
        {"driver": "GV1", "value": 0, "uom": 25},
        {"driver": "GV2", "value": 0, "uom": 25},
        {"driver": "GV3", "value": -1, "uom": 56},
    ]

    def __init__(self, polyglot):
        super().__init__(
            polyglot, "controller", "controller", "YouTube Live Monitor"
        )
        self.last_check = 0
        self.checking = False
        self.lock = threading.Lock()
        self.scheduled_start = None
        self.scheduled_id = None
        self.zero_reported = False

    def start(self):
        self.setDriver("ST", 0, report=True, force=True)
        self.setDriver("GV1", 0, report=True, force=True)
        self.setDriver("GV2", 0, report=True, force=True)
        self.setDriver("GV3", -1, report=True, force=True)
        self.check_now()

    def check_now(self, command=None):
        with self.lock:
            if self.checking:
                return
            self.checking = True

        threading.Thread(
            target=self._check_worker,
            daemon=True,
        ).start()

    def _check_worker(self):
        try:
            token = youtube_oauth.getAccessToken()
            if not token:
                raise RuntimeError("YouTube authentication required")

            result = check_stream(access_token=token)

            receiving = 2 if result["receiving"] else 1

            broadcast = {
                "offline": 1,
                "scheduled": 2,
                "live": 3,
            }.get(result.get("broadcast"), 0)

            next_start = result.get("next_start")
            next_id = result.get("next_id")
            now = datetime.now(timezone.utc)
            upcoming = datetime.fromisoformat(next_start) if next_start else None

            schedules = result.get("upcoming_schedules", {})
            upcoming_ids = set(result.get("upcoming_ids", []))
            active_ids = set(result.get("active_ids", []))

            with self.lock:
                current = self.scheduled_start
                current_id = self.scheduled_id

                if current_id is None:
                    current = upcoming
                    current_id = next_id
                    self.scheduled_start = current
                    self.scheduled_id = current_id
                    self.zero_reported = False

                elif current_id in schedules:
                    current = datetime.fromisoformat(
                        schedules[current_id].replace("Z", "+00:00")
                    )
                    self.scheduled_start = current

                elif current_id in active_ids:
                    # The broadcast is now active. Preserve its
                    # scheduled start until zero has been reported.
                    pass

                elif (
                    current is not None
                    and abs((current - now).total_seconds()) <= 60
                ):
                    # Allow a brief transition between upcoming
                    # and active without skipping countdown zero.
                    pass

                elif current_id not in active_ids:
                    # If the scheduled start has passed, report
                    # zero once before advancing to another event.
                    if current is not None and current <= now:
                        # Preserve the existing zero_reported flag.
                        # The countdown logic below handles advancing.
                        pass
                    else:
                        # Disappeared before its scheduled start:
                        # treat as canceled.
                        current = upcoming
                        current_id = next_id
                        self.scheduled_start = current
                        self.scheduled_id = current_id
                        self.zero_reported = False

                if current is None:
                    minutes = -1
                else:
                    seconds = (current - now).total_seconds()

                    if seconds <= -60 and self.zero_reported:
                        current = upcoming
                        self.scheduled_start = upcoming
                        self.scheduled_id = next_id
                        self.zero_reported = False
                        minutes = (
                            max(0, int((current - now).total_seconds() / 60))
                            if current else -1
                        )

                    else:
                        minutes = max(0, int((seconds + 29.999) / 60))

                    if minutes == 0:
                        self.zero_reported = True

            self.setDriver("ST", receiving, uom=25)
            self.setDriver("GV1", broadcast, uom=25)
            self.setDriver("GV2", 2, uom=25)
            self.setDriver("GV3", minutes, uom=56)

            LOGGER.info("YouTube status: %s", result)

        except Exception:
            LOGGER.exception("YouTube status check failed")
            self.setDriver("GV2", 1, uom=25)

        finally:
            with self.lock:
                self.last_check = time.monotonic()
                self.checking = False


    def poll(self):
        now = datetime.now(timezone.utc)

        with self.lock:
            scheduled = self.scheduled_start
            elapsed = time.monotonic() - self.last_check

        interval = 60

        if scheduled is not None:
            seconds = (scheduled - now).total_seconds()

            if -60 <= seconds <= 300:
                interval = 10

        if elapsed >= interval:
            self.check_now()

    def query(self, command=None):
        self.reportDrivers()

    commands = {
        "QUERY": query,
        "CHECK": check_now,
    }


def poll_handler(poll_type):
    if poll_type == "shortPoll" and controller is not None:
        controller.poll()


def stop_handler():
    LOGGER.info("YouTube Live Monitor stopping")
    if youtube_oauth is not None:
        youtube_oauth.shutdown()
    polyglot.stop()


if __name__ == "__main__":
    try:
        polyglot = udi_interface.Interface([])
        polyglot.start("0.1.1")

        polyglot.subscribe(polyglot.POLL, poll_handler)
        polyglot.subscribe(polyglot.STOP, stop_handler)

        install_oauth_log_filter()
        youtube_oauth = YouTubeOAuth(polyglot)

        polyglot.subscribe(
            polyglot.CUSTOMNS, youtube_oauth.customNsHandler
        )
        polyglot.subscribe(
            polyglot.OAUTH, youtube_oauth.oauthHandler
        )

        polyglot.ready()
        polyglot.updateProfile()

        controller = YouTubeController(polyglot)
        polyglot.addNode(controller)
        controller.start()

        polyglot.runForever()

    except (KeyboardInterrupt, SystemExit):
        pass

    except Exception:
        LOGGER.exception("Unhandled YouTube Live Monitor exception")
