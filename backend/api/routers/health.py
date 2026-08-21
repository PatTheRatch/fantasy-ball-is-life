"""Health check — the one genuinely public route."""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.policy import RoutePolicy, declare_policy

router = APIRouter()


@router.get("/health")
@declare_policy(RoutePolicy.PUBLIC)
def health() -> dict[str, str]:
    return {"status": "ok"}
