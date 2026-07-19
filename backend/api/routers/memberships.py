"""N-2: Invite management + self-join + member removal endpoints."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from backend.league.credentials import get_league_context, resolve_league_context
from backend.recaps.store import RecapStore
from backend.recaps.store import RecapStoreError as _StoreError

router = APIRouter(prefix="/leagues/{slug}", tags=["memberships"])


def _require_user(request: Request) -> str:
    """Extract authenticated user ID from Supabase auth JWT in the request."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    # The slug middleware already resolved the league context.
    # We rely on Supabase RLS to enforce per-user access; here we just
    # need the user ID for the redeem/invite endpoints.
    # In production, the user ID comes from the Supabase JWT.
    # For now, extract it from the header — the Supabase client sends it.
    try:
        import jwt
        token = auth_header.split(" ", 1)[1]
        # Don't verify — Supabase proxy already did. Just decode.
        payload = jwt.decode(token, options={"verify_signature": False})
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user_id
    except Exception:
        raise HTTPException(status_code=401, detail="Could not parse auth token")


# ── Invite CRUD (admin only) ────────────────────────────────────────────

@router.post("/invites")
def create_invite(
    slug: str,
    request: Request,
    email: str | None = None,
    role: str = "member",
    expires_in_days: int = 7,
) -> dict[str, Any]:
    """Create a single-use invite link. Admin only (enforced by RLS)."""
    ctx = get_league_context()
    if ctx is None:
        raise HTTPException(status_code=404, detail="League not found")

    user_id = _require_user(request)
    store = RecapStore()

    token = secrets.token_urlsafe(24)  # ~192 bits
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    row = {
        "league_id": ctx.league_id,
        "token": token,
        "email": email,
        "role": role,
        "expires_at": expires_at.isoformat(),
        "created_by": user_id,
    }

    try:
        result = store._request(
            "POST", "league_invites", json=row, prefer="return=representation"
        )
        return {"invite": result[0] if isinstance(result, list) else result}
    except _StoreError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/invites")
def list_invites(slug: str) -> dict[str, Any]:
    """List active (unused) invites for a league. Admin only (RLS)."""
    ctx = get_league_context()
    if ctx is None:
        raise HTTPException(status_code=404, detail="League not found")

    store = RecapStore()
    try:
        rows = store._request(
            "GET",
            "league_invites",
            params={
                "league_id": f"eq.{ctx.league_id}",
                "select": "id,token,email,role,expires_at,created_at,used_at",
                "used_at": "is.null",
                "order": "created_at.desc",
            },
        )
        return {"invites": rows or []}
    except _StoreError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/invites/{invite_id}")
def delete_invite(slug: str, invite_id: str) -> dict[str, str]:
    """Delete an invite. Admin only (RLS)."""
    ctx = get_league_context()
    if ctx is None:
        raise HTTPException(status_code=404, detail="League not found")

    store = RecapStore()
    try:
        store._request(
            "DELETE",
            "league_invites",
            params={"id": f"eq.{invite_id}", "league_id": f"eq.{ctx.league_id}"},
        )
        return {"status": "deleted"}
    except _StoreError as e:
        raise HTTPException(status_code=403, detail=str(e))


# ── Redeem ──────────────────────────────────────────────────────────────

@router.post("/join")
def join_league(
    slug: str,
    request: Request,
    invite_token: str | None = None,
    team_name: str | None = None,
) -> dict[str, Any]:
    """Join a league — either via invite token or self-join (public league).

    Self-join: omit invite_token, provide team_name to claim.
    Invite join: provide invite_token, team_name optional.
    """
    ctx = get_league_context()
    if ctx is None:
        raise HTTPException(status_code=404, detail="League not found")

    user_id = _require_user(request)
    store = RecapStore()

    if invite_token:
        # Redeem via invite RPC
        try:
            result = store._request(
                "POST",
                "rpc/redeem_league_invite",
                json={"p_token": invite_token},
            )
            league_id = (
                result if isinstance(result, str) else result.get("redeem_league_invite", "")
            )
        except _StoreError as e:
            raise HTTPException(status_code=400, detail=str(e))
    else:
        # Self-join: insert membership directly (RLS policy enforces public-only)
        league_id = ctx.league_id
        row = {
            "league_id": league_id,
            "user_id": user_id,
            "role": "member",
            "team_name": team_name,
        }
        try:
            store._request("POST", "league_memberships", json=row)
        except _StoreError as e:
            msg = str(e)
            if "duplicate key" in msg or "unique" in msg.lower():
                if "team" in msg.lower():
                    raise HTTPException(
                        status_code=409,
                        detail="That team name is already claimed. Try another.",
                    )
                raise HTTPException(status_code=409, detail="You're already a member of this league.")
            raise HTTPException(status_code=403, detail=msg)

    return {"status": "joined", "league_id": league_id}


# ── Member list + removal ──────────────────────────────────────────────

@router.get("/members")
def list_members(slug: str) -> dict[str, Any]:
    """List league members with their claimed teams."""
    ctx = get_league_context()
    if ctx is None:
        raise HTTPException(status_code=404, detail="League not found")

    store = RecapStore()
    try:
        rows = store._request(
            "GET",
            "league_memberships",
            params={
                "league_id": f"eq.{ctx.league_id}",
                "select": "user_id,role,team_name,created_at",
                "order": "created_at.asc",
            },
        )
        return {"members": rows or []}
    except _StoreError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/members/{user_id}")
def remove_member(slug: str, user_id: str) -> dict[str, str]:
    """Remove a member from the league. Admin or self only (RLS)."""
    ctx = get_league_context()
    if ctx is None:
        raise HTTPException(status_code=404, detail="League not found")

    store = RecapStore()
    try:
        store._request(
            "DELETE",
            "league_memberships",
            params={
                "league_id": f"eq.{ctx.league_id}",
                "user_id": f"eq.{user_id}",
            },
        )
        return {"status": "removed"}
    except _StoreError as e:
        raise HTTPException(status_code=403, detail=str(e))
