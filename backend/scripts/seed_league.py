"""One-time seed: insert the Patriot Games league row with encrypted credentials.

Idempotent — running twice does not duplicate the row. Uses the current
environment variables (ESPN_LEAGUE_ID, ESPN_SWID, ESPN_S2, ESPN_SEASON).

Usage:
    python -m backend.scripts.seed_league

Pre-requisites:
    CRED_ENCRYPTION_KEY set in the environment (same key used by the
    migration and the credential resolver).
"""

from __future__ import annotations

import os
import sys

# Ensure project root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.recaps.store import RecapStore


def _encrypt(plaintext: str | None) -> str:
    """Encrypt a value via Supabase's pgp_sym_encrypt RPC."""
    if not plaintext:
        return ""
    key = os.getenv("CRED_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("CRED_ENCRYPTION_KEY env var is required")
    store = RecapStore()
    rows = store._request(
        "POST",
        "rpc/pgp_sym_encrypt",
        json={"data": plaintext, "pwd": key},
    )
    return rows.get("pgp_sym_encrypt", "") if isinstance(rows, dict) else (rows[0].get("pgp_sym_encrypt", "") if rows else "")


def main() -> None:
    espn_league_id = int(os.getenv("ESPN_LEAGUE_ID", "3853870"))
    espn_season = int(os.getenv("ESPN_SEASON", "2026"))
    swid = os.getenv("ESPN_SWID", "")
    espn_s2 = os.getenv("ESPN_S2", "")
    slug = os.getenv("RECAP_LEAGUE_SLUG", "patriot-games")

    store = RecapStore()

    # Check if the league already exists (idempotent)
    existing = store._request(
        "GET",
        "leagues",
        params={"slug": f"eq.{slug}", "select": "id"},
    )

    encrypted_swid = _encrypt(swid)
    encrypted_s2 = _encrypt(espn_s2)

    if existing:
        print(f"League '{slug}' already exists (id={existing[0]['id']}). Updating credentials...")
        store._request(
            "PATCH",
            f"leagues?id=eq.{existing[0]['id']}",
            json={
                "espn_league_id": espn_league_id,
                "espn_season": espn_season,
                "espn_swid": encrypted_swid,
                "espn_s2": encrypted_s2,
            },
        )
        print("Updated.")
    else:
        import uuid
        new_id = str(uuid.uuid4())
        store._request(
            "POST",
            "leagues",
            json={
                "id": new_id,
                "slug": slug,
                "name": "Patriot Games",
                "espn_league_id": espn_league_id,
                "espn_season": espn_season,
                "espn_swid": encrypted_swid,
                "espn_s2": encrypted_s2,
                "timezone": "America/New_York",
            },
        )
        print(f"Inserted league '{slug}' (id={new_id}).")

    print("Done.")


if __name__ == "__main__":
    main()
