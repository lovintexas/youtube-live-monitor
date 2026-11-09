"""YouTube livestream monitoring for HTTP Control."""

from pathlib import Path
import json
import requests

API_BASE = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_access_token(auth_dir):
    auth_dir = Path(auth_dir)
    token_path = auth_dir / "token.json"
    secret_path = auth_dir / "client_secret.json"

    token = json.loads(token_path.read_text())
    client = json.loads(secret_path.read_text())["installed"]

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
    return response.json()["access_token"]


def check_stream(auth_dir):
    access_token = get_access_token(auth_dir)
    headers = {"Authorization": f"Bearer {access_token}"}

    stream_ids = set()
    broadcast_status = "offline"

    for status in ("active", "upcoming"):
        response = requests.get(
            f"{API_BASE}/liveBroadcasts",
            headers=headers,
            params={
                "part": "contentDetails",
                "broadcastStatus": status,
                "maxResults": 50,
            },
            timeout=15,
        )
        response.raise_for_status()

        items = response.json().get("items", [])

        if status == "active" and items:
            broadcast_status = "live"
        elif status == "upcoming" and items and broadcast_status != "live":
            broadcast_status = "scheduled"

        for item in items:
            stream_id = item.get("contentDetails", {}).get("boundStreamId")
            if stream_id:
                stream_ids.add(stream_id)

    if not stream_ids:
        return {"receiving": False, "streams": 0, "broadcast": broadcast_status}

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
    }


if __name__ == "__main__":
    result = check_stream(Path(__file__).resolve().parent / "persist")
    print(json.dumps(result, indent=2))
