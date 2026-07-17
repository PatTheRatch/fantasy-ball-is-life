"""Snapshot worker: pull ESPN → write league_state_snapshots.

Shadow mode (P-3a): stores RAW ESPN data for each phase. Computation
(power rankings, scoped standings, canonical matchups) stays in
``assemble_weekly_snapshot()`` — in P-3b it reads from these snapshots
instead of calling live ESPN.

Each phase is independently wrapped — one failure does not block the
others. A failed refresh keeps the previous snapshot (staleness, never
a 500 on reads).

Per P-3's architecture: the worker calls the EXACT existing data_feed
functions. It only moves WHERE they run.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from backend.recaps.store import RecapStore
from backend.league.data_feed import (
    ESPNHandles,
    standings_df,
    week_transactions,
)
from espn_api.basketball import League

logger = logging.getLogger(__name__)

PHASES = [
    "standings",
    "scoreboard",
    "transactions",
    "settings",
]


def upsert_phase(
    *,
    store: RecapStore,
    league_id: str,
    season: int,
    week: int,
    phase: str,
    payload: dict[str, Any] | list[dict[str, Any]],
    fetched_at: str,
) -> dict[str, Any]:
    """Write one phase row. Unique constraint makes this a natural upsert."""
    return store._request(
        "POST",
        "league_state_snapshots",
        json={
            "league_id": league_id,
            "season": season,
            "week": week,
            "phase": phase,
            "payload_json": payload,
            "fetched_at": fetched_at,
        },
        prefer="resolution=merge-duplicates",
    )


def refresh_league(
    *,
    league_id: str,
    espn_league_id: int,
    espn_season: int,
    espn_s2: str,
    swid: str,
) -> dict[str, str]:
    """Pull ESPN → write all phases. One failure never blocks the rest.

    Returns {phase: status_string} for logging.
    """
    # ── Connect ESPN ──────────────────────────────────────────────────────────
    try:
        league = League(
            league_id=espn_league_id,
            year=espn_season,
            espn_s2=espn_s2,
            swid=swid,
        )
        handles = ESPNHandles(league=league)
    except Exception as exc:
        logger.error("refresh_league(%s): connect failed — %s", league_id, exc)
        return {"connect": f"error: {exc}"}

    current_week = _current_week(league)

    store = RecapStore()
    results: dict[str, str] = {}

    for phase in PHASES:
        started = time.monotonic()
        fetched_at = datetime.now(timezone.utc).isoformat()
        try:
            payload = _load_phase(phase, handles, current_week)
            upsert_phase(
                store=store,
                league_id=league_id,
                season=espn_season,
                week=current_week,
                phase=phase,
                payload=payload,
                fetched_at=fetched_at,
            )
            elapsed = time.monotonic() - started
            logger.info("refresh_league(%s): %s ok (%.1fs)", league_id, phase, elapsed)
            results[phase] = f"ok ({elapsed:.1f}s)"
        except Exception as exc:
            elapsed = time.monotonic() - started
            logger.warning(
                "refresh_league(%s): %s FAILED (%.1fs) — %s",
                league_id, phase, elapsed, exc,
            )
            results[phase] = f"error: {exc}"

    return results


# ── Phase loaders (reuse existing data_feed functions) ────────────────────────


def _load_phase(
    phase: str,
    handles: ESPNHandles,
    week: int,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Dispatch to the exact existing loader. Zero new analytics logic."""
    if phase == "standings":
        return _load_standings(handles)

    if phase == "scoreboard":
        return _load_scoreboard(handles, week)

    if phase == "transactions":
        return _load_transactions(handles, week)

    if phase == "settings":
        return _load_settings(handles, week)

    raise ValueError(f"Unknown phase: {phase}")


def _load_standings(handles: ESPNHandles) -> list[dict[str, Any]]:
    """standings_df — the exact existing loader."""
    df = standings_df(handles)
    return df.to_dict(orient="records")


def _load_scoreboard(handles: ESPNHandles, week: int) -> list[dict[str, Any]]:
    """Raw ESPN box scores for the current matchup period."""
    boxes_df = handles.league.box_scores(matchup_period=week)
    if boxes_df is None or (hasattr(boxes_df, "empty") and boxes_df.empty):
        return []
    return boxes_df.reset_index().to_dict(orient="records")


def _load_transactions(handles: ESPNHandles, week: int) -> list[dict[str, Any]]:
    """week_transactions — the exact existing loader."""
    return week_transactions(handles, scoring_period=week)


def _load_settings(handles: ESPNHandles, week: int) -> dict[str, Any]:
    """League settings (acquisition type, playoff config, season length)."""
    try:
        settings = handles.league.settings
        return {
            "acquisition_type": str(getattr(settings, "acquisition_type", "")),
            "trade_deadline": str(getattr(settings, "trade_deadline", "")),
            "playoff_team_count": getattr(settings, "playoff_team_count", None),
            "playoff_start": getattr(settings, "playoff_start", None),
            "schedule": {
                "total_matchups": (
                    getattr(settings, "schedule", {}).get("total_matchups", week)
                    if hasattr(settings, "schedule")
                    else week
                ),
            },
        }
    except Exception:
        return {"week": week}


def _current_week(league) -> int:
    try:
        return getattr(league, "current_week", 1) or 1
    except Exception:
        return 1
