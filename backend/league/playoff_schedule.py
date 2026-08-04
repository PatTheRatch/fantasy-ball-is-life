"""Playoff-weeks schedule planner (spec: PLAYOFF_SCHEDULE_PLANNER.md).

Which NBA teams play the most games during THIS league's playoff weeks —
derived from the league's own ESPN settings (never hardcoded), the
season-keyed matchup-week calendar, and the ESPN pro schedule (whose game
entries carry real timestamps).

Pure functions here; the endpoint in ``backend/api/routers/league.py`` wires
snapshot-stored settings + ``get_pro_schedule()`` into them.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional

from backend.league.data_feed import _epoch_ms_to_iso_date


def playoff_rounds(playoff_team_count: Optional[int]) -> int:
    """Bracket rounds for an N-team playoff (4→2, 6→3 with byes, 8→3)."""
    try:
        n = int(playoff_team_count or 0)
    except (TypeError, ValueError):
        return 0
    if n < 2:
        return 0
    return math.ceil(math.log2(n))


def derive_playoff_weeks(
    *,
    reg_season_count: Optional[int],
    playoff_team_count: Optional[int],
    playoff_matchup_period_length: Optional[int],
    calendar_weeks: Mapping[int, Mapping[str, str]],
) -> List[int]:
    """The league's playoff matchup periods, from its own ESPN settings.

    ``reg_season_count`` regular-season periods, then
    ``rounds x playoff_matchup_period_length`` playoff periods — intersected
    with the calendar so a mis-sized setting can't invent weeks that don't
    exist. Falls back to "every calendar week after the regular season" when
    the playoff shape is unknown, and to ``[]`` (honest empty, not a guess)
    when even ``reg_season_count`` is missing.
    """
    try:
        reg = int(reg_season_count or 0)
    except (TypeError, ValueError):
        reg = 0
    if reg <= 0:
        return []

    rounds = playoff_rounds(playoff_team_count)
    try:
        length = int(playoff_matchup_period_length or 0)
    except (TypeError, ValueError):
        length = 0

    weeks = sorted(int(w) for w in calendar_weeks)
    if rounds > 0 and length > 0:
        last = reg + rounds * length
        return [w for w in weeks if reg < w <= last]
    return [w for w in weeks if w > reg]


def count_games_by_team(
    pro_teams: List[Dict[str, Any]],
    week_windows: Mapping[int, Mapping[str, str]],
) -> List[Dict[str, Any]]:
    """Games per NBA team per matchup week, from the ESPN pro schedule.

    ``pro_teams`` is ``settings.proTeams`` from ``get_pro_schedule()``: each
    team carries ``proGamesByScoringPeriod`` whose game entries have real
    epoch-ms ``date`` stamps (the only reliable field — scoringPeriodId does
    not map cleanly to calendar days, see ``_scoring_periods_for_week``).
    Games are deduped per team by game id (a game can surface under more
    than one scoring-period bucket).

    Returns one row per team: ``{pro_team, games_by_week, total}``, sorted
    most-total-games first (the draft-day ordering).
    """
    if not week_windows:
        return []

    windows = {
        int(w): (str(rng["start"]), str(rng["end"]))
        for w, rng in week_windows.items()
    }

    rows: List[Dict[str, Any]] = []
    for team in pro_teams or []:
        abbrev = str(team.get("abbrev") or team.get("abbreviation") or "").upper()
        if not abbrev:
            continue
        counts: Dict[str, int] = {str(w): 0 for w in sorted(windows)}
        seen_games: set = set()
        for games in (team.get("proGamesByScoringPeriod") or {}).values():
            for game in games or []:
                game_date = _epoch_ms_to_iso_date(game.get("date"))
                if not game_date:
                    continue
                game_key = game.get("id") or f"{game_date}:{game.get('awayProTeamId')}@{game.get('homeProTeamId')}"
                if game_key in seen_games:
                    continue
                seen_games.add(game_key)
                for w, (start, end) in windows.items():
                    if start <= game_date <= end:
                        counts[str(w)] += 1
                        break
        rows.append(
            {
                "pro_team": abbrev,
                "games_by_week": counts,
                "total": sum(counts.values()),
            }
        )

    rows.sort(key=lambda r: (-r["total"], r["pro_team"]))
    return rows


def build_playoff_schedule(
    *,
    settings: Optional[Mapping[str, Any]],
    calendar_weeks: Mapping[int, Mapping[str, str]],
    pro_schedule: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Assemble the endpoint payload; empty states are honest, never errors."""
    settings = settings or {}
    weeks = derive_playoff_weeks(
        reg_season_count=settings.get("reg_season_count"),
        playoff_team_count=settings.get("playoff_team_count"),
        playoff_matchup_period_length=settings.get("playoff_matchup_period_length"),
        calendar_weeks=calendar_weeks,
    )
    if not weeks:
        return {"playoff_weeks": [], "teams": [], "reason": "settings_unavailable"}

    windows = {w: calendar_weeks[w] for w in weeks if w in calendar_weeks}
    pro_teams = ((pro_schedule or {}).get("settings") or {}).get("proTeams") or []
    teams = count_games_by_team(pro_teams, windows)
    if not teams:
        # Pre-release (schedule not out yet) or ESPN hiccup — honest empty.
        return {"playoff_weeks": weeks, "teams": [], "reason": "schedule_unavailable"}

    return {"playoff_weeks": weeks, "teams": teams}
