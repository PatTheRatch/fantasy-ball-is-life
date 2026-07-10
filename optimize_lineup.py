import string
from typing import Optional

import pandas as pd
from fantasy import MyLeague
import cvxpy as cp
import shutup

from config import (
    BBM_PROJECTIONS_PATH,
    DRAFT_LEAGUE_YEAR_DEFAULT,
    GAMES_PER_WEEK,
    LEAGUE_ID,
    SOLVER_TIME_LIMIT_SECONDS,
)
import draft_targets_mc as mc

shutup.please()


class OptimizeLineup:
    def __init__(
        self,
        exclude_players=None,
        drafted_players=None,
        games_per_week=None,
        initial_budget=200,
        year=None,
        roster_size=13,
        minimum_value_players=3,
        favorite_team=None,
        favorite_team_representation=1,
        minimum_game_threshold=20,
        value_col='$',
        projections_df: Optional[pd.DataFrame] = None,
    ):
        if year is None:
            year = DRAFT_LEAGUE_YEAR_DEFAULT
        if games_per_week is None:
            games_per_week = GAMES_PER_WEEK
        self.league = MyLeague(LEAGUE_ID, year)
        self.games_per_week = games_per_week
        self.excluded_players = exclude_players or []
        self.drafted_players = drafted_players or []
        self.roster_size = roster_size
        self.minimum_value_players = minimum_value_players
        self._projections_df = projections_df
        self.player_data_df = self.process_draft_data()
        self.current_roster = self.init_current_roster()
        self.initial_budget = initial_budget
        self.requirements = {}
        self.favorite_team = favorite_team
        self.favorite_team_representation = favorite_team_representation
        max_g = self.player_data_df["g"].max()
        if minimum_game_threshold >= max_g:
            minimum_game_threshold = max(1, int(max_g * 0.5))
        self.minimum_game_threshold = minimum_game_threshold
        self.value_col = value_col

    def draft_player(self, player, bid):
        self.drafted_players.append((player, bid))
        ind = self.player_data_df['Name'].str.lower() == player
        self.current_roster['Name'].append(player.lower())
        self.current_roster['Bid'].append(bid)
        self.current_roster['PTS PW'].append(self.player_data_df.loc[ind, 'PTS PW'].values[0])
        self.current_roster['REB PW'].append(self.player_data_df.loc[ind, 'REB PW'].values[0])
        self.current_roster['AST PW'].append(self.player_data_df.loc[ind, 'AST PW'].values[0])
        self.current_roster['STL PW'].append(self.player_data_df.loc[ind, 'STL PW'].values[0])
        self.current_roster['BLK PW'].append(self.player_data_df.loc[ind, 'BLK PW'].values[0])
        self.current_roster['TO PW'].append(self.player_data_df.loc[ind, 'TO PW'].values[0])
        self.current_roster['3PM PW'].append(self.player_data_df.loc[ind, '3PM PW'].values[0])
        self.current_roster['fgm/g PW'].append(self.player_data_df.loc[ind, 'fgm/g PW'].values[0])
        self.current_roster['fga/g PW'].append(self.player_data_df.loc[ind, 'fga/g PW'].values[0])
        self.current_roster['ftm/g PW'].append(self.player_data_df.loc[ind, 'ftm/g PW'].values[0])
        self.current_roster['fta/g PW'].append(self.player_data_df.loc[ind, 'fta/g PW'].values[0])
        self.current_roster['Pos'].append(self.player_data_df.loc[ind, 'Pos'].values[0])

    def show_current_roster(self):
        return pd.DataFrame(self.current_roster)

    def init_current_roster(self):
        current_roster = {
            'Name': [],
            'Bid': [],
            'PTS PW': [],
            'REB PW': [],
            'AST PW': [],
            'STL PW': [],
            'BLK PW': [],
            'TO PW': [],
            '3PM PW': [],
            'fgm/g PW': [],
            'fga/g PW': [],
            'ftm/g PW': [],
            'fta/g PW': [],
            'Pos': []
        }
        return current_roster

    def exclude_player(self, player):
        self.excluded_players.append(player)

    def process_draft_data(self):
        # Get draft data
        draft_data = [(pick.playerName, pick.bid_amount, pick.team.team_name) for pick in self.league.draft]
        draft_df = pd.DataFrame(draft_data, columns=['Player', 'Bid', 'Owner'])

        # Load and process player stats
        if self._projections_df is not None:
            stats_df = self._projections_df.copy()
        else:
            stats_df = pd.read_excel(BBM_PROJECTIONS_PATH)
        stat_columns = {
            'fg%': 'FG%', 'ft%': 'FT%', 'p/g': 'PTS', '3/g': '3PM',
            'r/g': 'REB', 'a/g': 'AST', 's/g': 'STL', 'b/g': 'BLK', 'to/g': 'TO'
        }
        stats_df.rename(columns=stat_columns, inplace=True)

        # Merge and clean data
        df = pd.merge(stats_df, draft_df, how='left', left_on='Name', right_on='Player')
        df = self.clean_player_data(df)

        # Calculate derived stats
        df = self.calculate_stats(df)

        return df

    def clean_player_data(self, df):
        # Filter and process player data
        excluded = ['kyrie irving', 'deandre ayton', 'kristaps porzingis', 'jimmy butler',
                    'jason tatum']
        if self.excluded_players:
            excluded.extend(self.excluded_players)

        df = df[~df['Name'].str.lower().isin(excluded)]
        df = df[df['g'] >= 25]
        df.loc[df['Name'] == 'Anthony Davis', 'Pos'] = 'C'
        # replace nans in bid with '$' column
        df.loc[df['Bid'].isna(), 'Bid'] = df.loc[df['Bid'].isna(), '$']

        # Make new value column that is the greater of $ or Bid, rounded to nearest integer, with minimum of 1
        df['Value'] = df[['$', 'Bid']].max(axis=1)
        df['Value'] = round(df['Value'], 0).replace(0, 1)

        df['$'] = round(df['$'], 0).replace(0, 1)
        df['Cost'] = df[['$', 'Bid']].max(axis=1)
        df.loc[df['Bid'] == 1, 'Cost'] = 1

        return df

    def get_target_stats(self, percentile=.75):
        print('getting target stats')
        weekly_stats = {cat: [] for cat in self.league.stat_categories}

        # Sample only weeks that have actually been played and fall within the
        # regular season: playoff weeks involve a shrinking subset of teams and
        # aren't a representative "typical week" for setting draft category
        # targets. `reg_season_count` comes straight from ESPN's league settings
        # (already relied on elsewhere, e.g. data_feed.py) rather than a
        # hand-typed week count.
        reg_season_weeks = int(getattr(self.league.settings, 'reg_season_count', 0) or 0)
        reg_season_weeks = reg_season_weeks or int(self.league.length_of_schedule)
        last_played_week = max(1, min(int(self.league.effective_current_week), reg_season_weeks))

        for week in range(1, last_played_week + 1):
            try:
                weekly_scores = self.league.get_universe_wins(weeks=[week])
            except ValueError:
                # No matchup data for this week (e.g. a bye/All-Star week with no
                # scheduled matchup) — skip it rather than corrupting the sample.
                continue
            # get the n percentile of each stat category
            for category in self.league.stat_categories:
                weekly_stats[category].append(weekly_scores[category].quantile(percentile))
        weekly_stats = pd.DataFrame(weekly_stats)
        # Get the average weekly stats for each category
        avg_weekly_stats = weekly_stats.mean()
        return avg_weekly_stats

    def _mc_pool_df(self):
        """Map the optimizer's per-week player columns into the shape the Monte
        Carlo engine expects. We feed the already-scaled ``* PW`` columns and run
        the engine with ``avg_games_per_week=1.0`` so MC targets land on exactly
        the same per-week scale as the roster constraints. Turnovers are passed in
        the optimizer's internal negated convention, so the TO target comes back
        directly usable."""
        df = self.player_data_df
        value_col = next(
            (c for c in ('LeagV', 'League Value', 'Value') if c in df.columns),
            '$',
        )
        return pd.DataFrame({
            'Player': df['Name'],
            'POS': df['Pos'],
            'Price': df['$'],
            'Value': df[value_col],
            'PTS_PG': df['PTS PW'],
            'REB_PG': df['REB PW'],
            'AST_PG': df['AST PW'],
            'STL_PG': df['STL PW'],
            'BLK_PG': df['BLK PW'],
            '3PM_PG': df['3PM PW'],
            'TO_PG': df['TO PW'],          # already negated (higher is better)
            'FGM_PG': df['fgm/g PW'],
            'FGA_PG': df['fga/g PW'],
            'FTM_PG': df['ftm/g PW'],
            'FTA_PG': df['fta/g PW'],
        })

    def get_target_stats_mc(self, percentile=.80, n_teams=1000, seed=7):
        """Monte Carlo targets: simulate ``n_teams`` realistic drafts of the current
        pool and take the ``percentile``-th team per category. History-independent.
        Returns a Series indexed by the league's stat categories (same shape as
        :meth:`get_target_stats`)."""
        print('getting target stats (monte carlo)')
        teams_df, fg_pct, ft_pct, _ = mc.monte_carlo_drafts_13team_daily(
            self._mc_pool_df(),
            n_teams=n_teams,
            budget=self.initial_budget,
            avg_games_per_week=1.0,   # PW columns are already per-week
            rng_seed=seed,
        )
        targets = mc.mc_targets_from_percentile(teams_df, fg_pct, ft_pct, pct=percentile)
        return pd.Series({cat: targets[cat] for cat in self.league.stat_categories})

    def set_requirements(self, categories, percentile=.75, target_method='monte_carlo',
                         n_teams=1000, seed=7):
        """Set per-category floor targets for the optimizer.

        ``target_method='monte_carlo'`` (default) derives targets by simulating
        drafts of the current player pool; ``'historical'`` uses past weekly
        scores (needs league history). Monte Carlo falls back to historical if the
        pool can't produce feasible teams."""
        print(f'setting requirements ({target_method})')
        if target_method == 'monte_carlo':
            try:
                avg_weekly_stats = self.get_target_stats_mc(
                    percentile=percentile, n_teams=n_teams, seed=seed,
                )
            except (RuntimeError, KeyError, ValueError) as e:
                print(f'monte carlo targets unavailable ({e}); falling back to historical')
                avg_weekly_stats = self.get_target_stats(percentile)
        elif target_method == 'historical':
            avg_weekly_stats = self.get_target_stats(percentile)
        else:
            raise ValueError(
                f"Unknown target_method={target_method!r}; expected "
                f"'monte_carlo' or 'historical'."
            )
        self.requirements = {cat: avg_weekly_stats.loc[cat] for cat in categories}

    def calculate_stats(self, df):
        # Calculate additional statistics
        df['TO'] *= -1
        df['fgm/g'] = df['fga/g'] * df['FG%']
        df['ftm/g'] = df['fta/g'] * df['FT%']

        # Calculate weekly stats
        weekly_stats = ['PTS', 'REB', 'AST', 'STL', 'BLK', 'TO', '3PM',
                        'fgm/g', 'fga/g', 'ftm/g', 'fta/g']
        for stat in weekly_stats:
            df[f'{stat} PW'] = df[stat] * self.games_per_week
            df[f'{stat} PW'].fillna(0, inplace=True)

        return df

    def _validate_pool_feasibility(self, player_data_df, current_roster, player_data_df_original):
        """
        Sanity-check the filtered player pool before handing it to the solver, so obviously
        infeasible setups (e.g. a `minimum_game_threshold` that filters out every player) raise a
        clear, actionable error instead of cvxpy's opaque "Cannot unpack invalid solution".
        """
        needed = self.roster_size - len(current_roster)

        if player_data_df.empty:
            max_games = player_data_df_original['g'].max() if not player_data_df_original.empty else 0
            raise ValueError(
                f"No players remain after filtering on minimum_game_threshold="
                f"{self.minimum_game_threshold} (max games in the loaded projections data is "
                f"{max_games}). Lower `minimum_game_threshold` and try again."
            )

        if needed < 0:
            raise ValueError(
                f"Current roster already has {len(current_roster)} players, which exceeds "
                f"roster_size={self.roster_size}."
            )

        if needed > len(player_data_df):
            raise ValueError(
                f"Need {needed} more player(s) to fill the roster, but only "
                f"{len(player_data_df)} eligible player(s) remain after filtering "
                f"(minimum_game_threshold={self.minimum_game_threshold}). Lower "
                f"`minimum_game_threshold` or exclude fewer players."
            )

        value_players = int((player_data_df[self.value_col] == 1).sum())
        if value_players < self.minimum_value_players:
            raise ValueError(
                f"`minimum_value_players`={self.minimum_value_players} but only {value_players} "
                f"player(s) with {self.value_col}==1 remain after filtering "
                f"(minimum_game_threshold={self.minimum_game_threshold}). Lower "
                f"`minimum_value_players` or `minimum_game_threshold`."
            )

        for position in ('C', 'PG', 'SG', 'SF', 'PF'):
            available = int(player_data_df['Pos'].str.contains(position).sum())
            if available < 1:
                raise ValueError(
                    f"No eligible players remain at position '{position}' after filtering "
                    f"(minimum_game_threshold={self.minimum_game_threshold}). Lower "
                    f"`minimum_game_threshold` or exclude fewer players."
                )

        if self.favorite_team:
            fav_team_available = int((player_data_df['Team'] == self.favorite_team).sum())
            if fav_team_available < self.favorite_team_representation:
                raise ValueError(
                    f"favorite_team_representation={self.favorite_team_representation} requires that "
                    f"many {self.favorite_team} player(s), but only {fav_team_available} remain "
                    f"after filtering (minimum_game_threshold={self.minimum_game_threshold}, "
                    f"exclude_players, and anyone already drafted). Lower `favorite_team_representation` "
                    f"or `minimum_game_threshold`, or exclude fewer players."
                )

    def optimize_roster(self, stat_to_maximize):
        # Core constraints
        player_data_df = self.player_data_df.copy()

        current_roster = self.show_current_roster()
        current_roster['Pos'] = current_roster['Pos'].astype('object')
        player_data_df_original = player_data_df.copy()

        player_data_df = player_data_df[
            (~player_data_df['Name'].str.lower().isin(current_roster['Name'])) &
            (player_data_df['g'] > self.minimum_game_threshold)
        ]

        self._validate_pool_feasibility(player_data_df, current_roster, player_data_df_original)

        player_vars = cp.Variable(len(player_data_df), boolean=True)

        remaining_budget = self.initial_budget - sum(current_roster['Bid'])

        # Constraint for big 5 roster
        costs = player_data_df[self.value_col].values
        S = costs @ player_vars

        # categorical constraints
        constraints = [
            player_data_df[self.value_col].values @ player_vars <= remaining_budget,
            cp.sum(player_vars) == (self.roster_size - len(current_roster)),
            (player_data_df[self.value_col].values @ player_vars) >= 0.3 * S,
        ]

        # Favorite team constraint

        if self.favorite_team:
            print(f'Including at least {self.favorite_team_representation} player(s) from {self.favorite_team}')
            # At least 1 player from team x (placeholder for now)
            fav_team_players = player_data_df['Team'] == self.favorite_team  # Example: Cleveland Cavaliers
            constraints.append(cp.sum(player_vars[fav_team_players]) >= self.favorite_team_representation)

        # Stat requirements constraints

        t_fg = self.requirements.get('FG%', None)
        t_ft = self.requirements.get('FT%', None)

        FGM = player_data_df['fgm/g PW'].to_numpy()  # per-week field goals made
        FGA = player_data_df['fga/g PW'].to_numpy()

        FTM = player_data_df['ftm/g PW'].to_numpy()  # per-week free throws made
        FTA = player_data_df['fta/g PW'].to_numpy()

        if t_fg is not None:
            constraints += [(FGM @ player_vars) - t_fg * (FGA @ player_vars) >= 0]

        if t_ft is not None:
            constraints += [(FTM @ player_vars) - t_ft * (FTA @ player_vars) >= 0]

        for key, value in self.requirements.items():
            if key not in ['FG%', 'FT%']:
                constraints.append(
                    player_data_df[f'{key} PW'].values @ player_vars >= (value - current_roster[f'{key} PW'].sum())
                )

        # Position constraints
        positions = {
            'C': (player_data_df['Pos'] == 'C', (1, 3)),
            'PG': (player_data_df['Pos'].str.contains('PG'), (1, None)),
            'SG': (player_data_df['Pos'].str.contains('SG'), (1, None)),
            'SF': (player_data_df['Pos'].str.contains('SF'), (1, None)),
            'PF': (player_data_df['Pos'].str.contains('PF'), (1, None))
        }

        for position, (pos_filter, (min_req, max_req)) in positions.items():
            if min_req:
                constraints.append(cp.sum(player_vars[pos_filter]) >= min_req)
            if max_req:
                constraints.append(cp.sum(player_vars[pos_filter]) <= (
                            max_req - len(current_roster[current_roster['Pos'].str.contains(position)])))

        # Set Minimum value player constraint
        constraints.append(cp.sum(player_vars[player_data_df[self.value_col] == 1]) == self.minimum_value_players)

        objective = cp.Maximize(player_data_df[f'{stat_to_maximize} PW'].values @ player_vars)
        prob = cp.Problem(objective, constraints)
        try:
            # cvxpy's MILP solve has no timeout by default. Discovered running real
            # Monte Carlo-derived category targets through this path for the first
            # time (docs/specs/MC_DRAFT_TARGETS.md): some genuinely feasible
            # category/percentile combinations took 8-24s+ with no bound -- a live
            # draft can't wait on that. `time_limit` bounds every solve; HiGHS
            # returns status 'user_limit' with the best incumbent found so far
            # when it hits the cap (accepted below like 'optimal_inaccurate').
            prob.solve(solver=cp.HIGHS, time_limit=SOLVER_TIME_LIMIT_SECONDS)
        except ValueError as e:
            raise ValueError(
                f"Solver failed to find a solution (status={prob.status}). This usually means the "
                f"constraints are infeasible for the current player pool of {len(player_data_df)} "
                f"player(s) and remaining budget of {remaining_budget}. Try lowering "
                f"`minimum_game_threshold` (currently {self.minimum_game_threshold}), reducing "
                f"`minimum_value_players` (currently {self.minimum_value_players}), or relaxing "
                f"the stat requirement percentile."
            ) from e

        if prob.status == 'user_limit' and player_vars.value is None:
            raise ValueError(
                f"Solver hit the {SOLVER_TIME_LIMIT_SECONDS:.0f}s time limit without finding any "
                f"feasible roster for a player pool of {len(player_data_df)} player(s) and remaining "
                f"budget of {remaining_budget}. This doesn't necessarily mean it's infeasible -- just "
                f"hard to solve quickly. Try relaxing the stat requirement percentile, lowering "
                f"`minimum_game_threshold` (currently {self.minimum_game_threshold}), or reducing "
                f"`minimum_value_players` (currently {self.minimum_value_players})."
            )

        if prob.status not in ('optimal', 'optimal_inaccurate', 'user_limit') or player_vars.value is None:
            raise ValueError(
                f"No feasible roster found (solver status={prob.status}) for a player pool of "
                f"{len(player_data_df)} player(s) and remaining budget of {remaining_budget}. Try "
                f"lowering `minimum_game_threshold` (currently {self.minimum_game_threshold}), "
                f"reducing `minimum_value_players` (currently {self.minimum_value_players}), or "
                f"relaxing the stat requirement percentile."
            )

        # A 'user_limit' incumbent isn't guaranteed to satisfy every hard
        # constraint the way a proven-optimal/proven-feasible status is -- e.g.
        # HiGHS can return a degenerate all-zero selection when it hits the time
        # limit before finding a single complete roster. Verify the count before
        # trusting it; a size mismatch here means "ran out of time", not a
        # usable (if suboptimal) roster.
        selected_count = int(player_vars.value.round().astype(bool).sum())
        needed_count = self.roster_size - len(current_roster)
        if selected_count != needed_count:
            raise ValueError(
                f"Solver hit the {SOLVER_TIME_LIMIT_SECONDS:.0f}s time limit (status={prob.status}) "
                f"without completing a valid {needed_count}-player roster (got {selected_count}) for a "
                f"player pool of {len(player_data_df)} player(s) and remaining budget of "
                f"{remaining_budget}. Try relaxing the stat requirement percentile, lowering "
                f"`minimum_game_threshold` (currently {self.minimum_game_threshold}), or reducing "
                f"`minimum_value_players` (currently {self.minimum_value_players})."
            )

        results = player_data_df[(player_vars.value.round().astype(bool))]
        results = pd.concat([results, player_data_df_original[
            player_data_df_original['Name'].str.lower().isin(current_roster['Name'])]])

        for key in list(self.requirements.keys()) + [stat_to_maximize]:
            if key == 'FG%':
                print(f'{key}: {results[f"fgm/g PW"].sum() / results[f"fga/g PW"].sum()}')
            elif key == 'FT%':
                print(f'{key}: {results[f"ftm/g PW"].sum() / results[f"fta/g PW"].sum()}')
            else:
                print(f'{key}: {results[f"{key} PW"].sum()}')
        print(f'Cost: {results["$"].sum()}')

        return results


