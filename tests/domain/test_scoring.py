"""All-play scoring.

Invariant register: docs/v2/V1_CLASSIFICATION.md §7 "All-play / playoffs".
Ported from V1 tests/test_allplay_playoff_participants.py.

These encode a shipped bug: week 21 returned rankings for 14 teams when only
11 were active, and each synthetic team was awarded 11 turnover wins.
"""

from __future__ import annotations

from backend.domain.categories import NINE_CAT, Category, CategoryKind
from backend.domain.scoring import TeamWeek, all_play_totals, all_play_week

PTS = Category("PTS", "PTS", CategoryKind.COUNTING, True)
TO = Category("TO", "TO", CategoryKind.COUNTING, False)
SIMPLE = (PTS, TO)


def team(name: str, pts: float, to: float) -> TeamWeek:
    return TeamWeek(name, {"PTS": pts, "TO": to})


# V1: test_regular_week_all_14_teams_participate
def test_every_supplied_team_participates() -> None:
    teams = [team(f"t{i}", 400 + i, 70) for i in range(14)]
    records = all_play_week(teams, SIMPLE)
    assert len(records) == 14
    assert {r.team_id for r in records} == {f"t{i}" for i in range(14)}


# V1: test_early_playoff_two_byes_excluded / test_late_playoff_four_eliminated_excluded
def test_teams_that_did_not_play_are_absent_not_zero_filled() -> None:
    """A bye or eliminated team is simply not supplied, so cannot appear."""
    active = [team("a", 500, 60), team("b", 480, 70), team("c", 460, 80)]
    records = all_play_week(active, SIMPLE)
    assert {r.team_id for r in records} == {"a", "b", "c"}


# V1: test_get_wins_ignores_ghost_league_teams
def test_a_ghost_team_cannot_collect_wins() -> None:
    """The V1 bug in its purest form.

    A zero-filled phantom would beat everyone at turnovers, because 0 is fewer
    than any real count. Since participants are supplied rather than inferred,
    there is no phantom to collect them.
    """
    active = [team("a", 500, 60), team("b", 480, 70)]
    records = all_play_week(active, SIMPLE)
    total_to_wins = sum(
        1 for r in records for _ in r.beaten
    )
    assert len(records) == 2
    assert total_to_wins <= 2
    assert "ghost" not in {r.team_id for r in records}


# V1: test_get_wins_bye_team_returns_empty_frame
def test_fewer_than_two_teams_is_empty_not_an_error() -> None:
    assert all_play_week([team("solo", 500, 60)], SIMPLE) == []
    assert all_play_week([], SIMPLE) == []


# V1: test_turnovers_fewer_is_better_in_allplay
def test_turnover_direction_holds_inside_all_play() -> None:
    """Identical points, so turnovers alone decide every comparison."""
    teams = [team("clean", 500, 50), team("sloppy", 500, 90)]
    records = {r.team_id: r for r in all_play_week(teams, SIMPLE)}
    assert records["clean"].beaten == ("sloppy",)
    assert records["sloppy"].lost_to == ("clean",)


def test_matchup_is_a_tie_when_categories_split_evenly() -> None:
    """4-4-1 is a tie, not a loss for both sides."""
    a = TeamWeek("a", {"PTS": 500, "TO": 90})   # wins PTS, loses TO
    b = TeamWeek("b", {"PTS": 480, "TO": 50})
    records = {r.team_id: r for r in all_play_week([a, b], SIMPLE)}
    assert records["a"].matchup_ties == 1
    assert records["a"].matchup_wins == 0
    assert records["b"].tied_with == ("a",)


def test_category_records_are_symmetric() -> None:
    """Every win is someone's loss; totals must balance across the league."""
    teams = [team("a", 500, 60), team("b", 480, 70), team("c", 460, 65)]
    records = all_play_week(teams, NINE_CAT)
    assert sum(r.category_wins for r in records) == sum(r.category_losses for r in records)


def test_unknown_values_tie_rather_than_lose() -> None:
    known = TeamWeek("known", {"PTS": 500, "TO": 60})
    unknown = TeamWeek("unknown", {"PTS": None, "TO": None})
    records = {r.team_id: r for r in all_play_week([known, unknown], SIMPLE)}
    assert records["unknown"].category_losses == 0
    assert records["unknown"].category_ties == 2


def test_totals_aggregate_across_weeks_and_drop_opponent_lists() -> None:
    w1 = all_play_week([team("a", 500, 60), team("b", 480, 70)], SIMPLE)
    w2 = all_play_week([team("a", 400, 90), team("b", 520, 50)], SIMPLE)
    totals = {r.team_id: r for r in all_play_totals([w1, w2])}
    assert totals["a"].category_wins + totals["b"].category_wins == 4
    assert totals["a"].beaten == ()


def test_totals_ordering_is_deterministic() -> None:
    """Equal records must not reorder between runs."""
    week = all_play_week([team("z", 500, 60), team("a", 500, 60)], SIMPLE)
    first = [r.team_id for r in all_play_totals([week])]
    assert first == sorted(first)
