"""Standings as a deterministic fold over completed periods.

Standings are **not stored**. They are computed from the matchup results of
final periods 1..N, so "standings as of week 7" is a first-class question with
one correct answer.

V1 stored standings as rolling latest state, which meant every past-week view
rendered the end-of-season table. The fix there was to recompute from per-week
scoreboards anyway — this is that fold, promoted to the only path. Storing a
derivable, order-dependent aggregate is how that class of bug happens.

Scoring is **H2H each-category**: a team's record is the sum of category wins,
losses and ties, not matchup wins. A 7-1-1 week adds 7-1-1, not 1-0. Win
percentage counts a tie as half a win and is expressed 0-100.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from backend.domain.categories import Category, tally


@dataclass(frozen=True, slots=True)
class MatchupResult:
    """One completed matchup's category outcome.

    ``away_team_id`` is None for a bye — the home side simply did not play an
    opponent, and neither side accrues a record. Byes are represented, never
    zero-filled.
    """

    home_team_id: str
    away_team_id: str | None
    home_category_wins: int
    away_category_wins: int
    category_ties: int


@dataclass(frozen=True, slots=True)
class StandingRow:
    team_id: str
    wins: int
    losses: int
    ties: int
    win_pct: float
    rank: int

    @property
    def played(self) -> int:
        return self.wins + self.losses + self.ties


def matchup_from_stats(
    home_team_id: str,
    away_team_id: str | None,
    home_values: dict[str, float | None],
    away_values: dict[str, float | None],
    categories: Sequence[Category],
) -> MatchupResult:
    """Build a :class:`MatchupResult` by tallying two teams' category values."""
    if away_team_id is None:
        return MatchupResult(home_team_id, None, 0, 0, 0)
    hw, aw, ties = tally(categories, home_values, away_values)
    return MatchupResult(home_team_id, away_team_id, hw, aw, ties)


def standings_through(
    results: Sequence[MatchupResult],
) -> list[StandingRow]:
    """Fold completed matchup results into a ranked standings table.

    Pass only the periods you want counted — that is what makes standings "as
    of" any point in the season, rather than always end-of-season.

    Empty input yields an empty table, not an error: a season before its first
    completed period genuinely has no standings, and that is a legitimate state
    to render rather than a failure.
    """
    records: dict[str, list[int]] = {}

    def acc(team_id: str) -> list[int]:
        return records.setdefault(team_id, [0, 0, 0])

    for r in results:
        if r.away_team_id is None:
            # A bye. Ensure the team still appears in the table with a zero
            # record rather than vanishing from the league.
            acc(r.home_team_id)
            continue
        home = acc(r.home_team_id)
        home[0] += r.home_category_wins
        home[1] += r.away_category_wins
        home[2] += r.category_ties

        away = acc(r.away_team_id)
        away[0] += r.away_category_wins
        away[1] += r.home_category_wins
        away[2] += r.category_ties

    rows: list[tuple[str, int, int, int, float]] = []
    for team_id, (w, losses, t) in records.items():
        total = w + losses + t
        pct = ((w + 0.5 * t) / total * 100) if total > 0 else 0.0
        rows.append((team_id, w, losses, t, round(pct, 1)))

    # Deterministic: win% desc, then wins desc, then team id for a stable tie
    # break. V1 sorted on the first two only, so equal teams could reorder
    # between renders.
    rows.sort(key=lambda r: (-r[4], -r[1], r[0]))

    return [
        StandingRow(team_id=tid, wins=w, losses=losses, ties=t, win_pct=pct, rank=i + 1)
        for i, (tid, w, losses, t, pct) in enumerate(rows)
    ]
