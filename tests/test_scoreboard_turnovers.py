"""Regression tests for turnover (TO) direction across the scoreboard layer.

Turnovers are stored as natural positive counts throughout the data layer;
"fewer is better" is applied once at comparison time. These tests lock in the
live-reproduced bug where a 57-vs-89 turnover category was awarded to the team
with *more* turnovers because the feed pre-negated TO and the recap layer then
inverted a second time.
"""
from types import SimpleNamespace

import math

from backend.league import data_feed as feed
from backend.recaps.assemble import STAT_ORDER, canonical_matchups

NINE_CATS = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]


def _matchup(home, away, home_stats, away_stats):
    return SimpleNamespace(
        home_team=SimpleNamespace(team_name=home),
        away_team=SimpleNamespace(team_name=away),
        home_stats={k: {"value": v} for k, v in home_stats.items()},
        away_stats={k: {"value": v} for k, v in away_stats.items()},
    )


class _FakeLeague:
    def __init__(self, matchups, current_matchup_period=1):
        self._matchups = matchups
        self.currentMatchupPeriod = current_matchup_period

    def box_scores(self, matchup_period=None):
        return self._matchups


# --- category_result: single source of truth for category direction ----------

def test_category_result_turnovers_lower_wins():
    # Live case: home 57 TO, away 89 TO -> home (fewer) wins.
    assert feed.category_result("TO", 57, 89) == ("W", "L")
    assert feed.category_result("TO", 89, 57) == ("L", "W")


def test_category_result_other_stats_higher_wins():
    assert feed.category_result("PTS", 510, 480) == ("W", "L")
    assert feed.category_result("PTS", 480, 510) == ("L", "W")


def test_category_result_ties_and_nan():
    assert feed.category_result("TO", 40, 40) == ("T", "T")
    assert feed.category_result("PTS", 40, 40) == ("T", "T")
    # Non-comparable values tie rather than silently awarding a win.
    assert feed.category_result("TO", math.nan, 40) == ("T", "T")
    assert feed.category_result("PTS", math.nan, 40) == ("T", "T")


# --- get_current_scoreboard: no more TO negation -----------------------------

def test_get_current_scoreboard_keeps_turnovers_positive():
    matchup = _matchup(
        "Alpha",
        "Beta",
        {"PTS": 510, "TO": 57},
        {"PTS": 480, "TO": 89},
    )
    handles = feed.ESPNHandles(league=_FakeLeague([matchup]))

    df = feed.get_current_scoreboard(handles, scoring_period=1)

    to_row = df[df["stat"] == "TO"].iloc[0]
    assert to_row["current_home_score"] == 57
    assert to_row["current_away_score"] == 89
    # Non-TO stats are untouched and remain natural values.
    pts_row = df[df["stat"] == "PTS"].iloc[0]
    assert pts_row["current_home_score"] == 510
    assert pts_row["current_away_score"] == 480


def test_scoreboard_feeds_correct_turnover_winner_to_recap():
    """End-to-end: raw feed rows -> canonical_matchups awards TO to fewer turnovers."""
    home_stats = {stat: 100 for stat in NINE_CATS}
    away_stats = {stat: 90 for stat in NINE_CATS}
    home_stats["TO"] = 57  # home has fewer turnovers -> home should win TO
    away_stats["TO"] = 89
    handles = feed.ESPNHandles(
        league=_FakeLeague([_matchup("Alpha", "Beta", home_stats, away_stats)])
    )

    df = feed.get_current_scoreboard(handles, scoring_period=1)
    matchup = canonical_matchups(df.to_dict("records"), week=1)[0]

    turnover = next(c for c in matchup["categories"] if c["stat"] == "TO")
    assert turnover["home_value"] == 57
    assert turnover["away_value"] == 89
    assert turnover["winner"] == "home"
    # All nine categories present and won by home (higher on 8, fewer TO on 1).
    assert {c["stat"] for c in matchup["categories"]} == set(STAT_ORDER)
    assert matchup["home_category_wins"] == 9
    assert matchup["winner"] == "Alpha"
