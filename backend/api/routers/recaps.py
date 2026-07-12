"""Persisted weekly recap admin and public-read endpoints."""
from __future__ import annotations

from datetime import date
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.recaps import service
from backend.recaps.auth import require_supabase_user
from backend.recaps.store import RecapStore, RecapStoreError

router = APIRouter(prefix="/leagues/{slug}/recaps", tags=["recaps"])


class GenerateDraftBody(BaseModel):
    week_start: date
    week_end: date
    generate_anyway: bool = False


class EditionActionBody(BaseModel):
    edition_id: str


def get_recap_store() -> RecapStore:
    return RecapStore()


def _run(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except RecapStoreError as exc:
        raise service.as_http_error(exc) from exc


def _user_id(user: dict[str, Any]) -> str:
    return str(user["id"])


def _validate_dates(start: date, end: date) -> None:
    if end < start:
        raise HTTPException(
            status_code=422, detail="week_end must be on or after week_start."
        )


@router.get("/{season}/{week}")
def published_recap(
    slug: str,
    season: int,
    week: int,
    store: RecapStore = Depends(get_recap_store),
) -> dict[str, Any]:
    return _run(
        lambda: service.get_public_edition(
            store=store, slug=slug, season=season, week=week
        )
    )


@router.get("/{season}/{week}/readiness")
def recap_readiness(
    slug: str,
    season: int,
    week: int,
    week_start: date = Query(...),
    week_end: date = Query(...),
    user: dict[str, Any] = Depends(require_supabase_user),
    store: RecapStore = Depends(get_recap_store),
) -> dict[str, Any]:
    _validate_dates(week_start, week_end)
    return _run(
        lambda: service.build_readiness(
            store=store,
            slug=slug,
            user_id=_user_id(user),
            season=season,
            week=week,
            week_start=week_start.isoformat(),
            week_end=week_end.isoformat(),
        )
    )


@router.post("/{season}/{week}/generate")
def generate_recap_draft(
    slug: str,
    season: int,
    week: int,
    body: GenerateDraftBody,
    user: dict[str, Any] = Depends(require_supabase_user),
    store: RecapStore = Depends(get_recap_store),
) -> dict[str, Any]:
    _validate_dates(body.week_start, body.week_end)
    return _run(
        lambda: service.generate_draft(
            store=store,
            slug=slug,
            user_id=_user_id(user),
            season=season,
            week=week,
            week_start=body.week_start.isoformat(),
            week_end=body.week_end.isoformat(),
            generate_anyway=body.generate_anyway,
        )
    )


@router.get("/{season}/{week}/draft")
def latest_recap_draft(
    slug: str,
    season: int,
    week: int,
    user: dict[str, Any] = Depends(require_supabase_user),
    store: RecapStore = Depends(get_recap_store),
) -> Optional[dict[str, Any]]:
    return _run(
        lambda: service.get_admin_edition(
            store=store,
            slug=slug,
            user_id=_user_id(user),
            season=season,
            week=week,
        )
    )


@router.get("/{season}/{week}/history")
def recap_history(
    slug: str,
    season: int,
    week: int,
    user: dict[str, Any] = Depends(require_supabase_user),
    store: RecapStore = Depends(get_recap_store),
) -> list[dict[str, Any]]:
    return _run(
        lambda: service.get_history(
            store=store,
            slug=slug,
            user_id=_user_id(user),
            season=season,
            week=week,
        )
    )


@router.post("/{season}/{week}/publish")
def publish_recap(
    slug: str,
    season: int,
    week: int,
    body: EditionActionBody,
    user: dict[str, Any] = Depends(require_supabase_user),
    store: RecapStore = Depends(get_recap_store),
) -> dict[str, Any]:
    return _run(
        lambda: service.publish_edition(
            store=store,
            slug=slug,
            user_id=_user_id(user),
            season=season,
            week=week,
            edition_id=body.edition_id,
        )
    )


@router.post("/{season}/{week}/rollback")
def rollback_recap(
    slug: str,
    season: int,
    week: int,
    body: EditionActionBody,
    user: dict[str, Any] = Depends(require_supabase_user),
    store: RecapStore = Depends(get_recap_store),
) -> dict[str, Any]:
    return _run(
        lambda: service.rollback_edition(
            store=store,
            slug=slug,
            user_id=_user_id(user),
            season=season,
            week=week,
            edition_id=body.edition_id,
        )
    )
