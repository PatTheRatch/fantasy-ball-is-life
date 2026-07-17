"""Per-league ESPN credential resolution — replaces the module-level config.

P-4 replaces the single-global ``config.LEAGUE_ID/SWID/ESPN_S2/SEASON``
constants with per-league rows in the ``leagues`` table. Credentials are
encrypted at rest with pgcrypto; this module decrypts them at resolution
time.

Interim (single-league): ``get_league_context()`` resolves the only league
row. When P-4b adds slug-scoped routes, each request's league context is
derived from the URL slug.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from backend.recaps.store import RecapStore


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
    return rows.get("pgp_sym_decrypt", "") if isinstance(rows, dict) else (rows[0].get("pgp_sym_decrypt", "") if rows else "")


def get_league_context(
    *,
    slug: str | None = None,
    store: RecapStore | None = None,
) -> LeagueContext | None:
    """Resolve one league's credentials from the DB.

    Args:
        slug: Optional league slug. If None, resolves the first league
              (single-league interim path; P-4b adds slug-scoped resolution).
        store: Optional RecapStore instance (creates one if not provided).

    Returns None if no league row matches.
    """
    _store = store or RecapStore()
    params: dict[str, str] = {
        "select": "id,slug,name,espn_league_id,espn_season,espn_swid,espn_s2,timezone",
    }
    if slug:
        params["slug"] = f"eq.{slug}"
    else:
        params["limit"] = "1"

    rows = _store._request("GET", "leagues", params=params)
    if not rows:
        return None

    row = rows[0]
    return LeagueContext(
        league_id=row["id"],
        slug=row["slug"],
        name=row["name"],
        espn_league_id=int(row["espn_league_id"] or 0),
        espn_season=int(row["espn_season"] or 0),
        swid=_decrypt(row.get("espn_swid"), store=_store),
        espn_s2=_decrypt(row.get("espn_s2"), store=_store),
        timezone=row.get("timezone", "America/New_York"),
    )
