import pandas as pd
from espn_api.basketball import League

from backend.config import ESPN_S2, SWID
from backend.league.data_feed import LOWER_IS_BETTER_STATS
from backend.league.scoreboard import WeeklyScoreboard
from backend.league.scoreboard_fetch import (
    league_matchups_of,
    matchup_scores_df,
    schedule_df,
)


class MyLeague(League):
    def __init__(self, league_id, year, espn_s2=None, swid=None):
        espn_s2 = ESPN_S2 if espn_s2 is None else espn_s2
        swid = SWID if swid is None else swid
        super().__init__(league_id, year, espn_s2=espn_s2, swid=swid)
        # Schedules can differ in length depending on playoffs/bye; use max.
        self.length_of_schedule = max((len(team.schedule) for team in self.teams), default=0)
        self.league_matchups = self.get_all_matchups()
        self.schedule = self.get_schedule()
        # ESPN's `currentMatchupPeriod` can exceed the schedule length (e.g. playoffs/champ week),
        # but our `league_matchups` dict is built strictly from the schedule weeks.
        try:
            max_available_week = max(int(k) for k in self.league_matchups.keys()) if self.league_matchups else 0
        except Exception:
            max_available_week = 0
        max_available_week = max_available_week or int(self.length_of_schedule)
        self.effective_current_week = max(1, min(int(self.currentMatchupPeriod), int(max_available_week)))
        self.current_scoreboard = self.league_matchups.get(self.effective_current_week, [])
        self.stat_categories = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'FG%', 'FT%', 'TO']

    def _get_all_pro_schedule(self):
        """Skip the NBA pro-schedule fetch (~420 KB, one of espn-api's 4 calls
        during construction) — no attribute here or in any consumer (draft
        optimizer, schedule/current-week-matchups endpoints) reads
        ``self.pro_schedule`` or per-player game-day data; verified live that
        team/roster/draft construction is unaffected without it."""
        return {}

    def get_all_matchups(self):
        return league_matchups_of(self)

    def get_all_matchup_data(self):
        # Tidy `[Week, Team, <cats>]`, one row per team per played matchup across
        # every scheduled week (incl. playoffs), via the shared shaping helper.
        return matchup_scores_df(self, self.league_matchups, self.stat_categories)

    def _scoreboard(self, all_data=None):
        """A :class:`WeeklyScoreboard` over this league's matchup data.

        ``all_data`` lets callers (and tests) inject a pre-shaped table; it
        defaults to :meth:`get_all_matchup_data`.
        """
        data = self.get_all_matchup_data() if all_data is None else all_data
        return WeeklyScoreboard(
            data, self.schedule, self.stat_categories, LOWER_IS_BETTER_STATS
        )

    def get_schedule(self):
        return schedule_df(self)

    def get_universe_wins(self, include_current=False, weeks=None, order_by='Total Wins', ascending=False,
                          additional_team_stats=None):
        """All-play standings over ``weeks`` (defaults to weeks played so far).

        Thin wrapper over :class:`~backend.league.scoreboard.WeeklyScoreboard`,
        which owns the vectorized all-play computation. ``additional_team_stats``
        maps ``(week, team) -> {stat: value}`` for the draft what-if path.
        """
        if weeks is None:
            weeks = range(1, self.currentMatchupPeriod + include_current)
        return self._scoreboard().all_play(
            weeks=weeks, order_by=order_by, ascending=ascending,
            inject=additional_team_stats or None,
        )

    def get_wins(self, team_name, week, additional_team_stats=None, all_data=None):
        """One team's raw all-play row for one week (empty frame on a bye).

        Delegates to :meth:`WeeklyScoreboard.team_week`; ``all_data`` overrides
        the matchup table (used by tests and the historical call path)."""
        return self._scoreboard(all_data).team_week(
            team_name, week, inject=additional_team_stats,
        )

    def get_current_week_matchups(self):
        matchups = {
            'Week': [],
            'Home Teams': [],
            'Away Teams': []
        }
        for matchup in self.current_scoreboard:
            matchups['Home Teams'].append(matchup.home_team.team_name)
            matchups['Away Teams'].append(matchup.away_team.team_name)
            matchups['Week'].append(self.currentMatchupPeriod)
        return pd.DataFrame(matchups)


