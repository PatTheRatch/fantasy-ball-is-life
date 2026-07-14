"""PR C — playoff participant correctness for MyLeague all-play.

Weekly all-play must be contested only among teams with a real matchup that
week. Bye / eliminated teams are excluded entirely (never zero-filled), so they
neither earn phantom category wins nor drag down active teams. Turnovers stay
lower-is-better via the shared LOWER_IS_BETTER_STATS constant.

These build a MyLeague via __new__ (no ESPN construction) and feed synthetic
weekly matchup data straight into get_wins / get_universe_wins.
"""
import pandas as pd
import pytest

from backend.league.data_feed import LOWER_IS_BETTER_STATS
from backend.league.fantasy import MyLeague

STAT_CATS = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]


def _league(team_names):
    # `team_names` isn't stored on the instance (MyLeague no longer has that
    # attribute) -- kept as a parameter purely so each call site documents
    # which teams the scenario involves.
    lg = MyLeague.__new__(MyLeague)  # skip ESPN __init__
    lg.stat_categories = list(STAT_CATS)
    lg.currentMatchupPeriod = 1
    lg.schedule = pd.DataFrame({"Week": [], "Team": [], "Opponent": []})
    return lg


def _week_data(week, team_stats):
    rows = []
    for team, stats in team_stats.items():
        row = {"Week": week, "Team": team}
        for cat in STAT_CATS:
            row[cat] = stats.get(cat, 10.0)
        rows.append(row)
    return pd.DataFrame(rows)


def _uniform_active(teams):
    """All cats equal (=> ties) except a unique PTS so ranking is deterministic."""
    stats = {t: {cat: 10.0 for cat in STAT_CATS} for t in teams}
    for i, t in enumerate(teams):
        stats[t]["PTS"] = 100.0 + i
    return stats


def test_to_is_registered_as_lower_is_better():
    assert "TO" in LOWER_IS_BETTER_STATS


def test_regular_week_all_14_teams_participate():
    teams = [f"T{i}" for i in range(1, 15)]
    lg = _league(teams)
    data = _week_data(1, _uniform_active(teams))
    lg.get_all_matchup_data = lambda: data

    out = lg.get_universe_wins(weeks=[1])

    assert set(out["Team"]) == set(teams)
    assert len(out) == 14
    # 9 categories * 13 opponents = 117 all-play decisions each.
    for _, r in out.iterrows():
        assert r["Total Wins"] + r["Total Losses"] + r["Total Ties"] == 117


def test_early_playoff_two_byes_excluded():
    teams = [f"T{i}" for i in range(1, 15)]  # league still has 14 teams
    active = teams[:12]
    lg = _league(teams)
    data = _week_data(20, _uniform_active(active))  # only 12 teams have rows
    lg.get_all_matchup_data = lambda: data

    out = lg.get_universe_wins(weeks=[20])

    assert set(out["Team"]) == set(active)  # the 2 bye teams are absent
    assert len(out) == 12
    for _, r in out.iterrows():
        assert r["Total Wins"] + r["Total Losses"] + r["Total Ties"] == 9 * 11  # 99
    # No ghost inflation: nobody can exceed 99 decisions (would be 117 with ghosts).
    assert out["Total Wins"].max() <= 99


def test_late_playoff_four_eliminated_excluded():
    teams = [f"T{i}" for i in range(1, 15)]
    active = teams[:10]
    lg = _league(teams)
    data = _week_data(21, _uniform_active(active))
    lg.get_all_matchup_data = lambda: data

    out = lg.get_universe_wins(weeks=[21])

    assert set(out["Team"]) == set(active)
    assert len(out) == 10
    for _, r in out.iterrows():
        assert r["Total Wins"] + r["Total Losses"] + r["Total Ties"] == 9 * 9  # 81


def test_get_wins_ignores_ghost_league_teams():
    # League has a 4th team ("Ghost") with no matchup row this week.
    lg = _league(["A", "B", "C", "Ghost"])
    stats = {t: {cat: 10.0 for cat in STAT_CATS} for t in ["A", "B", "C"]}
    stats["A"]["PTS"], stats["B"]["PTS"], stats["C"]["PTS"] = 50, 60, 70
    data = _week_data(21, stats)

    row = lg.get_wins("A", 21, all_data=data)

    # A plays only B and C (2 opponents), never Ghost: 9 cats * 2 = 18 decisions.
    total = row["Total Wins"].iloc[0] + row["Total Losses"].iloc[0] + row["Total Ties"].iloc[0]
    assert total == 18


def test_get_wins_bye_team_returns_empty_frame():
    lg = _league(["A", "B", "Bye"])
    data = _week_data(21, {t: {cat: 10.0 for cat in STAT_CATS} for t in ["A", "B"]})
    assert lg.get_wins("Bye", 21, all_data=data).empty


def test_turnovers_fewer_is_better_in_allplay():
    lg = _league(["Low", "High"])
    stats = {
        "Low": {cat: 10.0 for cat in STAT_CATS},
        "High": {cat: 10.0 for cat in STAT_CATS},
    }
    stats["Low"]["TO"] = 5.0    # fewer turnovers -> should WIN the TO category
    stats["High"]["TO"] = 20.0
    data = _week_data(1, stats)

    low = lg.get_wins("Low", 1, all_data=data)
    high = lg.get_wins("High", 1, all_data=data)

    assert low["TO Wins"].iloc[0] == 1
    assert high["TO Wins"].iloc[0] == 0
    # Downstream convention (power rankings + draft optimizer) expects the TO
    # stat total negated; confirm we preserved that.
    assert low["TO"].iloc[0] == -5.0
    assert high["TO"].iloc[0] == -20.0
