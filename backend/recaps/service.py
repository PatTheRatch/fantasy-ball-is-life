"""Weekly recap generation and publication orchestration."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from backend.commentary.generate import generate_structured_recap
from backend.commentary.schemas import dump_model
from backend.recaps.assemble import assemble_weekly_snapshot
from backend.recaps.awards import select_awards
from backend.recaps.sharing import format_share_text
from backend.recaps.store import RecapStore, RecapStoreError


def _league_or_404(store: RecapStore, slug: str) -> dict[str, Any]:
    league = store.get_league_by_slug(slug)
    if not league:
        raise HTTPException(status_code=404, detail="League not found.")
    return league


def require_admin(
    store: RecapStore, slug: str, user_id: str
) -> dict[str, Any]:
    league = _league_or_404(store, slug)
    if not store.is_league_admin(league, user_id):
        raise HTTPException(status_code=403, detail="League admin access required.")
    return league


def _edition_or_404(
    edition: dict[str, Any] | None,
    *,
    league_id: str,
    season: int,
    week: int,
) -> dict[str, Any]:
    if (
        not edition
        or edition.get("league_id") != league_id
        or int(edition.get("season", -1)) != season
        or int(edition.get("week", -1)) != week
    ):
        raise HTTPException(status_code=404, detail="Recap edition not found.")
    return edition


def _normalize_stored_snapshot(edition: dict[str, Any], league: dict[str, Any]) -> None:
    """Reshape the Supabase `league_week_snapshots` embed (raw `*_json` column
    names) into the same `snapshot` field shape `generate_draft` returns right
    after generation, so any stored edition previews the same way as a
    freshly-generated one (e.g. the matchup-results grid)."""
    stored = edition.pop("league_week_snapshots", None)
    if not stored:
        return
    edition["snapshot"] = {
        "schema_version": stored.get("schema_version"),
        "league": league,
        "season": edition.get("season"),
        "week": edition.get("week"),
        "week_dates": None,
        "matchups": stored.get("matchups_json") or [],
        "standings": stored.get("standings_json") or [],
        "power_rankings": stored.get("power_rankings_json") or [],
        "transactions": stored.get("transactions_json") or [],
        "season_stats": stored.get("season_stats_json") or [],
        "award_candidates": stored.get("award_candidates_json") or [],
        "data_quality": stored.get("data_quality_json") or {},
    }


def build_readiness(
    *,
    store: RecapStore,
    slug: str,
    user_id: str,
    season: int,
    week: int,
    week_start: str,
    week_end: str,
) -> dict[str, Any]:
    league = require_admin(store, slug, user_id)
    snapshot = assemble_weekly_snapshot(
        league=league,
        season=season,
        week=week,
        week_start=week_start,
        week_end=week_end,
    )
    snapshot.award_candidates = select_awards(snapshot)
    return dump_model(snapshot)


def generate_draft(
    *,
    store: RecapStore,
    slug: str,
    user_id: str,
    season: int,
    week: int,
    week_start: str,
    week_end: str,
    generate_anyway: bool,
) -> dict[str, Any]:
    league = require_admin(store, slug, user_id)
    snapshot = assemble_weekly_snapshot(
        league=league,
        season=season,
        week=week,
        week_start=week_start,
        week_end=week_end,
    )
    snapshot.award_candidates = select_awards(snapshot)
    snapshot_payload = dump_model(snapshot)
    if not snapshot.data_quality.ready and not generate_anyway:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Recap data is incomplete. Confirm Generate Anyway.",
                "data_quality": dump_model(snapshot.data_quality),
            },
        )

    snapshot_version = store.next_version(
        "league_week_snapshots",
        league_id=league["id"],
        season=season,
        week=week,
    )
    stored_snapshot = store.insert_snapshot(
        {
            "league_id": league["id"],
            "season": season,
            "week": week,
            "version": snapshot_version,
            "schema_version": snapshot.schema_version,
            "matchups_json": snapshot.matchups,
            "standings_json": snapshot.standings,
            "power_rankings_json": snapshot.power_rankings,
            "transactions_json": snapshot.transactions,
            "season_stats_json": snapshot.season_stats,
            "award_candidates_json": snapshot.award_candidates,
            "data_quality_json": dump_model(snapshot.data_quality),
            "created_by": user_id,
        }
    )

    try:
        generated = generate_structured_recap(snapshot)
        generated = format_share_text(snapshot, generated)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Structured recap generation failed: {exc}",
        ) from exc

    edition_version = store.next_version(
        "recap_editions",
        league_id=league["id"],
        season=season,
        week=week,
    )
    edition = store.insert_edition(
        {
            "league_id": league["id"],
            "season": season,
            "week": week,
            "version": edition_version,
            "snapshot_id": stored_snapshot["id"],
            "status": "draft",
            "structured_content_json": dump_model(generated),
            "data_warnings_json": snapshot.data_quality.warnings,
            "created_by": user_id,
        }
    )
    edition["snapshot"] = snapshot_payload
    return edition


def get_public_snapshot(
    *,
    store: RecapStore,
    slug: str,
    season: int,
    week: int,
) -> dict[str, Any]:
    """Return the snapshot for a league/week regardless of publication status.

    Public (no auth). The snapshot is deterministic — computed from ESPN, not
    generated by an LLM — so it should be visible even before the recap is published.
    Non-public leagues still 404.
    """
    league = _league_or_404(store, slug)
    if league.get("visibility", "public") != "public":
        raise _not_found()

    edition = store.get_edition(
        league_id=league["id"], season=season, week=week, status=None
    )
    if edition is None:
        raise _not_found()

    return {"league": league, "snapshot": edition["league_week_snapshots"]}


def get_public_edition(
    *,
    store: RecapStore,
    slug: str,
    season: int,
    week: int,
) -> dict[str, Any]:
    league = _league_or_404(store, slug)
    if league.get("visibility") != "public":
        raise HTTPException(status_code=404, detail="Published recap not found.")
    edition = store.get_edition(
        league_id=league["id"],
        season=season,
        week=week,
        status="published",
    )
    if not edition:
        raise HTTPException(status_code=404, detail="Published recap not found.")
    _normalize_stored_snapshot(edition, league)
    return {"league": league, "edition": edition}


def get_published_archive(
    *,
    store: RecapStore,
    slug: str,
    season: int,
) -> list[dict[str, Any]]:
    """Return all published weeks for a league/season (public)."""
    league = _league_or_404(store, slug)
    if league.get("visibility") != "public":
        raise HTTPException(status_code=404, detail="Published recap not found.")
    return store.list_published(league["id"], season)


def get_admin_edition(
    *,
    store: RecapStore,
    slug: str,
    user_id: str,
    season: int,
    week: int,
    status: str = "draft",
) -> dict[str, Any] | None:
    league = require_admin(store, slug, user_id)
    edition = store.get_edition(
        league_id=league["id"],
        season=season,
        week=week,
        status=status,
    )
    if edition:
        _normalize_stored_snapshot(edition, league)
    return edition


def get_edition_by_id(
    *,
    store: RecapStore,
    slug: str,
    user_id: str,
    season: int,
    week: int,
    edition_id: str,
) -> dict[str, Any]:
    """Full content for one specific edition -- lets an admin preview any
    past draft/superseded/published version, not just the latest."""
    league = require_admin(store, slug, user_id)
    edition = _edition_or_404(
        store.get_edition_with_content_by_id(edition_id),
        league_id=league["id"],
        season=season,
        week=week,
    )
    _normalize_stored_snapshot(edition, league)
    return edition


def get_history(
    *,
    store: RecapStore,
    slug: str,
    user_id: str,
    season: int,
    week: int,
) -> list[dict[str, Any]]:
    league = require_admin(store, slug, user_id)
    return store.get_history(
        league_id=league["id"], season=season, week=week
    )


def publish_edition(
    *,
    store: RecapStore,
    slug: str,
    user_id: str,
    season: int,
    week: int,
    edition_id: str,
) -> dict[str, Any]:
    league = require_admin(store, slug, user_id)
    _edition_or_404(
        store.get_edition_by_id(edition_id),
        league_id=league["id"],
        season=season,
        week=week,
    )
    return store.publish(edition_id, user_id)


def rollback_edition(
    *,
    store: RecapStore,
    slug: str,
    user_id: str,
    season: int,
    week: int,
    edition_id: str,
) -> dict[str, Any]:
    league = require_admin(store, slug, user_id)
    _edition_or_404(
        store.get_edition_by_id(edition_id),
        league_id=league["id"],
        season=season,
        week=week,
    )
    return store.rollback(
        edition_id,
        league_id=league["id"],
        season=season,
        week=week,
    )


def as_http_error(exc: RecapStoreError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))
