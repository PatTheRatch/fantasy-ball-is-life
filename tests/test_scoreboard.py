"""Unit tests for WeeklyScoreboard — the vectorized all-play computation.

These build a scoreboard straight from a hand-written tidy table (no ESPN, no
`League` mock), which is the whole point of extracting it from `MyLeague`.
"""
import numpy as np
import pandas as pd
import pytest

from backend.league.scoreboard import WeeklyScoreboard

CATS = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]


def _scores(rows):
    """rows: list of (week, team, {cat: val}); missing cats default to 10.0."""
    out = []
    for week, team, stats in rows:
        rec = {"Week": week, "Team": team}
        for c in CATS:
            rec[c] = stats.get(c, 10.0)
        out.append(rec)
    return pd.DataFrame(out)


def _schedule(rows):
    return pd.DataFrame(rows, columns=["Week", "Team", "Opponent"])


def _uniform(week, teams):
    """All cats tied except a unique PTS per team (deterministic ordering)."""
    return [(week, t, {"PTS": 100.0 + i}) for i, t in enumerate(teams)]


def _board(score_rows, sched_rows=()):
    return WeeklyScoreboard(_scores(score_rows), _schedule(list(sched_rows)))


# --- basic all-play shape -----------------------------------------------------

def test_single_week_total_decisions():
    teams = [f"T{i}" for i in range(4)]
    board = _board(_uniform(1, teams))
    out = board.all_play(weeks=[1])
    assert set(out["Team"]) == set(teams)
    # 9 categories * 3 opponents = 27 decisions each.
    for _, r in out.iterrows():
        assert r["Total Wins"] + r["Total Losses"] + r["Total Ties"] == 27


def test_single_week_has_list_columns_multi_week_drops_them():
    teams = ["A", "B", "C"]
    board = _board(_uniform(1, teams) + _uniform(2, teams))
    single = board.all_play(weeks=[1])
    multi = board.all_play(weeks=[1, 2])
    for col in ("Lost To", "Tied With", "Beaten"):
        assert col in single.columns
        assert col not in multi.columns


def test_turnovers_lower_is_better_and_negated_total():
    board = _board([
        (1, "Low", {"TO": 5.0}),
        (1, "High", {"TO": 20.0}),
    ])
    out = board.all_play(weeks=[1]).set_index("Team")
    assert out.loc["Low", "TO Wins"] == 1
    assert out.loc["High", "TO Wins"] == 0
    # Downstream convention: TO total stored negated.
    assert out.loc["Low", "TO"] == -5.0
    assert out.loc["High", "TO"] == -20.0


# --- playoff / bye exclusion --------------------------------------------------

def test_absent_team_does_not_participate():
    # League has D, but D has no row in week 1 → excluded, not zero-filled.
    board = _board(_uniform(1, ["A", "B", "C"]))
    out = board.all_play(weeks=[1])
    assert set(out["Team"]) == {"A", "B", "C"}
    for _, r in out.iterrows():
        assert r["Total Wins"] + r["Total Losses"] + r["Total Ties"] == 9 * 2


def test_team_week_bye_returns_empty():
    board = _board(_uniform(1, ["A", "B"]))
    assert board.team_week("Ghost", 1).empty


def test_all_play_empty_when_fewer_than_two_teams():
    board = _board([(1, "Solo", {})])
    assert board.all_play(weeks=[1]).empty


def test_missing_week_raises_valueerror():
    board = _board(_uniform(1, ["A", "B"]))
    with pytest.raises(ValueError):
        board.all_play(weeks=[5])


# --- actual (scheduled-opponent) record ---------------------------------------

def test_actual_record_uses_scheduled_opponent():
    # A beats B on PTS only; A vs C not scheduled. Actual = only vs B.
    board = _board(
        [
            (1, "A", {"PTS": 100}),
            (1, "B", {"PTS": 50}),
            (1, "C", {"PTS": 40}),
        ],
        [(1, "A", "B"), (1, "B", "A")],
    )
    row = board.all_play(weeks=[1]).set_index("Team").loc["A"]
    # Actual is 9 categories vs B: A wins PTS, ties the other 8.
    assert row["Actual Wins"] + row["Actual Losses"] + row["Actual Ties"] == 9
    assert row["Actual Wins"] == 1  # PTS


# --- max_week / aggregation ---------------------------------------------------

def test_max_week():
    board = _board(_uniform(1, ["A", "B"]) + _uniform(4, ["A", "B"]))
    assert board.max_week == 4


def test_multi_week_sums_decisions():
    teams = ["A", "B", "C"]
    board = _board(_uniform(1, teams) + _uniform(2, teams))
    out = board.all_play(weeks=[1, 2]).set_index("Team")
    # Two weeks * 9 cats * 2 opponents = 36 decisions.
    for t in teams:
        r = out.loc[t]
        assert r["Total Wins"] + r["Total Losses"] + r["Total Ties"] == 36
