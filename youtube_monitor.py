"""YouTube livestream monitoring."""

from datetime import datetime, timezone
import requests

API_BASE = "https://www.googleapis.com/youtube/v3"
def check_stream(access_token):
    if not access_token:
        raise RuntimeError("YouTube OAuth access token unavailable")

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
