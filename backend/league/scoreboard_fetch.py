"""Narrow ESPN fetch + shaping for the power-rankings / season-stats path.

A full ``MyLeague`` construction fires 4 ESPN calls (~2.4 MB): the box-score
league view, the pro-player name map, the NBA pro schedule, and the draft. Power
rankings and season stats need *only* the first — the per-team weekly category
scores. ``ScoreboardLeague`` fetches just that one view (skipping ~740 KB / 3
calls) using espn-api's own box-score parsing, and ``fetch_scoreboard`` shapes
it into a :class:`~backend.league.scoreboard.WeeklyScoreboard`.

The shaping helpers (``league_matchups_of`` / ``matchup_scores_df`` /
``schedule_df``) are the single source of "espn ``League`` → tidy table" and are
reused by ``MyLeague`` so there is one implementation of the shape.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import pandas as pd
from espn_api.basketball import League

from backend.league.credentials import get_league_context, _require_context
from backend.league.data_feed import LOWER_IS_BETTER_STATS
from backend.league.scoreboard import (
    DEFAULT_STAT_CATEGORIES,
    WeeklyScoreboard,
)


class ScoreboardLeague(League):
    """A ``League`` that fetches only the box-score view needed for all-play.

    Overrides the three loaders whose data the scoreboard never touches
    (players, pro schedule, draft) to no-ops, so construction makes a single
    ESPN request instead of four.
    """

    def __init__(self, league_id, year, espn_s2=None, swid=None):
        if espn_s2 is None or swid is None:
            ctx = get_league_context() or _require_context()
            espn_s2 = ctx.espn_s2 if espn_s2 is None else espn_s2
            swid = ctx.swid if swid is None else swid
        super().__init__(league_id, year, espn_s2=espn_s2, swid=swid, fetch_league=False)
        data = self._fetch_league()   # box-score view only (players skipped below)
        self._fetch_teams(data)       # espn-api parses matchup category scores

    def _fetch_players(self):  # noqa: D401 - only for draft/transaction name maps
        """Skip the pro-player name map (call #2) — unused by all-play."""
        self.player_map = {}

    def _get_all_pro_schedule(self):
        """Skip the NBA pro schedule (call #3) — unused by all-play."""
        return {}

    def _fetch_draft(self):
        """Skip the draft (call #4) — unused by all-play."""
        return


# --- shaping: espn League -> tidy table ---------------------------------------

def league_matchups_of(league: Any) -> dict[int, list]:
    """``{week: [matchup, ...]}`` keyed once per matchup (home side), 1-indexed."""
    all_matchups: dict[int, list] = {}
    for team in league.teams:
        for i, matchup in enumerate(team.schedule):
            if matchup.home_team.team_name == team.team_name:
                all_matchups.setdefault(i + 1, []).append(matchup)
    return all_matchups


def _max_week(league_matchups: dict[int, list], fallback: int) -> int:
    try:
        if league_matchups:
            return max(int(k) for k in league_matchups.keys())
    except Exception:
        pass
    return max(int(fallback or 0), 1)


def matchup_scores_df(
    league: Any,
    league_matchups: dict[int, list],
    stat_categories: Sequence[str] = DEFAULT_STAT_CATEGORIES,
) -> pd.DataFrame:
    """Tidy ``[Week, Team, <cats>]`` — one row per team per played matchup.

    Only weeks present in ``league_matchups`` are emitted; a team/side with no
    scored categories yet (future/unplayed) is skipped rather than zero-filled.
    """
    length = max((len(t.schedule) for t in league.teams), default=0)
    max_w = _max_week(league_matchups, length)
    cats = list(stat_categories)
    rows = []
    for w in range(1, max_w + 1):
        for mu in league_matchups.get(w, []):
            for side in ("home", "away"):
                team = getattr(mu, f"{side}_team").team_name
                team_cats = getattr(mu, f"{side}_team_cats")
                if not team_cats:
                    continue
                rec = {"Week": w, "Team": team}
                for s in cats:
                    rec[s] = team_cats[s]["score"]
                rows.append(rec)
    df = pd.DataFrame(rows)
    if not df.empty:
        df["Week"] = pd.to_numeric(df["Week"])
    return df


def schedule_df(league: Any) -> pd.DataFrame:
    """Tidy ``[Week, Team, Opponent]`` from every team's schedule."""
    sched: dict[str, list] = {"Week": [], "Team": [], "Opponent": []}
    for team in league.teams:
        for i, matchup in enumerate(team.schedule):
            sched["Week"].append(i + 1)
            sched["Team"].append(team.team_name)
            sched["Opponent"].append(
                matchup.away_team.team_name
                if matchup.home_team.team_name == team.team_name
                else matchup.home_team.team_name
            )
    return pd.DataFrame(sched)


def scoreboard_from_league(
    league: Any,
    stat_categories: Sequence[str] = DEFAULT_STAT_CATEGORIES,
    lower_is_better: Iterable[str] = LOWER_IS_BETTER_STATS,
) -> WeeklyScoreboard:
    """Build a :class:`WeeklyScoreboard` from any espn-api ``League``."""
    lm = league_matchups_of(league)
    scores = matchup_scores_df(league, lm, stat_categories)
    schedule = schedule_df(league)
    return WeeklyScoreboard(scores, schedule, stat_categories, lower_is_better)


def fetch_scoreboard(
    league_id: int,
    year: int,
    stat_categories: Sequence[str] = DEFAULT_STAT_CATEGORIES,
    lower_is_better: Iterable[str] = LOWER_IS_BETTER_STATS,
) -> WeeklyScoreboard:
    """Narrow single-call fetch → ready-to-query ``WeeklyScoreboard``."""
    league = ScoreboardLeague(league_id, year)
    return scoreboard_from_league(league, stat_categories, lower_is_better)
