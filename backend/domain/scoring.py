"""All-play scoring — every team against every other team, per week.

Ported from V1's ``WeeklyScoreboard``, which was one of the genuinely good
pieces of that codebase. Two changes:

* **No pandas.** V1 vectorised this because it had been a per-team Python loop
  issuing ESPN calls. The arithmetic itself is tiny — twelve teams by nine
  categories is ~1,300 comparisons for a week — so plain Python is fast enough
  and keeps the domain layer importable with no heavy dependency.
* **Participants are supplied, never inferred.** V1 reindexed every week to the
  full league and zero-filled the gaps, which produced rankings for teams that
  had no matchup: week 21 returned 14 teams when 11 were active, and each
  synthetic team collected 11 turnover wins. Here a team that did not play is
  simply absent from the input and therefore absent from the output.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from backend.domain.categories import Category, CategoryKind, Result, compare, ratio_value


@dataclass(frozen=True, slots=True)
class TeamWeek:
    """One team's category values for one week.

    ``values`` may carry ratio categories directly, or the component stats they
    derive from, or both. Absent and NaN values are "unknown" and tie.
    """

    team_id: str
    values: Mapping[str, float | None]


@dataclass(frozen=True, slots=True)
class AllPlayRecord:
    """One team's all-play result for one week."""

    team_id: str
    category_wins: int
    category_losses: int
    category_ties: int
    matchup_wins: int
    matchup_losses: int
    matchup_ties: int
    beaten: tuple[str, ...] = field(default=())
    lost_to: tuple[str, ...] = field(default=())
    tied_with: tuple[str, ...] = field(default=())

    @property
    def total_category_results(self) -> int:
        return self.category_wins + self.category_losses + self.category_ties


def _resolved(cat: Category, values: Mapping[str, float | None]) -> float | None:
    """A category's value, deriving ratios from components when needed."""
    direct = values.get(cat.key)
    if direct is not None or cat.kind is not CategoryKind.RATIO:
        return direct
    return ratio_value(cat, values)


def all_play_week(
    teams: Sequence[TeamWeek],
    categories: Sequence[Category],
) -> list[AllPlayRecord]:
    """All-play records for one week.

    Every supplied team is compared against every other supplied team. Fewer
    than two teams means nobody has an opponent, which is an empty result and
    not an error — a bye week, or a playoff round with one live matchup.

    A team "wins" a hypothetical matchup when it takes more categories than it
    loses; an equal split is a tie. This matches V1's primary implementation
    (``local_wins > local_losses``) exactly. Note V1 also carried a cruder
    fallback helper using ``wins > len(cats) / 2``, which mis-scores a 4-4-1
    week as a loss for both sides — that variant is deliberately not ported.
    """
    if len(teams) < 2:
        return []

    resolved: dict[str, dict[str, float | None]] = {
        t.team_id: {c.key: _resolved(c, t.values) for c in categories} for t in teams
    }

    records: list[AllPlayRecord] = []
    for team in teams:
        mine = resolved[team.team_id]
        cat_w = cat_l = cat_t = 0
        mu_w = mu_l = mu_t = 0
        beaten: list[str] = []
        lost_to: list[str] = []
        tied_with: list[str] = []

        for other in teams:
            if other.team_id == team.team_id:
                continue
            theirs = resolved[other.team_id]

            w = losses = ties = 0
            for cat in categories:
                result, _ = compare(cat, mine[cat.key], theirs[cat.key])
                if result is Result.WIN:
                    w += 1
                elif result is Result.LOSS:
                    losses += 1
                else:
                    ties += 1

            cat_w += w
            cat_l += losses
            cat_t += ties

            if w > losses:
                mu_w += 1
                beaten.append(other.team_id)
            elif losses > w:
                mu_l += 1
                lost_to.append(other.team_id)
            else:
                mu_t += 1
                tied_with.append(other.team_id)

        records.append(
            AllPlayRecord(
                team_id=team.team_id,
                category_wins=cat_w,
                category_losses=cat_l,
                category_ties=cat_t,
                matchup_wins=mu_w,
                matchup_losses=mu_l,
                matchup_ties=mu_t,
                beaten=tuple(beaten),
                lost_to=tuple(lost_to),
                tied_with=tuple(tied_with),
            )
        )

    return records


def all_play_totals(
    weeks: Sequence[Sequence[AllPlayRecord]],
) -> list[AllPlayRecord]:
    """Aggregate per-week all-play records across weeks.

    Per-opponent lists are dropped: "who beat whom" is a single-week fact and
    aggregating it across weeks would be meaningless. Ordering is by category
    wins then matchup wins, both descending, with the team id as a stable
    tiebreak so the output is deterministic.
    """
    totals: dict[str, list[int]] = {}
    for week in weeks:
        for rec in week:
            acc = totals.setdefault(rec.team_id, [0, 0, 0, 0, 0, 0])
            acc[0] += rec.category_wins
            acc[1] += rec.category_losses
            acc[2] += rec.category_ties
            acc[3] += rec.matchup_wins
            acc[4] += rec.matchup_losses
            acc[5] += rec.matchup_ties

    out = [
        AllPlayRecord(
            team_id=team_id,
            category_wins=a[0],
            category_losses=a[1],
            category_ties=a[2],
            matchup_wins=a[3],
            matchup_losses=a[4],
            matchup_ties=a[5],
        )
        for team_id, a in totals.items()
    ]
    out.sort(key=lambda r: (-r.category_wins, -r.matchup_wins, r.team_id))
    return out
