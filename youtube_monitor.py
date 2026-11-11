"""YouTube livestream monitoring."""

from pathlib import Path
from datetime import datetime, timezone
import json
import threading
import time
import requests

API_BASE = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"

_access_token = None
_token_expires = 0
_token_lock = threading.Lock()


def get_access_token(auth_dir):
    global _access_token, _token_expires

    with _token_lock:
        if _access_token and time.monotonic() < _token_expires:
            return _access_token

        auth_dir = Path(auth_dir)
        token = json.loads((auth_dir / "token.json").read_text())
        client = json.loads(
            (auth_dir / "client_secret.json").read_text()
        )["installed"]

        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": client["client_id"],
                "client_secret": client["client_secret"],
                "refresh_token": token["refresh_token"],
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        response.raise_for_status()

        data = response.json()
        _access_token = data["access_token"]
        _token_expires = time.monotonic() + data.get("expires_in", 3600) - 60

        return _access_token


def check_stream(auth_dir):
    access_token = get_access_token(auth_dir)
    headers = {"Authorization": f"Bearer {access_token}"}

    stream_ids = set()
    broadcast_status = "offline"
    next_start = None
    now = datetime.now(timezone.utc)

    for status in ("active", "upcoming"):
        response = requests.get(
            f"{API_BASE}/liveBroadcasts",
            headers=headers,
            params={
                "part": "snippet,contentDetails",
                "broadcastStatus": status,
                "maxResults": 50,
            },
            timeout=15,
        )
        response.raise_for_status()

        for item in response.json().get("items", []):
            snippet = item.get("snippet", {})
            stream_id = item.get(
                "contentDetails", {}
            ).get("boundStreamId")

            if stream_id:
                stream_ids.add(stream_id)

            if status == "active":
                broadcast_status = "live"

            elif status == "upcoming":
                scheduled = snippet.get("scheduledStartTime")

                if scheduled:
                    start = datetime.fromisoformat(
                        scheduled.replace("Z", "+00:00")
                    )

                    if start > now:
                        if next_start is None or start < next_start:
                            next_start = start

    if broadcast_status != "live" and next_start:
        broadcast_status = "scheduled"

    if not stream_ids:
        return {
            "receiving": False,
            "broadcast": broadcast_status,
            "streams": 0,
            "next_start": next_start.isoformat() if next_start else None,
        }

    response = requests.get(
        f"{API_BASE}/liveStreams",
        headers=headers,
        params={
            "part": "status",
            "id": ",".join(sorted(stream_ids)),
        },
        timeout=15,
    )
    response.raise_for_status()

    statuses = [
        item.get("status", {}).get("streamStatus", "unknown")
        for item in response.json().get("items", [])
    ]

    return {
        "receiving": "active" in statuses,
        "broadcast": broadcast_status,
        "streams": len(stream_ids),
        "statuses": statuses,
        "next_start": next_start.isoformat() if next_start else None,
    }


if __name__ == "__main__":
    result = check_stream(Path(__file__).resolve().parent / "persist")
    print(json.dumps(result, indent=2))
