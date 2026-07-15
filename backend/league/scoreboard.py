"""Vectorized weekly all-play computation, decoupled from the ESPN fetch.

The entire "universe wins" / power-ranking universe is derivable from one tidy
table — ``(week, team) -> [9 category totals]`` — plus the schedule
``(week, team) -> real opponent``. That's ~250 rows for a full 12-team season.

``WeeklyScoreboard`` owns that computation. It takes the tidy scores + schedule
(however they were fetched) and answers ``all_play(weeks)`` — the replacement
for ``MyLeague.get_universe_wins`` / ``get_wins`` / ``get_all_matchup_data``.
Per week it does the all-play tournament with numpy pairwise comparisons over a
small ``n_teams × n_cats`` matrix instead of the previous nested Python loop of
chained ``.loc[]`` scalar lookups, then runs the identical
concat → aggregate → derive tail so the output frame is byte-for-byte the same.

Why this exists separately from ``MyLeague``:
- Power rankings and season stats need *only* this — not the pro schedule,
  player map, or draft that ``MyLeague`` also fetches. A ``WeeklyScoreboard``
  can be built from a narrow mMatchup-only fetch (see
  ``backend/league/scoreboard_fetch.py``).
- It has no ESPN dependency, so it is unit-testable from a hand-built table
  with no ``League`` mock.

``MyLeague`` now delegates its all-play methods here, so there is a single
implementation of the semantics (playoff/bye exclusion, lower-is-better
turnovers, the all-play win% derivations).
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

DEFAULT_STAT_CATEGORIES: tuple[str, ...] = (
    "PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO",
)
DEFAULT_LOWER_IS_BETTER: frozenset[str] = frozenset({"TO"})


class WeeklyScoreboard:
    """All-play metrics over a tidy per-(team, week) category table.

    Parameters
    ----------
    scores:
        DataFrame with columns ``Week``, ``Team`` and one column per stat
        category. Exactly one row per (team, week) that actually played.
    schedule:
        DataFrame with columns ``Week``, ``Team``, ``Opponent`` giving each
        team's real head-to-head opponent per week (used for "Actual" record).
    stat_categories / lower_is_better:
        Category set and the subset where fewer is better (turnovers). Fewer-is-
        better categories are negated internally so a single ``>`` comparison
        wins them — matching the downstream convention power rankings and the
        draft optimizer both rely on (the ``TO`` total comes out negated).
    """

    def __init__(
        self,
        scores: pd.DataFrame,
        schedule: pd.DataFrame,
        stat_categories: Sequence[str] = DEFAULT_STAT_CATEGORIES,
        lower_is_better: Iterable[str] = DEFAULT_LOWER_IS_BETTER,
    ) -> None:
        self.stat_categories = list(stat_categories)
        self.lower_is_better = frozenset(lower_is_better)
        self._scores = scores
        self._schedule = schedule
        # (week, team) -> real opponent, for the "Actual" record.
        self._opponent: dict[tuple[int, str], str] = {}
        if schedule is not None and not schedule.empty:
            for w, t, opp in zip(schedule["Week"], schedule["Team"], schedule["Opponent"]):
                self._opponent[(int(w), t)] = opp

    @property
    def max_week(self) -> int:
        """Largest week present in the scores table (0 if empty)."""
        if self._scores is None or self._scores.empty or "Week" not in self._scores:
            return 0
        return int(pd.to_numeric(self._scores["Week"]).max())

    # --- construction from an espn-api League ---------------------------------

    @classmethod
    def from_all_matchup_data(
        cls,
        all_data: pd.DataFrame,
        schedule: pd.DataFrame,
        stat_categories: Sequence[str] = DEFAULT_STAT_CATEGORIES,
        lower_is_better: Iterable[str] = DEFAULT_LOWER_IS_BETTER,
    ) -> "WeeklyScoreboard":
        """Build from a ``get_all_matchup_data``-shaped frame (one row per
        team-week with raw, *un-negated* category scores)."""
        return cls(all_data, schedule, stat_categories, lower_is_better)

    # --- core: one week -------------------------------------------------------

    def _week_records(
        self,
        week: int,
        all_data: pd.DataFrame,
        inject: Optional[Mapping[str, float]] = None,
        inject_team: Optional[str] = None,
    ) -> list[dict]:
        """All-play records for every active team in ``week``.

        Mirrors the old ``get_wins`` semantics exactly, but computes every
        team's row in one vectorized pass rather than one Python loop per team.
        Returns a list of per-team dicts (empty when the week has < 2 active
        teams, i.e. nobody has an opponent — same as the old empty-frame drop).
        """
        cats = self.stat_categories
        week_rows = all_data.loc[all_data["Week"] == week]
        if week_rows.empty and inject_team is None:
            raise ValueError(f"No matchup data for week {week}.")

        wk = week_rows.set_index("Team")[cats]
        if wk.index.duplicated().any():
            wk = wk[~wk.index.duplicated(keep="first")]

        # Optional hypothetical-team injection (draft what-if): a team with no
        # real matchup this week becomes an active participant with the given
        # stat line; an existing team's stats are overridden.
        if inject is not None and inject_team is not None:
            if inject_team not in wk.index:
                wk.loc[inject_team] = 0.0
            for stat, value in inject.items():
                wk.loc[inject_team, stat] = value

        teams = list(wk.index)
        if len(teams) < 2:
            return []

        idx = {t: i for i, t in enumerate(teams)}
        # Signed matrix: fewer-is-better categories negated so ">" wins them.
        M = wk[cats].to_numpy(dtype=float)
        signs = np.array([-1.0 if c in self.lower_is_better else 1.0 for c in cats])
        Ms = M * signs  # (n_teams, n_cats)
        n = len(teams)

        # Per-category, per-pair comparisons: gt[c, i, j] = Ms[i,c] > Ms[j,c].
        # Shape (n_cats, n_teams, n_teams).
        a = Ms.T[:, :, None]          # (n_cats, n_teams, 1)
        b = Ms.T[:, None, :]          # (n_cats, 1, n_teams)
        gt = a > b
        lt = a < b
        eq = a == b
        # Exclude self-comparison (the old code loops over opponents only).
        diag = np.eye(n, dtype=bool)[None, :, :]
        gt &= ~diag
        lt &= ~diag
        eq &= ~diag

        # Category all-play tallies per team (summed over opponents).
        cat_wins = gt.sum(axis=2)      # (n_cats, n_teams)
        total_wins = cat_wins.sum(axis=0)                 # (n_teams,)
        total_losses = lt.sum(axis=2).sum(axis=0)
        total_ties = eq.sum(axis=2).sum(axis=0)

        # Head-to-head (matchup) record: for each opponent, who won more cats.
        local_wins = gt.sum(axis=0)    # (n_teams, n_teams) i beat j in this many cats
        local_losses = lt.sum(axis=0)
        beat = local_wins > local_losses          # (i, j)
        lose = local_wins < local_losses
        tie = (local_wins == local_losses) & ~diag[0]
        # never count self as an opponent
        beat &= ~np.eye(n, dtype=bool)
        lose &= ~np.eye(n, dtype=bool)
        matchup_wins = beat.sum(axis=1)
        matchup_losses = lose.sum(axis=1)
        matchup_ties = tie.sum(axis=1)

        records: list[dict] = []
        for t in teams:
            i = idx[t]
            beaten = [teams[j] for j in range(n) if beat[i, j]]
            lost_to = [teams[j] for j in range(n) if lose[i, j]]
            tied_with = [teams[j] for j in range(n) if tie[i, j]]

            # "Actual" record: only vs the real scheduled opponent, if it played.
            actual_w = actual_l = actual_t = 0
            opp = self._opponent.get((int(week), t))
            if opp is not None and opp in idx and opp != t:
                j = idx[opp]
                actual_w = int(gt[:, i, j].sum())
                actual_l = int(lt[:, i, j].sum())
                actual_t = int(eq[:, i, j].sum())

            stat_wins = {f"{c} Wins": int(cat_wins[ci, i]) for ci, c in enumerate(cats)}
            # Signed per-category total (== the team's own value; TO negated).
            stat_totals = {c: float(Ms[i, ci]) for ci, c in enumerate(cats)}

            avg_wins = sum(1 for v in stat_wins.values() if v > 0)
            avg_ties = sum(1 for v in stat_wins.values() if v == 0)

            rec = {
                "Team": t,
                "Actual Wins": actual_w, "Actual Losses": actual_l, "Actual Ties": actual_t,
                "Matchup Wins": int(matchup_wins[i]), "Matchup Losses": int(matchup_losses[i]),
                "Matchup Ties": int(matchup_ties[i]),
                "Total Wins": int(total_wins[i]), "Total Losses": int(total_losses[i]),
                "Total Ties": int(total_ties[i]),
                "Lost To": lost_to, "Tied With": tied_with, "Beaten": beaten,
                # Avg Losses is always 0 — preserved bug-for-bug from the
                # original: a team's per-category win count is never negative, so
                # the original's `x < 0` test never fired. (Flagged for a
                # separate fix rather than silently changing the season-stats API.)
                "Avg Wins": avg_wins, "Avg Losses": 0, "Avg Ties": avg_ties,
                **stat_wins, **stat_totals,
            }
            records.append(rec)
        return records

    # --- public: many weeks ---------------------------------------------------

    def all_play(
        self,
        weeks: Iterable[int],
        order_by="Total Wins",
        ascending: bool = False,
        inject: Optional[Mapping[tuple[int, str], Mapping[str, float]]] = None,
        all_data: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """All-play standings over ``weeks`` — the ``get_universe_wins`` output.

        Single-week frames carry the ``Lost To`` / ``Tied With`` / ``Beaten``
        list columns; multi-week frames aggregate and drop them (identical to
        the original). ``inject`` maps ``(week, team) -> {stat: value}`` for the
        draft what-if path.
        """
        weeks_list = list(weeks)
        inject = inject or {}
        data = self._scores if all_data is None else all_data

        records: list[dict] = []
        for week in weeks_list:
            for (iw, it), stats in inject.items():
                if iw == week:
                    records.extend(self._week_records(week, data, inject=stats, inject_team=it))
                    break
            else:
                records.extend(self._week_records(week, data))

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated()].copy()

        if len(weeks_list) > 1:
            list_cols = ["Team", "Lost To", "Tied With", "Beaten"]
            mean_cols = ["Avg Wins", "Avg Losses", "Avg Ties", "FG%", "FT%"]
            agg_func = {
                col: "sum" for col in df.columns if col not in list_cols + mean_cols
            }
            agg_func.update({c: "mean" for c in mean_cols})
            df = df.groupby("Team", as_index=False).agg(agg_func)

        df["Total Win %"] = round((df["Total Wins"] + 0.5 * df["Total Ties"]) / (
            df["Total Wins"] + df["Total Losses"] + df["Total Ties"]) * 100, 2)
        df["Matchup Win %"] = round((df["Matchup Wins"] + 0.5 * df["Matchup Ties"]) / (
            df["Matchup Wins"] + df["Matchup Losses"] + df["Matchup Ties"]) * 100, 2)
        df["Actual Win %"] = round((df["Actual Wins"] + 0.5 * df["Actual Ties"]) / (
            df["Actual Wins"] + df["Actual Losses"] + df["Actual Ties"]) * 100, 2)
        df["Avg Win %"] = round((df["Avg Wins"] + 0.5 * df["Avg Ties"]) / (
            df["Avg Wins"] + df["Avg Losses"] + df["Avg Ties"]) * 100, 2)
        df["Win % Ratio"] = round(df["Actual Win %"] / df["Total Win %"], 2)

        return df.sort_values(by=order_by, ascending=ascending).reset_index(drop=True)

    # --- single team-week (get_wins compatibility) ----------------------------

    def team_week(
        self,
        team_name: str,
        week: int,
        inject: Optional[Mapping[str, float]] = None,
        all_data: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """One team's raw all-play row for one week — the ``get_wins`` output.
        Empty frame when the team sat out (bye / eliminated)."""
        data = self._scores if all_data is None else all_data
        records = self._week_records(
            week, data, inject=inject, inject_team=team_name if inject is not None else None
        )
        row = [r for r in records if r["Team"] == team_name]
        if not row:
            return pd.DataFrame()
        return pd.DataFrame([row[0]])


def _single_week_all_play(matchups: list[dict]) -> list[dict]:
    """Best-effort single-week all-play from matchup dicts [FIX-A]."""
    teams_stats: dict[str, dict] = {}
    for m in matchups:
        cats = m.get("categories", [])
        for side in ("home", "away"):
            team = m.get(f"{side}_team", "")
            if not team:
                continue
            teams_stats[team] = {c["stat"]: c[f"{side}_value"] for c in cats}

    team_names = list(teams_stats)
    results = []
    for team in team_names:
        my = teams_stats[team]
        mw = total = 0
        for other in team_names:
            if other == team:
                continue
            ot = teams_stats[other]
            wins = sum(1 for s, v in my.items()
                       if (s == "TO" and v < ot.get(s, 0))
                       or (s != "TO" and v > ot.get(s, 0)))
            total += wins
            if wins > len(my) / 2:
                mw += 1
        results.append({"Team": team, "Matchup Wins": mw, "Total Wins": total})
    return results
