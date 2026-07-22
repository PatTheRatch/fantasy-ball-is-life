"""N-4b: POST /leagues — create a league with ESPN validation, cap enforcement,
credential encryption, and owner membership + optional team claim.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.league.create import validate_espn_league
from backend.recaps.auth import require_supabase_user
from backend.recaps.store import RecapStore

# N-4a router is at prefix="/leagues". This one handles the root POST.
router = APIRouter(prefix="/leagues", tags=["leagues"])


# ── Request / response models ─────────────────────────────────────────────────


class CreateLeagueRequest(BaseModel):
    espn_league_id: int
    season: int
    name: str
    swid: str | None = None
    espn_s2: str | None = None
    team_name: str | None = None


class CreateLeagueResponse(BaseModel):
    id: str
    slug: str
    name: str
    espn_league_id: int
    espn_season: int
    timezone: str
    team_name: str | None = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _slugify(name: str) -> str:
    """Convert a league name into a URL-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _unique_slug(store: RecapStore, base: str) -> str:
    """Generate a unique slug, appending -2, -3, … on collision."""
    slug = base
    suffix = 2
    while True:
        existing = store._request(
            "GET",
            "leagues",
            params={"slug": f"eq.{slug}", "select": "id"},
        )
        if not existing:
            return slug
        slug = f"{base}-{suffix}"
        suffix += 1


def _encrypt(store: RecapStore, plaintext: str | None) -> str:
    """Encrypt via Supabase pgp_sym_encrypt RPC (service-role only)."""
    if not plaintext:
        return ""
    import os
    key = os.getenv("CRED_ENCRYPTION_KEY", "")
    if not key:
        raise HTTPException(
            status_code=500,
            detail={"code": "encryption_unconfigured", "message": "CRED_ENCRYPTION_KEY env var is not set"},
        )
    rows = store._request(
        "POST",
        "rpc/pgp_sym_encrypt",
        json={"data": plaintext, "pwd": key},
    )
    if isinstance(rows, dict):
        return rows.get("pgp_sym_encrypt", "")
    return (rows[0].get("pgp_sym_encrypt", "") if rows else "")


def _count_user_leagues(store: RecapStore, user_id: str) -> int:
    """Count leagues owned by a user."""
    rows = store._request(
        "GET",
        "leagues",
        params={"owner_user_id": f"eq.{user_id}", "select": "id"},
        headers={"Accept-Profile": "service_role"},
    )
    return len(rows) if isinstance(rows, list) else 0


def _raise_validation_error(result) -> None:
    """Map a failed LeagueValidation to the appropriate HTTPException."""
    if result.error_code == "not_found":
        raise HTTPException(status_code=404, detail={"code": result.error_code, "message": result.error_message})
    if result.error_code == "espn_unavailable":
        raise HTTPException(status_code=503, detail={"code": result.error_code, "message": result.error_message})
    raise HTTPException(status_code=422, detail={"code": result.error_code, "message": result.error_message})


# ── Endpoint ──────────────────────────────────────────────────────────────────


@router.post("", response_model=CreateLeagueResponse, status_code=201)
def create_league(
    body: CreateLeagueRequest,
    _user: dict[str, Any] = Depends(require_supabase_user),
) -> CreateLeagueResponse:
    """Create a new league, validate against ESPN, encrypt credentials, and
    create the owner membership row.

    Requires a valid Supabase session. Enforces a cap of 2 owned leagues.
    """
    user_id: str = _user.get("sub", "")
    if not user_id:
        raise HTTPException(status_code=401, detail={"code": "unauthorized"})

    store = RecapStore()

    # 1. Cap enforcement
    owned = _count_user_leagues(store, user_id)
    if owned >= 2:
        raise HTTPException(
            status_code=409,
            detail={"code": "league_cap_reached", "message": "You have reached the maximum of 2 owned leagues."},
        )

    # 2. Re-validate ESPN before persisting
    result = validate_espn_league(
        espn_league_id=body.espn_league_id,
        season=body.season,
        swid=body.swid,
        espn_s2=body.espn_s2,
    )
    if not result.valid:
        _raise_validation_error(result)

    # 3. Generate slug
    base_slug = _slugify(body.name)
    slug = _unique_slug(store, base_slug)

    # 4. Encrypt credentials
    encrypted_swid = _encrypt(store, body.swid)
    encrypted_s2 = _encrypt(store, body.espn_s2)

    # 5. Insert league row (service-role — bypasses RLS)
    league_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    store._request(
        "POST",
        "leagues",
        json={
            "id": league_id,
            "slug": slug,
            "name": body.name.strip(),
            "espn_league_id": body.espn_league_id,
            "espn_season": body.season,
            "espn_swid": encrypted_swid,
            "espn_s2": encrypted_s2,
            "owner_user_id": user_id,
            "admin_user_id": user_id,
            "timezone": "America/New_York",
            "created_at": now,
            "updated_at": now,
        },
        headers={
            "Prefer": "return=minimal",
            "Accept-Profile": "service_role",
        },
    )

    # 6. Create owner membership (role=admin)
    store._request(
        "POST",
        "league_memberships",
        json={
            "id": str(uuid.uuid4()),
            "league_id": league_id,
            "user_id": user_id,
            "role": "admin",
            "created_at": now,
        },
        headers={
            "Prefer": "return=minimal",
            "Accept-Profile": "service_role",
        },
    )

    # 7. Claim team if provided
    team_name = body.team_name.strip() if body.team_name else None
    if team_name:
        existing_claims = store._request(
            "GET",
            "league_memberships",
            params={
                "league_id": f"eq.{league_id}",
                "team_name": f"ilike.{team_name}",
                "select": "id",
            },
            headers={"Accept-Profile": "service_role"},
        )
        if existing_claims:
            raise HTTPException(
                status_code=409,
                detail={"code": "team_taken", "message": f"The team '{team_name}' is already claimed."},
            )

        store._request(
            "PATCH",
            f"league_memberships?league_id=eq.{league_id}&user_id=eq.{user_id}",
            json={"team_name": team_name},
            headers={
                "Accept-Profile": "service_role",
            },
        )

    return CreateLeagueResponse(
        id=league_id,
        slug=slug,
        name=body.name.strip(),
        espn_league_id=body.espn_league_id,
        espn_season=body.season,
        timezone="America/New_York",
        team_name=team_name,
    )
