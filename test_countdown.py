import sys
import types
import logging
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

mock = types.ModuleType("udi_interface")
mock.Node = type("Node", (), {})
mock.OAuth = type("OAuth", (), {})
mock.LOGGER = logging.getLogger("youtube_test")
sys.modules["udi_interface"] = mock

import youtube_live


def make_controller():
    controller = object.__new__(youtube_live.YouTubeController)
    controller.lock = threading.Lock()
    controller.scheduled_start = None
    controller.scheduled_id = None
    controller.zero_reported = False
    controller.last_check = 0
    controller.checking = True
    controller.values = {}
    controller.setDriver = lambda driver, value, **kwargs: (
        controller.values.__setitem__(driver, value)
    )
    return controller


def check(controller, now, start, status="upcoming", present=True):
    broadcast_id = "service1"
    scheduled = start.isoformat()

    result = {
        "receiving": status == "active",
        "broadcast": "live" if status == "active" else "scheduled",
        "next_start": scheduled if present and status == "upcoming"
                      and start > now else None,
        "next_id": broadcast_id if present and status == "upcoming"
                   and start > now else None,
        "upcoming_ids": [broadcast_id] if present and status == "upcoming" else [],
        "active_ids": [broadcast_id] if present and status == "active" else [],
        "upcoming_schedules": (
            {broadcast_id: scheduled}
            if present and status == "upcoming" else {}
        ),
    }

    with patch.object(youtube_live, "youtube_oauth") as oauth, \
         patch.object(youtube_live, "check_stream", return_value=result), \
         patch.object(youtube_live, "datetime") as clock:
        oauth.getAccessToken.return_value = "test-token"
        clock.now.return_value = now
        clock.fromisoformat.side_effect = datetime.fromisoformat
        controller._check_worker()

    return controller.values["GV3"]


def test_camera_trigger():
    start = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    c = make_controller()

    assert check(c, start - timedelta(seconds=60), start) == 1
    assert check(c, start - timedelta(seconds=40), start) == 1
    assert check(c, start - timedelta(seconds=20), start) == 0


def test_transition_to_live():
    start = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    c = make_controller()

    check(c, start - timedelta(seconds=20), start)
    assert check(c, start + timedelta(seconds=10), start, "active") == 0


def test_canceled_broadcast():
    start = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    c = make_controller()

    check(c, start - timedelta(minutes=5), start)
    assert check(c, start - timedelta(minutes=3), start,
                 present=False) == -1


def test_advance_after_start():
    start = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    c = make_controller()

    check(c, start - timedelta(seconds=20), start)
    assert check(c, start + timedelta(seconds=70), start,
                 present=False) == -1


def test_late_upcoming_broadcast():
    start = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    c = make_controller()

    assert check(c, start - timedelta(seconds=20), start) == 0

    # YouTube still lists the broadcast as upcoming,
    # even though its scheduled start was 70 seconds ago.
    assert check(c, start + timedelta(seconds=70), start) == -1


def test_late_upcoming_broadcast():
    start = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    c = make_controller()

    assert check(c, start - timedelta(seconds=20), start) == 0

    # YouTube still lists the broadcast as upcoming,
    # even though its scheduled start was 70 seconds ago.
    assert check(c, start + timedelta(seconds=70), start) == -1


def test_advance_to_next_service():
    start = datetime(2026, 11, 15, 10, 0, tzinfo=timezone.utc)
    next_start = start + timedelta(days=1)
    c = make_controller()

    # Current service reaches the camera trigger.
    assert check(c, start - timedelta(seconds=20), start) == 0

    # Current service is now live.
    assert check(c, start + timedelta(seconds=10), start, "active") == 0

    # After one minute, YouTube reports the next service.
    now = start + timedelta(seconds=70)
    result = {
        "receiving": True,
        "broadcast": "live",
        "next_start": next_start.isoformat(),
        "next_id": "service2",
        "upcoming_ids": ["service2"],
        "active_ids": ["service1"],
        "upcoming_schedules": {"service2": next_start.isoformat()},
    }

    with patch.object(youtube_live, "youtube_oauth") as oauth, \
         patch.object(youtube_live, "check_stream", return_value=result), \
         patch.object(youtube_live, "datetime") as clock:
        oauth.getAccessToken.return_value = "test-token"
        clock.now.return_value = now
        clock.fromisoformat.side_effect = datetime.fromisoformat
        c._check_worker()

    assert c.scheduled_id == "service2"
    assert c.values["GV3"] > 1000
