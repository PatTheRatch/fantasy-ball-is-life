"""Weekly recap generation and publication orchestration."""
from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import HTTPException

from backend.commentary.generate import generate_structured_recap
from backend.commentary.schemas import RankingExplanation, dump_model
from backend.league.data_feed import MATCHUP_WEEKS_2025_26
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

    # Power rankings are generated once per (league, season, week) and reused
    # on every later recap regeneration for that week -- the recap narrative
    # can be redrafted repeatedly (an admin iterating on wording, a retry
    # after a bad LLM response) without re-asking the LLM for rankings text
    # that has no reason to change.
    cached_rankings = store.get_power_rankings(
        league_id=league["id"], season=season, week=week
    )

    llm_started = time.perf_counter()
    try:
        generated = generate_structured_recap(
            snapshot, skip_ranking_explanations=cached_rankings is not None
        )
        generated = format_share_text(snapshot, generated)
    except Exception as exc:
        # Surface the real cause in the server logs — the detail below only
        # reaches the HTTP response body, so without this the Render logs show
        # a bare 502 with no reason (e.g. DeepSeek token-limit / API errors).
        logging.exception("recap generation failed after %.2fs: %s",
                          time.perf_counter() - llm_started, exc)
        raise HTTPException(
            status_code=502,
            detail=f"Structured recap generation failed: {exc}",
        ) from exc
    finally:
        logging.info(
            "recap assembly: LLM generate_structured_recap took %.2fs",
            time.perf_counter() - llm_started,
        )

    if cached_rankings is not None:
        generated.ranking_explanations = [
            RankingExplanation(**row)
            for row in (cached_rankings.get("ranking_explanations_json") or [])
        ]
    elif generated.ranking_explanations:
        try:
            store.insert_power_rankings(
                {
                    "league_id": league["id"],
                    "season": season,
                    "week": week,
                    "ranking_explanations_json": dump_model(generated)["ranking_explanations"],
                    "created_by": user_id,
                }
            )
        except RecapStoreError:
            # A concurrent generate_draft call for the same brand-new week can
            # win the insert first (unique constraint on league/season/week) --
            # this generation still succeeded, so don't fail the whole draft
            # over a lost cache-write race. The next regeneration will read
            # whichever row won.
            logging.warning(
                "power_ranking_editions insert lost a race for (%s, %s, %s); "
                "this generation's blurbs were not persisted",
                league["id"], season, week,
            )

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
    """Return the deterministic snapshot for a league/week (public, no auth).

    The snapshot (matchups, standings, power rankings, season stats,
    transactions) is computed from ESPN, not the LLM, so it must be visible even
    when no recap has been generated for the week. Prefer a stored edition's
    snapshot when one exists (cheap, already computed); otherwise assemble it
    fresh from ESPN. Never gated on a recap. Non-public leagues 404.
    """
    league = _league_or_404(store, slug)
    if league.get("visibility", "public") != "public":
        raise HTTPException(status_code=404, detail="League not found.")

    edition = store.get_edition(
        league_id=league["id"], season=season, week=week, status=None
    )
    if edition is not None and edition.get("league_week_snapshots"):
        # Reuse the already-computed snapshot; normalize the *_json columns into
        # the matchups/standings/... shape the tabs read.
        _normalize_stored_snapshot(edition, league)
        return {"league": league, "snapshot": edition["snapshot"]}

    # No stored snapshot yet — assemble deterministically from ESPN so the tabs
    # always have data.
    dates = MATCHUP_WEEKS_2025_26.get(week)
    if not dates:
        raise HTTPException(
            status_code=404, detail=f"No calendar window for week {week}."
        )
    snapshot = assemble_weekly_snapshot(
        league=league,
        season=season,
        week=week,
        week_start=dates["start"],
        week_end=dates["end"],
    )
    return {"league": league, "snapshot": dump_model(snapshot)}


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


def get_current_recaps(*, store: RecapStore, slug: str) -> dict[str, Any]:
    """N-3: league metadata + its configured season + that season's archive.

    The season comes from ``leagues.espn_season`` so a league configured for
    a different season than the deployment default resolves correctly.
    Archive is empty (not an error) for non-public leagues, matching how the
    pages degrade when the archive endpoint is unavailable.
    """
    league = _league_or_404(store, slug)
    raw_season = league.get("espn_season")
    if raw_season is None:
        raise HTTPException(
            status_code=500,
            detail=f"League '{slug}' has no espn_season configured.",
        )
    season = int(raw_season)
    if league.get("visibility") == "public":
        archive = store.list_published(league["id"], season)
    else:
        archive = []
    return {
        "league": {
            "slug": league.get("slug"),
            "name": league.get("name"),
            "logo_url": league.get("logo_url"),
            "accent_color": league.get("accent_color"),
            "visibility": league.get("visibility"),
        },
        "season": season,
        "archive": archive,
    }


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
