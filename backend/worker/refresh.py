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

from backend.league.credentials import resolve_league_context
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
        params={"on_conflict": "league_id,season,phase"},
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
    ctx = resolve_league_context(slug=slug)
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

    # ── Call live ESPN via data_feed, NOT the flipped league_api endpoints ──
    # The league_api.* functions were flipped in P-3b to read from stored
    # snapshots. The refresh worker is the thing that POPULATES those
    # snapshots, so it must call data_feed directly to avoid a circular
    # read-from-empty cycle.
    from backend.league import data_feed as feed
    import pandas as pd

    # ── settings ───────────────────────────────────────────────────────────
    phase = "settings"
    try:
        raw_settings = handles.league.settings
        payload: dict[str, Any] = {
            "name": raw_settings.name,
            "reg_season_count": raw_settings.reg_season_count,
            "playoff_team_count": raw_settings.playoff_team_count,
            "playoff_matchup_period_length": raw_settings.playoff_matchup_period_length,
            "team_count": raw_settings.team_count,
            "scoring_type": str(raw_settings.scoring_type),
        }
        _upsert_phase(store, league_id, season, week, phase, payload)
        results[phase] = "ok"
    except Exception as exc:
        results[phase] = f"error: {exc}"
        logger.warning("Phase '%s' failed: %s", phase, exc)

    # ── standings ──────────────────────────────────────────────────────────
    phase = "standings"
    try:
        from backend.recaps.assemble import canonical_matchups
        from collections import defaultdict
        records: dict[str, dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "ties": 0})

        for w in range(1, week + 1):
            try:
                df = get_current_scoreboard(handles, scoring_period=w)
                rows = df.to_dict(orient="records") if not df.empty else []
                matchups = canonical_matchups(rows, w)
            except Exception:
                continue
            for m in matchups:
                winner = m.get("winner", "")
                for side in ("home", "away"):
                    team = m.get(f"{side}_team", "")
                    if not team:
                        continue
                    if winner == team:
                        records[team]["wins"] += 1
                    elif winner == "Tie" or not winner:
                        records[team]["ties"] += 1
                    else:
                        records[team]["losses"] += 1

        standings_rows: list[dict[str, Any]] = []
        for team, rec in records.items():
            total = rec["wins"] + rec["losses"] + rec["ties"]
            wp = (rec["wins"] / total * 100) if total > 0 else 0.0
            standings_rows.append({
                "team_name": team, "wins": rec["wins"],
                "losses": rec["losses"], "ties": rec["ties"],
                "win_pct": round(wp, 1)
            })
        standings_rows.sort(key=lambda r: (-r["win_pct"], -r["wins"]))
        for i, r in enumerate(standings_rows):
            r["standing"] = i + 1

        _upsert_phase(store, league_id, season, week, phase, standings_rows)
        results[phase] = "ok"
    except Exception as exc:
        results[phase] = f"error: {exc}"
        logger.warning("Phase '%s' failed: %s", phase, exc)

    # ── scoreboard ─────────────────────────────────────────────────────────
    phase = "scoreboard"
    try:
        from backend.league.data_feed import get_current_scoreboard
        import math
        df = get_current_scoreboard(handles, scoring_period=week)
        scoreboard_rows: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            clean: dict[str, Any] = {}
            for k, v in row.items():
                if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                    clean[k] = None
                elif isinstance(v, float):
                    clean[k] = round(v, 4)  # sanity: trim float precision
                else:
                    clean[k] = v if not pd.isna(v) else None
            scoreboard_rows.append(clean)
        _upsert_phase(store, league_id, season, week, phase, scoreboard_rows)
        results[phase] = "ok"
    except Exception as exc:
        results[phase] = f"error: {exc}"
        logger.warning("Phase '%s' failed: %s", phase, exc)

    # ── transactions ───────────────────────────────────────────────────────
    phase = "transactions"
    try:
        # `week` is the fantasy matchup period (league.currentMatchupPeriod),
        # NOT an ESPN daily scoring period. week_transactions() takes a single
        # daily scoring_period; passing the fantasy week here fetches one wrong
        # day. week_transactions_for_week() resolves the week's real scoring-
        # period window and fetches all transactions within it.
        txn_rows = feed.week_transactions_for_week(handles, week=week)
        _upsert_phase(store, league_id, season, week, phase, txn_rows or [])
        results[phase] = "ok"
    except Exception as exc:
        results[phase] = f"error: {exc}"
        logger.warning("Phase '%s' failed: %s", phase, exc)

    # ── power_rankings ─────────────────────────────────────────────────────
    phase = "power_rankings"
    try:
        from backend.recaps.assemble import _live_power_rankings
        weeks_csv = ",".join(str(w) for w in range(1, week + 1))
        rankings = _live_power_rankings(weeks_csv, recent_weeks=3)
        _upsert_phase(store, league_id, season, week, phase, rankings)
        results[phase] = "ok"
    except Exception as exc:
        results[phase] = f"error: {exc}"
        logger.warning("Phase '%s' failed: %s", phase, exc)

    # ── season_stats ───────────────────────────────────────────────────────
    phase = "season_stats"
    try:
        # Season stats computation is complex (all_play over multiple weeks).
        # For now, store an empty list and fix properly in a follow-up.
        # The StandingsTab computes per-week averages client-side from totals,
        # and the Power Rankings tab uses power_rankings data directly.
        _upsert_phase(store, league_id, season, week, phase, [])
        results[phase] = "ok (deferred)"
    except Exception as exc:
        results[phase] = f"error: {exc}"
        logger.warning("Phase '%s' failed: %s", phase, exc)

    return results
