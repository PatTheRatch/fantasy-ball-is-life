import pandas as pd
from espn_api.basketball import League, Matchup

from config import ESPN_S2, SWID


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

    def _max_schedule_week(self) -> int:
        """Largest week index present in `league_matchups` (full season incl. playoffs)."""
        try:
            if self.league_matchups:
                return max(int(k) for k in self.league_matchups.keys())
        except Exception:
            pass
        return max(int(self.effective_current_week), int(self.length_of_schedule or 0), 1)

    def get_all_matchups(self):
        all_matchups = {}
        for team in self.teams:
            for i, matchup in enumerate(team.schedule):
                if matchup.home_team.team_name == team.team_name:
                    all_matchups.setdefault(i + 1, []).append(matchup)
        return all_matchups

    def get_all_matchup_data(self):
        # Include every scheduled week (not only through `effective_current_week`), so historical
        # `get_universe_wins(weeks=[...])` calls still see playoff weeks when ESPN's "current" week is off.
        max_w = max(1, int(self._max_schedule_week()))
        data = [
            self.get_matchup_data(match_up, i + 1, team)
            for i, matchups in enumerate(
                [self.league_matchups.get(x, []) for x in range(1, max_w + 1)]
            )
            for match_up in matchups
            for team in ["home", "away"]
        ]
        data = pd.concat(data, ignore_index=True)
        data['Week'] = pd.to_numeric(data['Week'])
        return data

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

    def get_matchup_data(self, matchup: Matchup, week, team='away'):
        team_data = {
            'away': (matchup.away_team.team_name, matchup.home_team.team_name, matchup.away_team_live_score,
                     matchup.home_team_live_score, matchup.away_team_cats),
            'home': (matchup.home_team.team_name, matchup.away_team.team_name, matchup.home_team,
                     matchup.away_team_live_score, matchup.home_team_cats),
        }
        team_name, opponent_name, team_total_score, opponent_total_score, cats = team_data[team]
        data = {
            'Week': [week],
            'Team': [team_name],
            'Opponent': [opponent_name],
            'Team Total Score': [team_total_score],
            'Opponent Total Score': [opponent_total_score],
            **{cat: [cats[cat]['score']] for cat in self.stat_categories}
        }

        return pd.DataFrame(data)

    def get_schedule(self):
        schedule = {'Week': [], 'Team': [], 'Opponent': []}
        for team in self.teams:
            for i, matchup in enumerate(team.schedule):
                schedule['Week'].append(i + 1)
                schedule['Team'].append(team.team_name)
                schedule['Opponent'].append(matchup.away_team.team_name if matchup.home_team.team_name == team.team_name
                                            else matchup.home_team.team_name)

        return pd.DataFrame(schedule)

    def get_universe_wins(self, include_current=False, weeks=None, order_by='Total Wins', ascending=False,
                          additional_team_stats=None):
        if weeks is None:
            weeks = range(1, self.currentMatchupPeriod + include_current)

        weeks_list = list(weeks)

        additional_team_stats = {} if additional_team_stats is None else additional_team_stats

        # One `get_all_matchup_data()` per call — previously every (team, week) pair rebuilt the full table.
        cached_all_data = None

        def _matchup_table():
            nonlocal cached_all_data
            if cached_all_data is None:
                cached_all_data = self.get_all_matchup_data()
            return cached_all_data

        dfs = []
        for team in self.team_names:
            for week in weeks_list:
                if (week, team) in additional_team_stats.keys():
                    dfs.append(self.get_wins(team, week, additional_team_stats[(week, team)], all_data=_matchup_table()))
                else:
                    dfs.append(self.get_wins(team, week, all_data=_matchup_table()))

        df = pd.concat(dfs, ignore_index=True)
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()].copy()

        """df = pd.concat(
            [self.get_wins(team, week, additional_team_stats[week]) for team in self.team_names for week in weeks],
            ignore_index=True
        )"""

        if len(weeks_list) > 1:
            agg_func = {col: 'sum' for col in df.columns if
                        col not in ['Avg Wins', 'Avg Losses', 'Avg Ties', 'Team',
                                    'Lost To', 'Tied With', 'Beaten', 'FG%', 'FT%']}
            agg_func.update(
                {'Avg Wins': 'mean', 'Avg Losses': 'mean', 'Avg Ties': 'mean', 'FG%': 'mean', 'FT%': 'mean'})
            df = df.groupby('Team', as_index=False).agg(agg_func)

        df['Total Win %'] = round((df['Total Wins'] + 0.5 * df['Total Ties']) / (
                df['Total Wins'] + df['Total Losses'] + df['Total Ties']) * 100, 2)
        df['Matchup Win %'] = round((df['Matchup Wins'] + 0.5 * df['Matchup Ties']) / (
                df['Matchup Wins'] + df['Matchup Losses'] + df['Matchup Ties']) * 100, 2)
        df['Actual Win %'] = round((df['Actual Wins'] + 0.5 * df['Actual Ties']) / (
                df['Actual Wins'] + df['Actual Losses'] + df['Actual Ties']) * 100, 2)
        df['Avg Win %'] = round((df['Avg Wins'] + 0.5 * df['Avg Ties']) / (
                df['Avg Wins'] + df['Avg Losses'] + df['Avg Ties']) * 100, 2)
        df['Win % Ratio'] = round(df['Actual Win %'] / df['Total Win %'], 2)

        return df.sort_values(by=order_by, ascending=ascending).reset_index(drop=True)

    @staticmethod
    def _scalar_stat(val):
        """Ensure a single numeric value (duplicate Team rows can make `.loc` return a Series)."""
        if isinstance(val, pd.Series):
            return float(val.iloc[0])
        return float(val)

    def get_wins(self, team_name, week, additional_team_stats=None, all_data=None):
        all_data = self.get_all_matchup_data() if all_data is None else all_data
        week_rows = all_data.loc[all_data['Week'] == week]
        if week_rows.empty:
            raise ValueError(f"No matchup data for week {week}.")
        week_matchups = week_rows.set_index('Team')[self.stat_categories]
        if week_matchups.index.duplicated().any():
            week_matchups = week_matchups[~week_matchups.index.duplicated(keep='first')]
        # Some playoff / partial weeks omit a team row; align to full league so lookups never KeyError.
        week_matchups = week_matchups.reindex(self.team_names).fillna(0.0)

        sched_slice = self.schedule.loc[
            (self.schedule['Week'] == week) & (self.schedule['Team'] == team_name), 'Opponent'
        ]
        # Playoffs: some teams have no matchup row in a later week (eliminated / schedule length mismatch).
        current_opponent = None if sched_slice.empty else sched_slice.iloc[0]

        if additional_team_stats is not None:
            for stat, value in additional_team_stats.items():
                week_matchups.loc[team_name, stat] = value

        stat_wins = {f'{stat} Wins': 0 for stat in self.stat_categories}
        stat_totals = {f'{stat}': 0 for stat in self.stat_categories}
        total_wins, total_losses, total_ties = 0, 0, 0
        matchup_wins, matchup_losses, matchup_ties = 0, 0, 0
        actual_wins, actual_losses, actual_ties = 0, 0, 0
        lost_to, tied_with, beaten = [], [], []

        for opponent in [team for team in self.team_names if team != team_name]:
            local_wins, local_losses, local_ties = 0, 0, 0
            for stat in self.stat_categories:
                team_stat = self._scalar_stat(week_matchups.loc[team_name][stat])
                opponent_stat = self._scalar_stat(week_matchups.loc[opponent][stat])
                if stat == 'TO':
                    team_stat = -team_stat
                    opponent_stat = -opponent_stat
                if current_opponent is not None and opponent == current_opponent:
                    actual_wins += int(team_stat > opponent_stat)
                    actual_losses += int(team_stat < opponent_stat)
                    actual_ties += int(team_stat == opponent_stat)
                total_wins += int(team_stat > opponent_stat)
                total_losses += int(team_stat < opponent_stat)
                total_ties += int(team_stat == opponent_stat)
                stat_wins[f'{stat} Wins'] += int(team_stat > opponent_stat)
                stat_totals[stat] += team_stat / (len(self.team_names) - 1)
                local_wins += int(team_stat > opponent_stat)
                local_losses += int(team_stat < opponent_stat)
                local_ties += int(team_stat == opponent_stat)
            if local_wins > local_losses:
                matchup_wins += 1
                beaten.append(opponent)
            elif local_wins < local_losses:
                matchup_losses += 1
                lost_to.append(opponent)
            else:
                matchup_ties += 1
                tied_with.append(opponent)

        data = {
            'Team': [team_name],
            'Actual Wins': [actual_wins], 'Actual Losses': [actual_losses], 'Actual Ties': [actual_ties],
            'Matchup Wins': [matchup_wins], 'Matchup Losses': [matchup_losses], 'Matchup Ties': [matchup_ties],
            'Total Wins': [total_wins], 'Total Losses': [total_losses], 'Total Ties': [total_ties],
            'Lost To': [lost_to], 'Tied With': [tied_with], 'Beaten': [beaten],
            'Avg Wins': [sum([1 for x in stat_wins.values() if x > 0])],
            'Avg Losses': [sum([1 for x in stat_wins.values() if x < 0])],
            'Avg Ties': [sum([1 for x in stat_wins.values() if x == 0])],
            **stat_wins, **stat_totals
        }
        return pd.DataFrame(data)

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