def _extract_team_df(result_or_opt):
    """
    Try to get the chosen roster as a DataFrame from:
      1) optimize_roster(...) return value, or
      2) draft_opt.team_df / draft_opt.results / draft_opt.team / draft_opt.roster, etc.
    Adjust/add branches if your class uses a different attribute.
    """
    # 1) If the function directly returned a DF
    if isinstance(result_or_opt, pd.DataFrame):
        return result_or_opt

    # 2) Common attribute names on the optimizer instance
    for attr in ("team_df", "results", "team", "roster", "chosen_roster"):
        if hasattr(result_or_opt, attr):
            maybe = getattr(result_or_opt, attr)
            if isinstance(maybe, pd.DataFrame):
                return maybe
            # some classes wrap the df in a dict
            if isinstance(maybe, dict):
                for k in ("team", "roster", "df", "players"):
                    if k in maybe and isinstance(maybe[k], pd.DataFrame):
                        return maybe[k]

    # 3) If optimize_roster returns a dict-like
    if isinstance(result_or_opt, dict):
        for k in ("team", "roster", "df", "players"):
            if k in result_or_opt and isinstance(result_or_opt[k], pd.DataFrame):
                return result_or_opt[k]

    raise AttributeError("Could not locate a team DataFrame from optimize_roster(). "
                         "Expose the roster as a DataFrame or adapt _extract_team_df().")


