"""Cron entrypoint: iterate all leagues → POST /admin/refresh/{league_id}.

Called by Render Cron per render.yaml. Iterates leagues from Supabase,
calls the authenticated refresh endpoint for each one. Per-phase isolation
means one league's slow phase never blocks others.
"""
import os
import sys

import requests

from backend.recaps.store import RecapStore


def main() -> None:
    store = RecapStore()
    leagues = store._request("GET", "leagues", params={"select": "id"})
    secret = os.environ["WORKER_SECRET"]
    base = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000")

    for row in leagues:
        lid = row["id"]
        try:
            r = requests.post(
                f"{base}/admin/refresh/{lid}",
                headers={"X-Worker-Secret": secret},
                timeout=300,
            )
            print(f"{lid}: {r.status_code}")
        except Exception as exc:
            print(f"{lid}: error — {exc}", file=sys.stderr)
            # Non-zero exit so Render logs the failure but doesn't crash other leagues.


if __name__ == "__main__":
    main()
