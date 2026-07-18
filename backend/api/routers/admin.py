"""P-4 admin endpoints — snapshot refresh trigger.

Secured by WORKER_SECRET (constant-time comparison). Called by Render Cron
or an authenticated admin force-refresh from the UI.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/admin", tags=["admin"])


def _verify_secret(header_value: str | None) -> None:
    """Constant-time comparison against WORKER_SECRET env var."""
    secret = os.environ.get("WORKER_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="WORKER_SECRET not configured")

    provided = header_value or ""
    if not hmac.compare_digest(secret, provided):
        raise HTTPException(status_code=403, detail="Forbidden")


@router.post("/refresh/{league_slug}")
def trigger_refresh(
    league_slug: str,
    x_worker_secret: str | None = Header(None, alias="X-Worker-Secret"),
) -> dict[str, Any]:
    """Trigger a full snapshot refresh for one league by slug.

    Credentials are resolved from the DB via ``get_league_context()``
    (P-4 — no global config monkeypatching).
    """
    _verify_secret(x_worker_secret)

    # Lazy import — avoids module-level credential resolution
    from backend.worker.refresh import refresh_league

    try:
        results = refresh_league(slug=league_slug)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return results
