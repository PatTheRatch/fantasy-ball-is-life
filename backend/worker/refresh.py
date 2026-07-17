"""Snapshot worker: patch ESPN config → call league API → store computed output.

Shadow mode (P-3a): writes snapshots but NOTHING reads from them yet.
Read-path flip is P-3b.

Per P-3's architecture: the worker calls the EXACT existing endpoint-level
functions (league_api.power_rankings, league_api.season_stats, etc.) so
the heavy compute (get_universe_wins) runs OFF the request path. P-3b's
read endpoints become SELECT payload → return.

Each phase is independently wrapped — one failure does not block the
others. A failed refresh keeps the previous snapshot (staleness, never
a 500 on reads).
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator

from backend.recaps.store import RecapStore

logger = logging.getLogger(__name__)

PHASES = [
    "standings",
    "power_rankings",
    "scoreboard",
    "transactions",
    "season_stats",
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


@contextmanager
def _patched_espn_config(
    league_id: int,
    season: int,
    swid: str,
    espn_s2: str,
) -> Generator[None, None, None]:
    """Temporarily swap ESPN credentials in the module-level config.

    The league API functions read ``config.LEAGUE_ID`` etc. at import time;
    we patch both the config source AND the modules that imported them so
    all call paths see this league's credentials. Restored on exit.
    """
    import backend.config as config
    import backend.league.data_feed as df
    import backend.api.deps as deps

    # Save originals across all modules that bind these names
    originals = {
        "config": {
            "LEAGUE_ID": config.LEAGUE_ID,
            "SEASON": config.SEASON,
            "SWID": config.SWID,
            "ESPN_S2": config.ESPN_S2,
        },
        "df": {
            "LEAGUE_ID": df.LEAGUE_ID,
            "SEASON": df.SEASON,
            "SWID": df.SWID,
            "ESPN_S2": df.ESPN_S2,
        },
        "deps": {
            "LEAGUE_ID": deps.LEAGUE_ID,
            "SEASON": deps.SEASON,
        },
    }

    try:
        # config module
        config.LEAGUE_ID = league_id
        config.SEASON = season
        config.SWID = swid
        config.ESPN_S2 = espn_s2

        # data_feed module (imported from config at module top)
        df.LEAGUE_ID = league_id
        df.SEASON = season
        df.SWID = swid
        df.ESPN_S2 = espn_s2

        # deps module (imported from config at module top)
        deps.LEAGUE_ID = league_id
        deps.SEASON = season

        yield
    finally:
        config.LEAGUE_ID = originals["config"]["LEAGUE_ID"]
        config.SEASON = originals["config"]["SEASON"]
        config.SWID = originals["config"]["SWID"]
        config.ESPN_S2 = originals["config"]["ESPN_S2"]

        df.LEAGUE_ID = originals["df"]["LEAGUE_ID"]
        df.SEASON = originals["df"]["SEASON"]
        df.SWID = originals["df"]["SWID"]
        df.ESPN_S2 = originals["df"]["ESPN_S2"]

        deps.LEAGUE_ID = originals["deps"]["LEAGUE_ID"]
        deps.SEASON = originals["deps"]["SEASON"]


def refresh_league(
    *,
    league_id: str,
    espn_league_id: int,
    espn_season: int,
    espn_s2: str,
    swid: str,
) -> dict[str, str]:
    """Patch ESPN config → call league API → write all 6 computed phases.

    Returns {phase: status_string} for logging.
    Each phase is independently wrapped — one failure never blocks the rest.
    """
    store = RecapStore()
    results: dict[str, str] = {}

    with _patched_espn_config(
        league_id=espn_league_id,
        season=espn_season,
        swid=swid,
        espn_s2=espn_s2,
    ):
        from backend.api.routers import league as league_api

        # Resolve current week FIRST (needed for most phases)
        try:
            handles = league_api._handles()
            current_week = int(getattr(handles.league, "current_week", 1) or 1)
        except Exception as exc:
            logger.error("refresh_league(%s): connect failed — %s", league_id, exc)
            return {"connect": f"error: {exc}"}

        weeks_csv = ",".join(str(w) for w in range(1, current_week + 1))

        for phase in PHASES:
            started = time.monotonic()
            fetched_at = datetime.now(timezone.utc).isoformat()
            try:
                payload = _load_phase(phase, league_api, current_week, weeks_csv)
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
                logger.info(
                    "refresh_league(%s): %s ok (%.1fs)", league_id, phase, elapsed
                )
                results[phase] = f"ok ({elapsed:.1f}s)"
            except Exception as exc:
                elapsed = time.monotonic() - started
                logger.warning(
                    "refresh_league(%s): %s FAILED (%.1fs) — %s",
                    league_id, phase, elapsed, exc,
                )
                results[phase] = f"error: {exc}"

    return results


# ── Phase loaders (call the EXACT existing endpoint-level functions) ───────────


def _load_phase(
    phase: str,
    league_api,
    week: int,
    weeks_csv: str,
) -> list[dict[str, Any]] | dict[str, Any]:
    """Dispatch to the exact existing league API function. Zero new logic."""
    if phase == "standings":
        return league_api.league_standings()

    if phase == "power_rankings":
        return league_api.power_rankings(weeks=weeks_csv, recent_weeks=3)

    if phase == "scoreboard":
        return league_api.scoreboard_current(scoring_period=week)

    if phase == "transactions":
        return league_api.transactions_week(scoring_period=week)

    if phase == "season_stats":
        return league_api.season_stats(weeks=weeks_csv)

    if phase == "settings":
        return league_api.league_settings()

    raise ValueError(f"Unknown phase: {phase}")
