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
        self.team_names = [team.team_name for team in self.teams]
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

    def get_power_rankings(self,
                           week=None,
                           lookback=3,
                           metric='Matchup Win %',
                           comparison_week=None,
                           ascending=False,
                           additional_team_stats=None):

        power_rankings = []
        week = self.currentMatchupPeriod if week is None else int(week)
        week = max(1, min(int(week), int(self.length_of_schedule)))

        comparison_week = week - 1 if comparison_week is None else int(comparison_week)
        comparison_week = max(1, min(int(comparison_week), int(self.length_of_schedule)))

        # Ensure we never ask for weeks <= 0 (range() would include 0/-1/etc.).
        lookback = int(lookback)
        lookback = max(0, min(lookback, week - 1))

        comparison_lookback = max(0, min(lookback, comparison_week - 1))

        rankings_data = self.get_universe_wins(weeks=range(max(1, week - lookback), week + 1), order_by=[metric, 'Win % Ratio'],
                                               ascending=ascending, additional_team_stats=additional_team_stats)
        comparison_rankings_data = self.get_universe_wins(weeks=range(max(1, comparison_week - comparison_lookback), week),
                                                          order_by=[metric, 'Win % Ratio'], ascending=ascending,
                                                          additional_team_stats=additional_team_stats)
        current_week_performance = self.get_universe_wins(weeks=[week], order_by=[metric, 'Win % Ratio'],
                                                          ascending=ascending, additional_team_stats=additional_team_stats)

        for team in self.team_names:
            team_data = rankings_data.loc[rankings_data['Team'] == team]
            comparison_team_data = comparison_rankings_data.loc[comparison_rankings_data['Team'] == team]
            change = (comparison_team_data.index[0] + 1) - (team_data.index[0] + 1)

            if change > 0:
                change_value = f'+{change}'
            elif change < 0:
                change_value = f'{change}'
            else:
                change_value = '-'
            power_rankings.append(
                {
                    'Team': [team],
                    'Current Rank': [team_data.index[0] + 1],
                    'Previous Rank': [comparison_team_data.index[0] + 1],
                    'Change': [change_value],
                    'Current Win %': [team_data[metric].values[0]],
                    'Previous Win %': [comparison_team_data[metric].values[0]],
                    'Change in Win %': [round(team_data[metric].values[0] - comparison_team_data[metric].values[0], 2)],
                    f'Week {week} Performance Rank': [
                        current_week_performance[current_week_performance['Team'] == team].index[0] + 1
                    ]
                }
            )

        return pd.concat([pd.DataFrame(data) for data in power_rankings]).sort_values(by='Current Rank').set_index('Team')

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


