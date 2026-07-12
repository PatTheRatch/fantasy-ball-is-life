"""Supabase access-token verification for recap admin endpoints."""
from __future__ import annotations

from typing import Any, Optional

import requests
from fastapi import Header, HTTPException

from backend import config


def require_supabase_user(
    authorization: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in is required.")

    if not config.SUPABASE_URL or not config.SUPABASE_ANON_KEY:
        raise HTTPException(status_code=503, detail="Supabase auth is not configured.")

    access_token = authorization.split(" ", 1)[1].strip()
    if not access_token:
        raise HTTPException(status_code=401, detail="Invalid access token.")

    try:
        response = requests.get(
            f"{config.SUPABASE_URL}/auth/v1/user",
            headers={
                "apikey": config.SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {access_token}",
            },
            timeout=10,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=503, detail="Authentication service is unavailable."
        ) from exc

    if response.status_code in {401, 403}:
        raise HTTPException(status_code=401, detail="Session is invalid or expired.")
    if not response.ok:
        raise HTTPException(
            status_code=503, detail="Authentication service is unavailable."
        )

    user = response.json()
    if not user.get("id"):
        raise HTTPException(status_code=401, detail="Session is invalid or expired.")
    return user
