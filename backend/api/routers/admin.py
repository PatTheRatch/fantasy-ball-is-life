"""P-3 admin endpoints — snapshot refresh trigger.

Secured by WORKER_SECRET (constant-time comparison). Called by Render Cron
or an authenticated admin force-refresh from the UI.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

from backend.worker.refresh import refresh_league

router = APIRouter(prefix="/admin", tags=["admin"])


def _verify_secret(header_value: str | None) -> None:
    """Constant-time comparison against WORKER_SECRET env var."""
    secret = os.environ.get("WORKER_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="WORKER_SECRET not configured")

    provided = header_value or ""
    if not hmac.compare_digest(
        hashlib.sha256(provided.encode()).digest(),
        hashlib.sha256(secret.encode()).digest(),
    ):
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/refresh/{league_id}")
def trigger_refresh(
    league_id: str,
    x_worker_secret: str | None = Header(None, alias="X-Worker-Secret"),
) -> dict[str, Any]:
    """Trigger a full snapshot refresh for one league.

    Called by Render Cron (15-min / 6-h cadence) or admin force-refresh.
    Returns per-phase status for observability.
    """
    _verify_secret(x_worker_secret)

    # Load league credentials from the database
    from backend.recaps.store import RecapStore
    store = RecapStore()

    rows = store._request(
        "GET",
        "leagues",
        params={"id": f"eq.{league_id}", "select": "id,espn_league_id,espn_season,espn_s2,espn_swid"},
    )
    if not rows:
        raise HTTPException(status_code=404, detail="League not found")

    league = rows[0]

    # Decrypt creds — pgcrypto integration comes in P-4 when leagues table
    # gains encrypted columns; for now read directly.
    try:
        espn_league_id = int(league["espn_league_id"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail="League is missing valid espn_league_id",
        )

    results = refresh_league(
        league_id=league_id,
        espn_league_id=espn_league_id,
        espn_season=int(league.get("espn_season", 2026)),
        espn_s2=str(league.get("espn_s2", "")),
        swid=str(league.get("espn_swid", "")),
    )

    return JSONResponse(content={"league_id": league_id, "phases": results})
