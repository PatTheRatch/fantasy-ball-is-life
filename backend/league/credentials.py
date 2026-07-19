"""Per-league ESPN credential resolution — replaces the module-level config.

P-4 replaces the single-global ``config.LEAGUE_ID/SWID/ESPN_S2/SEASON``
constants with per-league rows in the ``leagues`` table. Credentials are
encrypted at rest with pgcrypto; this module decrypts them at resolution
time.

Caching
-------
``resolve_league_context()`` fetches from the DB and caches the result in
a ``ContextVar`` for the lifetime of the request. ``get_league_context()``
returns the cached value (or None if nothing is resolved yet). Callers
that need a guaranteed context (e.g. dependency injection) should call
``resolve_league_context()`` directly.

Injecting a test / offline context
----------------------------------
Tests and CLI callers can push a ``LeagueContext`` onto the ContextVar
without touching Supabase::

    _LEAGUE_CTX.set(LeagueContext(...))

The decorator ``@with_cached_league_context`` injects the ctx Var as a
FastAPI dependency with a null-provider fallback — no request-scoped DB
resolution needed.

Interim (single-league): ``resolve_league_context()`` resolves the only
league row. When P-4b adds slug-scoped routes, each request's league
context is derived from the URL slug.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from backend.recaps.store import RecapStore
from backend.recaps.store import RecapStoreError as _StoreError

# ── ContextVar: one resolution per request ────────────────────────────────────

_LEAGUE_CTX: ContextVar[LeagueContext | None] = ContextVar(
    "league_context", default=None
)


@dataclass(frozen=True)
class LeagueContext:
    """Credentials + identity for one league, resolved from the DB."""
    league_id: str          # UUID primary key
    slug: str
    name: str
    espn_league_id: int
    espn_season: int
    swid: str               # decrypted
    espn_s2: str            # decrypted
    timezone: str


def get_league_context() -> LeagueContext | None:
    """Return the request-scoped league context, or None if not resolved yet.

    Does NOT hit the database — returns whatever ``resolve_league_context()``
    cached on the ContextVar (or whatever a test pushed). Returns None when
    no context has been set, meaning the caller should either inject one or
    call ``resolve_league_context()`` to fetch it.
    """
    return _LEAGUE_CTX.get()


def _decrypt(value: str | None, *, store: RecapStore) -> str:
    """Decrypt a pgp_sym_encrypt-ed column via a Supabase RPC call."""
    if not value:
        return ""
    key = os.getenv("CRED_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("CRED_ENCRYPTION_KEY env var is required for credential decryption")
    rows = store._request(
        "POST",
        "rpc/pgp_sym_decrypt",
        json={"data": value, "pwd": key},
    )
    # RPC returns the decrypted value as a bare string.
    if isinstance(rows, str):
        return rows
    if isinstance(rows, dict):
        return rows.get("pgp_sym_decrypt", "")
    if isinstance(rows, list) and rows:
        first = rows[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return first.get("pgp_sym_decrypt", "")
    return ""


def resolve_league_context(
    *,
    slug: str | None = None,
    store: RecapStore | None = None,
) -> LeagueContext | None:
    """Fetch league credentials from the DB and cache on the ContextVar.

    Call this ONCE per request (or once per process for CLI/worker paths).
    Subsequent ``get_league_context()`` calls return the cached value for
    free.

    Args:
        slug: Optional league slug. If None, resolves the first league
              (single-league interim path; P-4b adds slug-scoped resolution).
        store: Optional RecapStore instance (creates one if not provided).

    Returns None if no league row matches.
    """
    try:
        _store = store or RecapStore()
    except _StoreError:
        # Supabase not configured — leave ctx as None (offline/test path)
        return None

    params: dict[str, str] = {
        "select": "id,slug,name,espn_league_id,espn_season,espn_swid,espn_s2,timezone",
    }
    if slug:
        params["slug"] = f"eq.{slug}"
    else:
        params["limit"] = "1"

    try:
        rows = _store._request("GET", "leagues", params=params)
    except _StoreError:
        return None

    if not rows:
        return None

    row = rows[0]
    ctx = LeagueContext(
        league_id=row["id"],
        slug=row["slug"],
        name=row["name"],
        espn_league_id=int(row["espn_league_id"] or 0),
        espn_season=int(row["espn_season"] or 0),
        swid=_decrypt(row.get("espn_swid"), store=_store),
        espn_s2=_decrypt(row.get("espn_s2"), store=_store),
        timezone=row.get("timezone", "America/New_York"),
    )
    _LEAGUE_CTX.set(ctx)
    return ctx


def _require_context() -> LeagueContext:
    """Return the current league context or raise a clear error."""
    ctx = get_league_context()
    if ctx is None:
        raise RuntimeError(
            "No league context available. "
            "Run `python -m backend.scripts.seed_league` to seed the DB, "
            "or inject a LeagueContext for testing."
        )
    return ctx
