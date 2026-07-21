"""Cron entrypoint: POST /admin/refresh-all.

Called by Render Cron per render.yaml. The endpoint iterates every league
from the DB with per-league failure isolation (N-3), so one league's
failure never blocks the rest.
"""
import os
import sys

import requests


def main() -> None:
    secret = os.environ["WORKER_SECRET"]
    base = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8000")

    try:
        r = requests.post(
            f"{base}/admin/refresh-all",
            headers={"X-Worker-Secret": secret},
            timeout=900,
        )
        print(f"refresh-all: {r.status_code} {r.text[:2000]}")
        if not r.ok:
            sys.exit(1)
    except Exception as exc:
        print(f"refresh-all: error — {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
