"""Send one sample alert to the local API.

Usage (from the graduation-project folder, with the API already running):

    python scripts/send_sample_alert.py
    python scripts/send_sample_alert.py --fresh          # new event_id + now()
    python scripts/send_sample_alert.py --sample api/samples/create_alert_camera_frozen.json
    python scripts/send_sample_alert.py --api-key local-dev-key

No third-party dependency: uses urllib from the standard library.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE = ROOT / "api" / "samples" / "create_alert_fight.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Post a sample alert to the API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--sample", type=Path, default=DEFAULT_SAMPLE)
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="replace event_id with a new UUID and timestamp with now()",
    )
    parser.add_argument("--api-key", default=None, help="sent as X-API-Key")
    args = parser.parse_args()

    payload = json.loads(args.sample.read_text(encoding="utf-8"))
    if args.fresh:
        payload["event_id"] = str(uuid.uuid4())
        payload["timestamp"] = (
            datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )

    request = urllib.request.Request(
        f"{args.base_url.rstrip('/')}/api/v1/alerts",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if args.api_key:
        request.add_header("X-API-Key", args.api_key)

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status = response.status
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8")
    except urllib.error.URLError as exc:
        print(f"Cannot reach the API at {args.base_url}: {exc.reason}", file=sys.stderr)
        return 2

    print(f"POST {args.base_url}/api/v1/alerts -> {status}")
    print(json.dumps(json.loads(body), indent=2, ensure_ascii=False))

    if status == 201:
        print(f"\nCreated. Open in the browser: {args.base_url}/api/v1/alerts/{payload['event_id']}")
    elif status == 200:
        print("\nDuplicate event_id: already stored, nothing changed (idempotent).")

    return 0 if status < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
