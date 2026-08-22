"""Category semantics.

Invariant register: docs/v2/V1_CLASSIFICATION.md §7 "Category semantics".
Ported from V1 tests/test_scoreboard_turnovers.py.

These encode a shipped bug: reversed turnover winners in published recaps.
"""

from __future__ import annotations

import math

import pytest

from backend.domain.categories import (
    NINE_CAT,
    Category,
    CategoryKind,
    Result,
    compare,
    ratio_value,
    tally,
)

PTS = next(c for c in NINE_CAT if c.key == "PTS")
TO = next(c for c in NINE_CAT if c.key == "TO")
FG = next(c for c in NINE_CAT if c.key == "FG_PCT")


# V1: test_category_result_turnovers_lower_wins
def test_turnovers_fewer_wins() -> None:
    assert compare(TO, 8, 12) == (Result.WIN, Result.LOSS)
    assert compare(TO, 12, 8) == (Result.LOSS, Result.WIN)


# V1: test_category_result_other_stats_higher_wins
def test_every_other_category_more_wins() -> None:
    assert compare(PTS, 500, 480) == (Result.WIN, Result.LOSS)
    assert compare(PTS, 480, 500) == (Result.LOSS, Result.WIN)


# V1: test_category_result_ties_and_nan
def test_equal_values_tie() -> None:
    assert compare(PTS, 500, 500) == (Result.TIE, Result.TIE)
    assert compare(TO, 9, 9) == (Result.TIE, Result.TIE)


# charter §10: absence of a result must be distinguishable from a result
@pytest.mark.parametrize("bad", [None, math.nan])
def test_unknown_values_are_unknown_not_tie(bad: float | None) -> None:
    assert compare(PTS, bad, 100) == (Result.UNKNOWN, Result.UNKNOWN)
    assert compare(PTS, 100, bad) == (Result.UNKNOWN, Result.UNKNOWN)
    assert compare(TO, bad, bad) == (Result.UNKNOWN, Result.UNKNOWN)


def test_unknown_is_not_zero_and_not_tie() -> None:
    """A missing value is neither a real zero nor a tie.

    Zero turnovers would *win* the category; unknown must be its own outcome.
    V1's season-stats bug was exactly this conflation (charter §10).
    """
    assert compare(TO, None, 5) == (Result.UNKNOWN, Result.UNKNOWN)
    assert compare(TO, 0, 5) == (Result.WIN, Result.LOSS)


def test_direction_is_data_not_a_special_case() -> None:
    """Inverting the flag inverts the outcome, with no key-name special case."""
    inverted = Category("PTS", "PTS", CategoryKind.COUNTING, higher_is_better=False)
    assert compare(inverted, 500, 480) == (Result.LOSS, Result.WIN)


def test_ratio_derives_from_components() -> None:
    assert ratio_value(FG, {"fgm": 45.0, "fga": 90.0}) == pytest.approx(0.5)


def test_ratio_with_no_attempts_is_unknown_not_zero() -> None:
    """No attempts means no percentage. Zero would drag a team average down."""
    assert ratio_value(FG, {"fgm": 0.0, "fga": 0.0}) is None
    assert ratio_value(FG, {"fgm": 5.0}) is None


def test_ratio_category_rejects_missing_components_at_construction() -> None:
    with pytest.raises(ValueError, match="numerator and denominator"):
        Category("FG_PCT", "FG%", CategoryKind.RATIO, True)


def test_tally_counts_wins_losses_ties_and_unknowns() -> None:
    home = {"PTS": 500, "REB": 200, "AST": 100, "STL": 40, "BLK": 20,
            "TPM": 60, "TO": 80, "fgm": 45.0, "fga": 90.0, "ftm": 40.0, "fta": 50.0}
    away = {"PTS": 480, "REB": 210, "AST": 100, "STL": 30, "BLK": 25,
            "TPM": 55, "TO": 70, "fgm": 40.0, "fga": 100.0, "ftm": 45.0, "fta": 50.0}
    hw, aw, ties, unknowns = tally(NINE_CAT, home, away)
    assert hw + aw + ties + unknowns == len(NINE_CAT)
    assert ties == 1    # AST equal
    assert unknowns == 0  # every category present → nothing undetermined
    assert hw == 4      # PTS, STL, TPM, FG% (.500 vs .400)
    assert aw == 4      # REB, BLK, TO (fewer wins: 70 < 80), FT% (.900 vs .800)


def test_tally_counts_unknowns_separately_and_does_not_inflate_ties() -> None:
    # charter §10: absence of a result must be distinguishable from a result
    home = {"PTS": 500.0, "REB": None}
    away = {"PTS": 480.0, "REB": None}
    hw, aw, ties, unknowns = tally([PTS, next(c for c in NINE_CAT if c.key == "REB")], home, away)
    assert (hw, aw, ties, unknowns) == (1, 0, 0, 1)


def test_tally_prefers_a_directly_supplied_ratio() -> None:
    home = {"FG_PCT": 0.60, "fgm": 1.0, "fga": 100.0}
    away = {"FG_PCT": 0.40, "fgm": 99.0, "fga": 100.0}
    hw, aw, _, _ = tally([FG], home, away)
    assert (hw, aw) == (1, 0)
