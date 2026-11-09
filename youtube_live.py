#!/usr/bin/env python3
"""YouTube Live Monitor for Universal Devices IoX."""

import threading
from pathlib import Path
import time
import udi_interface

from youtube_monitor import check_stream

LOGGER = udi_interface.LOGGER

# Development only. Replace with plugin-private storage before deployment.
AUTH_DIRECTORY = Path(__file__).resolve().parent / "persist"

controller = None


class YouTubeController(udi_interface.Node):
    id = "youtubectrl"

    drivers = [
        {"driver": "ST", "value": 0, "uom": 25},
        {"driver": "GV1", "value": 0, "uom": 25},
        {"driver": "GV2", "value": 0, "uom": 25},
    ]

    def __init__(self, polyglot):
        super().__init__(
            polyglot, "controller", "controller", "YouTube Live Monitor"
        )
        self.last_check = 0
        self.checking = False
        self.lock = threading.Lock()

    def start(self):
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
            result = check_stream(AUTH_DIRECTORY)

            receiving = 1 if result["receiving"] else 0
            broadcast = {
                "offline": 0,
                "scheduled": 1,
                "live": 2,
            }.get(result.get("broadcast"), 0)

            self.setDriver("ST", receiving)
            self.setDriver("GV1", broadcast)
            self.setDriver("GV2", 1)

            LOGGER.info("YouTube status: %s", result)

        except Exception:
            LOGGER.exception("YouTube status check failed")
            self.setDriver("GV2", 0)

        finally:
            with self.lock:
                self.last_check = time.monotonic()
                self.checking = False

    def poll(self):
        if time.monotonic() - self.last_check >= 30:
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
    polyglot.stop()


if __name__ == "__main__":
    try:
        polyglot = udi_interface.Interface([])
        polyglot.start("0.1.0")

        polyglot.subscribe(udi_interface.POLL, poll_handler)
        polyglot.subscribe(udi_interface.STOP, stop_handler)

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
