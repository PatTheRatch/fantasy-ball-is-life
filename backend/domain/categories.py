"""Scoring categories and head-to-head comparison.

The nine-category set is *data*, not code (charter Decision 11: "the database
should not hardcode exactly nine categories forever"). ``NINE_CAT`` below is a
convenience default for tests and seeding; every function here takes the
categories it should use as an argument.

Direction is a property of the category, not a special case in the comparator.
V1 carried a module-level ``LOWER_IS_BETTER_STATS = {"TO"}`` set, which was the
correct fix for a real inverted-winner bug but put the rule in the interpreter
rather than the row. Here it is ``Category.higher_is_better``.

Ratio categories know their components. A team's weekly FG% is
``sum(fgm) / sum(fga)`` — never the mean of per-player percentages — and that
is only derivable if the category records which stats it is built from.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum


class CategoryKind(StrEnum):
    COUNTING = "counting"
    RATIO = "ratio"


class Result(StrEnum):
    WIN = "W"
    LOSS = "L"
    TIE = "T"
    UNKNOWN = "U"


@dataclass(frozen=True, slots=True)
class Category:
    """One scoring category in a league's configuration."""

    key: str
    short_name: str
    kind: CategoryKind
    higher_is_better: bool
    numerator: str | None = None
    denominator: str | None = None

    def __post_init__(self) -> None:
        if self.kind is CategoryKind.RATIO and not (self.numerator and self.denominator):
            raise ValueError(
                f"ratio category {self.key!r} needs numerator and denominator stats"
            )


#: The conventional 9-cat H2H set. A default for seeding and tests — never a
#: hardcoded assumption in logic. Turnovers are the only lower-is-better
#: category, and are stored throughout as natural positive counts.
NINE_CAT: tuple[Category, ...] = (
    Category("PTS", "PTS", CategoryKind.COUNTING, True),
    Category("REB", "REB", CategoryKind.COUNTING, True),
    Category("AST", "AST", CategoryKind.COUNTING, True),
    Category("STL", "STL", CategoryKind.COUNTING, True),
    Category("BLK", "BLK", CategoryKind.COUNTING, True),
    Category("TPM", "3PM", CategoryKind.COUNTING, True),
    Category("TO", "TO", CategoryKind.COUNTING, False),
    Category("FG_PCT", "FG%", CategoryKind.RATIO, True, numerator="fgm", denominator="fga"),
    Category("FT_PCT", "FT%", CategoryKind.RATIO, True, numerator="ftm", denominator="fta"),
)


def _comparable(value: float | None) -> bool:
    """A value participates in a comparison only if it is a real number.

    ``None`` and NaN both mean "we do not know", which is distinct from zero.
    V1 relied on NaN's comparison semantics making every branch fall through to
    a tie; making it explicit means a missing value can never be mistaken for a
    genuine zero. Unknown is its own outcome, not a tie (charter §10: absence
    of a result must be distinguishable from a result).
    """
    return value is not None and not math.isnan(value)


def compare(category: Category, home: float | None, away: float | None) -> tuple[Result, Result]:
    """Return ``(home_result, away_result)`` for one category.

    A non-comparable value on either side yields ``UNKNOWN`` on both — a
    missing stat is not a tie and must never be recorded as one (charter §10).
    Direction comes from the category, so turnovers need no special case at the
    call site.
    """
    if not _comparable(home) or not _comparable(away):
        return Result.UNKNOWN, Result.UNKNOWN

    assert home is not None and away is not None  # narrowed by _comparable
    if home == away:
        return Result.TIE, Result.TIE

    home_ahead = home > away if category.higher_is_better else home < away
    return (Result.WIN, Result.LOSS) if home_ahead else (Result.LOSS, Result.WIN)


def ratio_value(
    category: Category, stats: Mapping[str, float | None]
) -> float | None:
    """Derive a ratio category from its component stats.

    Returns ``None`` when either component is unknown or the denominator is
    zero — an undefined percentage, not a zero one. Callers must keep that
    distinction: a player with no attempts has no FG%, and folding them in as
    0.0 silently drags a team average down.
    """
    if category.kind is not CategoryKind.RATIO:
        raise ValueError(f"{category.key!r} is not a ratio category")

    assert category.numerator is not None and category.denominator is not None
    num = stats.get(category.numerator)
    den = stats.get(category.denominator)
    if not _comparable(num) or not _comparable(den) or den == 0:
        return None

    assert num is not None and den is not None
    return num / den


def tally(
    categories: Sequence[Category],
    home: Mapping[str, float | None],
    away: Mapping[str, float | None],
) -> tuple[int, int, int, int]:
    """Category record for one matchup as ``(home_wins, away_wins, ties, unknowns)``.

    Ratio categories are derived from their components when present, so a
    caller may supply either the ratio directly or the makes/attempts it is
    built from. Unknown categories are counted separately and never fall into
    the tie count (charter §10).
    """
    home_wins = away_wins = ties = unknowns = 0
    for cat in categories:
        if cat.kind is CategoryKind.RATIO:
            h = home.get(cat.key)
            a = away.get(cat.key)
            if not _comparable(h):
                h = ratio_value(cat, home)
            if not _comparable(a):
                a = ratio_value(cat, away)
        else:
            h = home.get(cat.key)
            a = away.get(cat.key)

        result, _ = compare(cat, h, a)
        if result is Result.WIN:
            home_wins += 1
        elif result is Result.LOSS:
            away_wins += 1
        elif result is Result.TIE:
            ties += 1
        else:
            unknowns += 1
    return home_wins, away_wins, ties, unknowns
