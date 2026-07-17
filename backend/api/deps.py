"""Shared FastAPI helpers used by routers and the app factory.

Kept separate from ``main`` so routers can import helpers without a
``main`` ↔ ``routers`` circular import.
"""
from __future__ import annotations

import io
from typing import Any, List, Optional

import numpy as np
import pandas as pd
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from backend.league import data_feed as feed
from backend.league.credentials import get_league_context, LeagueContext
from backend.league.fantasy import MyLeague
from backend.league.gateway import espn_error_status_code

# ── Lazy-resolved league context (P-4: per-request in P-4b) ───────────────────

_CTX: LeagueContext | None = None


def _resolve_ctx() -> LeagueContext:
    """Resolve the single league's credentials from the DB.

    Cached for the process lifetime (single-league interim).
    P-4b replaces this with request-scoped resolution from the URL slug.
    """
    global _CTX
    if _CTX is None:
        _CTX = get_league_context()
        if _CTX is None:
            raise RuntimeError(
                "No league found in the database. "
                "Run `python -m backend.scripts.seed_league` to seed."
            )
    return _CTX


def _my_league(year: Optional[int] = None) -> MyLeague:
    """``MyLeague`` from DB-sourced credentials (P-4)."""
    from backend.league.cache import get_cached_my_league

    ctx = _resolve_ctx()
    y = ctx.espn_season if year is None else year
    return get_cached_my_league(ctx.espn_league_id, y)


def _scoreboard(year: Optional[int] = None):
    """``WeeklyScoreboard`` from DB-sourced credentials (P-4)."""
    from backend.league.cache import get_cached_scoreboard

    ctx = _resolve_ctx()
    y = ctx.espn_season if year is None else year
    return get_cached_scoreboard(ctx.espn_league_id, y)


def _strip_numpy(obj: Any) -> Any:
    """Convert numpy/pandas scalar values to native Python for jsonable_encoder."""
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _strip_numpy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_numpy(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_strip_numpy(x) for x in obj)
    return obj


def _df_records(df: Optional[pd.DataFrame]) -> List[dict[str, Any]]:
    if df is None:
        return []
    out = df.where(pd.notnull(df), None)
    return jsonable_encoder(_strip_numpy(out.to_dict(orient="records")))


def _handles():
    return feed.connect()


def _espn_http_exception(e: Exception) -> HTTPException:
    """Map an ESPN-origin failure to its HTTP status: 504 for a gateway
    timeout, 502 for any other upstream/transport failure, 500 otherwise
    (unchanged fallback for non-ESPN errors)."""
    return HTTPException(status_code=espn_error_status_code(e), detail=str(e))


def _read_excel_bytes(data: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(data))


# ── P-3b: read-path helper ────────────────────────────────────────────────────


from functools import lru_cache


@lru_cache(maxsize=4)
def _resolve_league_uuid(espn_league_id: int) -> str | None:
    """Resolve UUID league_id from ESPN league_id (P-3 single-league bridge).

    Cached — the mapping is invariant within P-3. P-4 replaces this with
    request-scoped league resolution.
    """
    from backend.recaps.store import RecapStore

    store = RecapStore()
    rows = store._request(
        "GET",
        "leagues",
        params={
            "espn_league_id": f"eq.{espn_league_id}",
            "select": "id",
        },
    )
    return rows[0]["id"] if rows else None


def _snapshot_read(
    phase: str,
    *,
    season: int | None = None,
) -> tuple[Any, str | None]:
    """Read one phase from league_state_snapshots → (payload, fetched_at).

    Resolves league_id from the current config (single-league bridge).
    P-4 replaces the config lookup with request-scoped league resolution.

    Returns (payload_json, fetched_at) or (None, None) when no snapshot
    exists yet.
    """
    from backend.config import LEAGUE_ID, SEASON

    league_uuid = _resolve_league_uuid(LEAGUE_ID)
    if not league_uuid:
        return None, None

    from backend.recaps.store import RecapStore

    store = RecapStore()
    s = season or SEASON

    snap = store.get_phase_snapshot(league_id=league_uuid, season=s, phase=phase)
    if not snap:
        return None, None

    return snap["payload_json"], snap["fetched_at"]