def _pick_top_to_ban(team_df, prefer_col_order=("Price", "Value", "Z", "Score")):
    """
    Choose a 'top' player from a roster to ban next time.
    Priority: highest Price; if missing, fallback to Value/Z/Score.
    """
    df = team_df.copy()
    # normalize column names to handle case differences
    cols = {c.lower(): c for c in df.columns}
    for raw in prefer_col_order:
        c = raw.lower()
        if c in cols:
            col = cols[c]
            top = df.sort_values(col, ascending=False).iloc[0]
            # try to find a player-name column
            for name_col in ("Player", "player", "Name", "name"):
                if name_col in df.columns:
                    return str(top[name_col]).strip().lower()
            # if no explicit name col, use index
            return str(top.name).strip().lower()

    # fallback: first row’s player name
    for name_col in ("Player", "player", "Name", "name"):
        if name_col in df.columns:
            return str(df.iloc[0][name_col]).strip().lower()

    return str(df.index[0]).strip().lower()


def generate_multiple_plans(
    n_plans=20,
    base_excluded=None,
    base_percentile=0.80,
    percentiles_cycle=(0.78, 0.80, 0.82, 0.84, 0.86),
    categories=('PTS', 'REB', 'STL', 'BLK', 'AST'),  # your current set
    value_col='Value',
    year=None,
    roster_size=13,
    favorite_team='CLE',
    minimum_game_threshold=55,
    initial_budget=200,
    sort_primary='Price',  # how to choose “top player” to ban
    out_prefix='draft_plan_',  # files: draft_plan_A.csv, etc.
    objective_focus='3PM',  # what you pass to optimize_roster
    target_method='monte_carlo',  # 'monte_carlo' (default) | 'historical'
):
    """
    Build n_plans varied rosters by (a) cycling percentile targets and (b) banning one 'top' player each iteration.
    Saves each roster to CSV and returns a summary DataFrame.
    """
    if year is None:
        year = DRAFT_LEAGUE_YEAR_DEFAULT
    if base_excluded is None:
        base_excluded = []

    banned = set(p.strip().lower() for p in base_excluded)
    plans_summary = []

    # cycle letters A, B, C, ...
    plan_labels = list(string.ascii_uppercase)
    if n_plans > len(plan_labels):
        plan_labels += [f"Plan{idx + 1}" for idx in range(n_plans - len(plan_labels))]

    for i in range(n_plans):
        label = plan_labels[i]
        pct = percentiles_cycle[i % len(percentiles_cycle)] if percentiles_cycle else base_percentile

        # fresh optimizer each loop so constraints/sets are clean
        draft_opt = OptimizeLineup(
            exclude_players=sorted(banned),
            year=year,
            roster_size=roster_size,
            favorite_team=favorite_team,
            value_col=value_col,
            minimum_game_threshold=minimum_game_threshold,
            initial_budget=initial_budget
        )

        # set category targets at chosen percentile
        draft_opt.set_requirements(list(categories), percentile=pct, target_method=target_method)

        try:
            result = draft_opt.optimize_roster(objective_focus)
        except AttributeError:
            # your earlier try/except pattern — proceed if solver attaches results on the instance
            result = draft_opt

        # extract the roster DF
        team_df = _extract_team_df(result)

        # ensure we have a player-name column for saving
        if 'Player' not in team_df.columns:
            # try to find name-like; else promote index to a column
            for alt in ('player', 'Name', 'name'):
                if alt in team_df.columns:
                    team_df = team_df.rename(columns={alt: 'Player'})
                    break
            else:
                team_df = team_df.reset_index().rename(columns={'index': 'Player'})

        # save this plan
        outfile = f"{out_prefix}{label}.csv"
        team_df.to_csv(outfile, index=False)

        # compute quick aggregate stats if available
        totals = {}
        for cat in ('PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'TO', 'FGM', 'FGA', 'FTM', 'FTA'):
            if cat in team_df.columns:
                totals[cat] = float(team_df[cat].sum())

        # choose next ban target from this roster (top by Price or Value)
        top_to_ban = _pick_top_to_ban(team_df, prefer_col_order=(sort_primary, value_col))

        plans_summary.append({
            'Plan': label,
            'Percentile': pct,
            'Banned_Up_To_This_Plan': ", ".join(sorted(banned)) if banned else "",
            'Next_Ban_From_This_Roster': top_to_ban,
            'Saved_CSV': outfile,
            **totals
        })

        # add the top player from THIS roster to the ban list for the NEXT iteration
        banned.add(top_to_ban)

    summary_df = pd.DataFrame(plans_summary)
    summary_df.to_csv(f"{out_prefix}INDEX.csv", index=False)
    return summary_df


if __name__ == '__main__':
    excluded_players = ['jayson tatum', 'max strus', 'kyrie irving', 'tyler herro', 'kristaps porzingis',
                        'joel embiid', 'trey murphy', 'Zach Edey', 'brandon miller', 'amen thompson',
                        'cooper flag', 'amen thompson', 'luka doncic', 'james harden', 'anthony davis', 'trae young',
                        'bam adebayo', 'chet holmgren', 'josh giddey', 'dyson daniels', 'cade cunningham', 'alperen sengun',
                        'domantas sabonis', 'giannis antetokounmpo', 'devin booker', 'darius garland', 'cooper flagg', 'evan mobley',
                        'zion williamson', 'lamelo ball', 'donovan mitchell', 'nikola jokic', 'derrick white',
                        'stephen curry', 'kevin durant', 'desmond bane', 'coby white', 'nikola vucevic', 'jordan poole',
                        'tyrese maxey', 'victor wembanyama', 'jimmy butler','anthony edwards',
                        'jalen brunson', 'scottie barnes', 'jamal murray', 'shai gilgeous-alexander']
    """summary = generate_multiple_plans(
        n_plans=20,
        base_excluded=excluded_players,
        base_percentile=0.80,
        percentiles_cycle=(0.78, 0.80, 0.82, 0.75, 0.73),  # gentle wiggles
        categories=('PTS', 'REB', 'STL', 'BLK', 'AST'),  # same as your set_requirements
        value_col='Value',
        year=2025,
        roster_size=13,
        favorite_team='CLE',
        minimum_game_threshold=55,
        initial_budget=200,
        sort_primary='Price',  # ban the priciest guy each time
        out_prefix='draft_plan_',  # files draft_plan_A.csv, draft_plan_B.csv, ...
        objective_focus='3PM',  # what you already optimize on
    )"""


    draft_opt = OptimizeLineup(exclude_players=excluded_players, year=2025, roster_size=13, favorite_team=None,
                               value_col='Value', minimum_game_threshold=55, initial_budget=300)
    draft_opt.draft_player('ja morant', 22)
    draft_opt.draft_player('myles turner', 30)
    draft_opt.draft_player('lauri markkanen', 16)
    draft_opt.draft_player('andrew wiggins', 8)
    draft_opt.draft_player('jalen johnson', 40)
    #draft_opt.draft_player('kawhi leonard', 12)
    draft_opt.draft_player('kevin porter jr.', 5)
    draft_opt.draft_player('jarrett allen', 17)
    draft_opt.draft_player('ausar thompson', 2)
    draft_opt.set_requirements(['PTS', 'REB', 'STL', 'BLK', 'AST',
                                # 'FG%'
                                ], percentile=.60)
    try:
        results = draft_opt.optimize_roster('AST')
        draft_opt.optimize_roster('3PM')
    except AttributeError:
        print('No players available to meet requirements')
