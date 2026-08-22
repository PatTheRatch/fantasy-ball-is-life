"""Standings as a fold over completed periods.

Invariant register: docs/v2/V1_CLASSIFICATION.md §7 "Historical correctness".
Ported from V1 tests/test_per_week_standings.py.

These encode a shipped bug: every past-week view rendered the end-of-season
table, because standings were stored as rolling latest state.
"""

from __future__ import annotations

from backend.domain.categories import NINE_CAT
from backend.domain.standings import MatchupResult, matchup_from_stats, standings_through


def wk(home: str, away: str, hw: int, aw: int, ties: int = 0) -> MatchupResult:
    return MatchupResult(home, away, hw, aw, ties)


# V1: test_sums_category_wins_across_weeks
def test_record_sums_categories_not_matchups() -> None:
    """H2H each-category: a 7-1-1 week adds 7-1-1, not 1-0."""
    rows = {r.team_id: r for r in standings_through([wk("a", "b", 7, 1, 1)])}
    assert (rows["a"].wins, rows["a"].losses, rows["a"].ties) == (7, 1, 1)
    assert (rows["b"].wins, rows["b"].losses, rows["b"].ties) == (1, 7, 1)


# V1: test_standing_ranks_by_win_pct
def test_ranks_by_win_pct() -> None:
    rows = standings_through([wk("a", "b", 8, 1), wk("c", "d", 5, 4)])
    assert [r.team_id for r in rows] == ["a", "c", "d", "b"]
    assert [r.rank for r in rows] == [1, 2, 3, 4]


# V1: test_win_pct_is_0_to_100
def test_win_pct_is_0_to_100_and_a_tie_is_half_a_win() -> None:
    rows = {r.team_id: r for r in standings_through([wk("a", "b", 4, 4, 1)])}
    assert rows["a"].win_pct == 50.0
    assert rows["b"].win_pct == 50.0
    perfect = {r.team_id: r for r in standings_through([wk("a", "b", 9, 0)])}
    assert perfect["a"].win_pct == 100.0
    assert perfect["b"].win_pct == 0.0


# V1: test_fewer_weeks_yields_different_table
def test_standings_as_of_an_earlier_period_differ() -> None:
    """The whole point: pass fewer periods, get the table as it stood then."""
    week1 = [wk("a", "b", 9, 0)]
    week2 = [wk("a", "b", 0, 9)]
    after_one = {r.team_id: r for r in standings_through(week1)}
    after_two = {r.team_id: r for r in standings_through(week1 + week2)}
    assert after_one["a"].win_pct == 100.0
    assert after_two["a"].win_pct == 50.0


# V1: test_derives_standings_from_weeks_not_rolling_state
def test_result_depends_only_on_the_periods_supplied() -> None:
    """No hidden state: the same input always yields the same table."""
    results = [wk("a", "b", 6, 3), wk("a", "b", 2, 7)]
    assert standings_through(results) == standings_through(results)


# V1: test_empty_input_is_empty_not_error
def test_empty_input_is_empty_not_an_error() -> None:
    assert standings_through([]) == []


def test_a_bye_keeps_the_team_in_the_table_with_no_record() -> None:
    """A team on bye must not vanish from the league that week."""
    results = [wk("a", "b", 5, 4), MatchupResult("c", None, 0, 0, 0)]
    rows = {r.team_id: r for r in standings_through(results)}
    assert set(rows) == {"a", "b", "c"}
    assert rows["c"].played == 0
    assert rows["c"].win_pct == 0.0


def test_ordering_is_stable_for_identical_records() -> None:
    rows = standings_through([wk("z", "a", 5, 4), wk("m", "b", 5, 4)])
    winners = [r.team_id for r in rows if r.wins == 5]
    assert winners == sorted(winners)


def test_matchup_from_stats_tallies_real_category_values() -> None:
    home = {"PTS": 500, "REB": 200, "AST": 100, "STL": 40, "BLK": 20,
            "TPM": 60, "TO": 80, "fgm": 45.0, "fga": 90.0, "ftm": 40.0, "fta": 50.0}
    away = {"PTS": 480, "REB": 210, "AST": 100, "STL": 30, "BLK": 25,
            "TPM": 55, "TO": 70, "fgm": 40.0, "fga": 100.0, "ftm": 45.0, "fta": 50.0}
    result = matchup_from_stats("a", "b", home, away, NINE_CAT)
    assert result.home_category_wins == 4
    assert result.away_category_wins == 4
    assert result.category_ties == 1


def test_matchup_from_stats_handles_a_bye() -> None:
    result = matchup_from_stats("a", None, {}, {}, NINE_CAT)
    assert result.away_team_id is None
    assert (result.home_category_wins, result.away_category_wins) == (0, 0)


def test_unknown_categories_fold_wlt_from_decided_only() -> None:
    # charter §10: absence of a result must be distinguishable from a result
    # 4 home wins, 3 away wins, 0 ties, 2 unknowns → neither side accrues a tie.
    result = MatchupResult("a", "b", 4, 3, 0, category_unknowns=2)
    rows = {r.team_id: r for r in standings_through([result])}
    assert (rows["a"].wins, rows["a"].losses, rows["a"].ties, rows["a"].unknown) == (4, 3, 0, 2)
    assert (rows["b"].wins, rows["b"].losses, rows["b"].ties, rows["b"].unknown) == (3, 4, 0, 2)


def test_win_pct_denominator_excludes_unknowns() -> None:
    # charter §10: an unknown category must never dilute or inflate a win %.
    with_unknown = MatchupResult("a", "b", 4, 3, 0, category_unknowns=2)
    without = MatchupResult("a", "b", 4, 3, 0)
    a_with = {r.team_id: r for r in standings_through([with_unknown])}["a"]
    a_without = {r.team_id: r for r in standings_through([without])}["a"]
    # 4-3 over 7 decided categories, not 4-3-2 over 9.
    assert a_with.win_pct == 57.1
    assert a_with.win_pct == a_without.win_pct
    assert a_with.played == 7  # unknown does not inflate games played
