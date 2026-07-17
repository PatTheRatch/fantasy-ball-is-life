"""Snapshot worker: pull ESPN → write league_state_snapshots.

P-4: Credentials are sourced from the ``leagues`` table (encrypted at
rest) instead of monkeypatching module-level ``config.LEAGUE_ID`` /
``SWID`` / ``ESPN_S2`` globals. ``connect()`` accepts explicit
``(league_id, season, swid, espn_s2)`` kwargs.

P-3a (shadow mode): writes snapshots but NOTHING reads from them yet.
P-3b (read-path flip): /league/* endpoints and assemble_weekly_snapshot()
read from stored snapshots instead of calling ESPN live.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from backend.league.credentials import get_league_context
from backend.recaps.store import RecapStore

logger = logging.getLogger(__name__)

PHASES = [
    "settings",
    "standings",
    "scoreboard",
    "transactions",
    "power_rankings",
    "season_stats",
]


def _upsert_phase(
    store: RecapStore,
    league_id: str,
    season: int,
    week: int,
    phase: str,
    payload: object,
) -> None:
    """UPSERT one phase row with a per-phase ``fetched_at`` timestamp."""
    import json

    now = datetime.now(timezone.utc).isoformat()
    store._request(
        "POST",
        "league_state_snapshots",
        json={
            "league_id": league_id,
            "season": season,
            "week": week,
            "phase": phase,
            "payload_json": payload,
            "fetched_at": now,
        },
        prefer="resolution=merge-duplicates",
    )


def refresh_league(*, slug: str | None = None) -> dict[str, str]:
    """Refresh all phases for one league from live ESPN.

    Credentials are resolved from the DB (``get_league_context()``).
    ``connect()`` receives explicit ``(league_id, season, swid, espn_s2)``
    — no more monkeypatching of module-level globals.

    Each phase is independently wrapped — one failure does not block the
    others. Returns a dict of ``{phase: "ok" | "error: ..."}``.
    """
    ctx = get_league_context(slug=slug)
    if ctx is None:
        raise RuntimeError(
            f"No league found{' for slug ' + slug if slug else ''} in the database. "
            "Run `python -m backend.scripts.seed_league` to seed."
        )

    league_id = ctx.league_id
    season = ctx.espn_season
    espn_league_id = ctx.espn_league_id
    swid = ctx.swid
    espn_s2 = ctx.espn_s2

    # Determine current ESPN week
    from backend.league.data_feed import connect
    from espn_api.basketball import League

    logger.info("Refreshing league %s (slug=%s, season=%s)…", league_id, ctx.slug, season)

    handles = connect(
        league_id=espn_league_id,
        season=season,
        swid=swid,
        espn_s2=espn_s2,
    )
    week = handles.league.currentMatchupPeriod

    store = RecapStore()
    results: dict[str, str] = {}

    from backend.api.routers import league as league_api

    # ── settings ───────────────────────────────────────────────────────────
    phase = "settings"
    try:
        raw = league_api.league_settings()
        # strip the P-3b envelope if present
        payload = raw.get("data", raw.get("settings", raw))
        _upsert_phase(store, league_id, season, week, phase, payload)
        results[phase] = "ok"
    except Exception as exc:
        results[phase] = f"error: {exc}"
        logger.warning("Phase '%s' failed: %s", phase, exc)

    # ── standings ──────────────────────────────────────────────────────────
    phase = "standings"
    try:
        raw = league_api.league_standings()
        payload = raw.get("data", raw)
        _upsert_phase(store, league_id, season, week, phase, payload)
        results[phase] = "ok"
    except Exception as exc:
        results[phase] = f"error: {exc}"
        logger.warning("Phase '%s' failed: %s", phase, exc)

    # ── scoreboard ─────────────────────────────────────────────────────────
    phase = "scoreboard"
    try:
        raw = league_api.scoreboard_current(scoring_period=week)
        payload = raw.get("data", raw)
        _upsert_phase(store, league_id, season, week, phase, payload)
        results[phase] = "ok"
    except Exception as exc:
        results[phase] = f"error: {exc}"
        logger.warning("Phase '%s' failed: %s", phase, exc)

    # ── transactions ───────────────────────────────────────────────────────
    phase = "transactions"
    try:
        raw = league_api.transactions_week(scoring_period=week)
        payload = raw.get("data", raw)
        _upsert_phase(store, league_id, season, week, phase, payload)
        results[phase] = "ok"
    except Exception as exc:
        results[phase] = f"error: {exc}"
        logger.warning("Phase '%s' failed: %s", phase, exc)

    # ── power_rankings ─────────────────────────────────────────────────────
    phase = "power_rankings"
    try:
        weeks_csv = ",".join(str(v) for v in range(1, week + 1))
        raw = league_api.power_rankings(weeks=weeks_csv, recent_weeks=3)
        payload = raw.get("data", raw)
        _upsert_phase(store, league_id, season, week, phase, payload)
        results[phase] = "ok"
    except Exception as exc:
        results[phase] = f"error: {exc}"
        logger.warning("Phase '%s' failed: %s", phase, exc)

    # ── season_stats ───────────────────────────────────────────────────────
    phase = "season_stats"
    try:
        weeks_csv = ",".join(str(v) for v in range(1, week + 1))
        raw = league_api.season_stats(weeks=weeks_csv)
        payload = raw.get("data", raw)
        _upsert_phase(store, league_id, season, week, phase, payload)
        results[phase] = "ok"
    except Exception as exc:
        results[phase] = f"error: {exc}"
        logger.warning("Phase '%s' failed: %s", phase, exc)

    elapsed = time.perf_counter()
    logger.info(
        "Refresh complete for %s in %.2fs: %s",
        ctx.slug,
        elapsed,
        ", ".join(f"{p}={s}" for p, s in results.items()),
    )
    return results
