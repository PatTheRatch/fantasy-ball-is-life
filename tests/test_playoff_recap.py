"""Playoff-narrative recap feature: round detection, advancement, next-round
pairing, evidence-bound generation validation, and WhatsApp formatting.
"""
from unittest.mock import Mock

import pytest

from backend.commentary import generate
from backend.commentary.schemas import (
    DataQualityReport,
    PlayoffContext,
    RecapGeneratedContent,
    WeeklyFactSnapshot,
)
from backend.recaps import assemble, playoffs
from backend.recaps.sharing import format_share_text


# --- playoffs.playoff_round --------------------------------------------------

def test_playoff_round_none_during_regular_season():
    assert (
        playoffs.playoff_round(
            week=10,
            reg_season_count=19,
            playoff_team_count=6,
            playoff_matchup_period_length=1,
        )
        is None
    )


def test_playoff_round_none_without_settings():
    assert (
        playoffs.playoff_round(
            week=21,
            reg_season_count=None,
            playoff_team_count=6,
            playoff_matchup_period_length=1,
        )
        is None
    )


def test_playoff_round_three_round_bracket_labels():
    # reg_season_count=19, 6-team bracket -> 3 rounds: 20=QF, 21=SF, 22=Championship.
    settings = dict(reg_season_count=19, playoff_team_count=6, playoff_matchup_period_length=1)

    quarterfinal = playoffs.playoff_round(week=20, **settings)
    semifinal = playoffs.playoff_round(week=21, **settings)
    championship = playoffs.playoff_round(week=22, **settings)

    assert quarterfinal["round_label"] == "Quarterfinals"
    assert quarterfinal["round_index"] == 1
    assert quarterfinal["total_rounds"] == 3
    assert quarterfinal["is_championship"] is False
    assert quarterfinal["next_round_week"] == 21

    assert semifinal["round_label"] == "Semifinals"
    assert semifinal["round_index"] == 2
    assert semifinal["is_championship"] is False
    assert semifinal["next_round_week"] == 22

    assert championship["round_label"] == "Championship"
    assert championship["round_index"] == 3
    assert championship["is_championship"] is True


def test_playoff_round_two_round_bracket_labels():
    # 4-team bracket -> 2 rounds: semifinal then championship (no quarterfinal).
    settings = dict(reg_season_count=19, playoff_team_count=4, playoff_matchup_period_length=1)

    semifinal = playoffs.playoff_round(week=20, **settings)
    championship = playoffs.playoff_round(week=21, **settings)

    assert semifinal["round_label"] == "Semifinals"
    assert championship["round_label"] == "Championship"


def test_playoff_round_respects_multi_week_rounds():
    # A 2-week-per-round league: weeks 20-21 are round 1, 22-23 round 2.
    settings = dict(reg_season_count=19, playoff_team_count=4, playoff_matchup_period_length=2)

    week20 = playoffs.playoff_round(week=20, **settings)
    week21 = playoffs.playoff_round(week=21, **settings)
    week22 = playoffs.playoff_round(week=22, **settings)

    assert week20["round_index"] == week21["round_index"] == 1
    assert week22["round_index"] == 2
    assert week20["next_round_week"] == 22


def test_playoff_round_none_past_the_bracket():
    # A placement/consolation week after the bracket has finished.
    settings = dict(reg_season_count=19, playoff_team_count=4, playoff_matchup_period_length=1)
    assert playoffs.playoff_round(week=22, **settings) is None


# --- playoffs.playoff_advancement -------------------------------------------

def test_playoff_advancement_skips_ties():
    matchups = [
        {"home_team": "Alpha", "away_team": "Beta", "winner": "Alpha"},
        {"home_team": "Gamma", "away_team": "Delta", "winner": "Tie"},
    ]
    advancing, eliminated = playoffs.playoff_advancement(matchups)
    assert advancing == ["Alpha"]
    assert eliminated == ["Beta"]


def test_playoff_advancement_handles_away_winner():
    matchups = [{"home_team": "Alpha", "away_team": "Beta", "winner": "Beta"}]
    advancing, eliminated = playoffs.playoff_advancement(matchups)
    assert advancing == ["Beta"]
    assert eliminated == ["Alpha"]


# --- playoffs.next_round_matchups -------------------------------------------

def test_next_round_matchups_when_bracket_is_resolved():
    schedule = [
        {"Week": 22, "Team": "Alpha", "Opponent": "Gamma"},
        {"Week": 22, "Team": "Gamma", "Opponent": "Alpha"},
        {"Week": 21, "Team": "Alpha", "Opponent": "Beta"},  # different week, ignored
    ]
    matchups = playoffs.next_round_matchups(
        week=21,
        next_round_week=22,
        advancing_teams=["Alpha", "Gamma"],
        schedule_loader=lambda: schedule,
    )
    assert len(matchups) == 1
    assert {matchups[0]["home_team"], matchups[0]["away_team"]} == {"Alpha", "Gamma"}
    assert matchups[0]["evidence_id"]


def test_next_round_matchups_empty_when_not_resolved():
    # Only Alpha shows up next week -- the bracket clearly isn't finalized yet.
    schedule = [{"Week": 22, "Team": "Alpha", "Opponent": "TBD"}]
    matchups = playoffs.next_round_matchups(
        week=21,
        next_round_week=22,
        advancing_teams=["Alpha", "Gamma"],
        schedule_loader=lambda: schedule,
    )
    assert matchups == []


def test_next_round_matchups_empty_when_schedule_loader_fails():
    def _raise():
        raise RuntimeError("ESPN unavailable")

    matchups = playoffs.next_round_matchups(
        week=21,
        next_round_week=22,
        advancing_teams=["Alpha"],
        schedule_loader=_raise,
    )
    assert matchups == []


def test_next_round_matchups_empty_without_advancing_teams():
    matchups = playoffs.next_round_matchups(
        week=21,
        next_round_week=22,
        advancing_teams=[],
        schedule_loader=lambda: [],
    )
    assert matchups == []


# --- assemble._build_playoff_context ----------------------------------------

def test_assemble_builds_playoff_context_for_a_playoff_week(monkeypatch):
    monkeypatch.setattr(
        assemble.league_api,
        "league_settings",
        lambda: {
            "reg_season_count": 19,
            "playoff_team_count": 6,
            "playoff_matchup_period_length": 1,
        },
    )
    monkeypatch.setattr(
        assemble.league_api,
        "my_league_schedule",
        lambda: [
            {"Week": 22, "Team": "Fantastic5", "Opponent": "TTW"},
            {"Week": 22, "Team": "TTW", "Opponent": "Fantastic5"},
        ],
    )
    matchups = [
        {
            "matchup_id": "week-21:ttw-vs-optimize",
            "home_team": "TTW",
            "away_team": "Optimize",
            "winner": "TTW",
        },
        {
            "matchup_id": "week-21:fantastic5-vs-brighton",
            "home_team": "Fantastic5",
            "away_team": "Brighton",
            "winner": "Fantastic5",
        },
        {
            # both teams missed the 6-team playoffs (seeds 7 & 8) -> consolation
            "matchup_id": "week-21:cellar-vs-basement",
            "home_team": "Cellar",
            "away_team": "Basement",
            "winner": "Cellar",
        },
    ]
    # ESPN playoffSeed lives in the standings `standing` field.
    standings = [
        {"team_name": "TTW", "standing": 1},
        {"team_name": "Fantastic5", "standing": 2},
        {"team_name": "Optimize", "standing": 3},
        {"team_name": "Brighton", "standing": 4},
        {"team_name": "Cellar", "standing": 7},
        {"team_name": "Basement", "standing": 8},
    ]

    context = assemble._build_playoff_context(21, matchups, standings, [])

    assert context is not None
    assert context.round_label == "Semifinals"
    # Seeds 1-6 made the real playoffs; 7-8 are consolation.
    assert context.championship_teams == ["TTW", "Fantastic5", "Optimize", "Brighton"]
    assert context.consolation_teams == ["Cellar", "Basement"]
    # Each matchup is tagged with its bracket.
    by_id = {m["matchup_id"]: m["bracket"] for m in matchups}
    assert by_id["week-21:ttw-vs-optimize"] == "championship"
    assert by_id["week-21:cellar-vs-basement"] == "consolation"


def test_assemble_playoff_context_none_for_regular_season_week(monkeypatch):
    monkeypatch.setattr(
        assemble.league_api,
        "league_settings",
        lambda: {
            "reg_season_count": 19,
            "playoff_team_count": 6,
            "playoff_matchup_period_length": 1,
        },
    )
    assert assemble._build_playoff_context(5, [], [], []) is None


def test_assemble_playoff_context_none_and_warns_when_settings_fail(monkeypatch):
    def _raise():
        raise RuntimeError("ESPN unavailable")

    monkeypatch.setattr(assemble.league_api, "league_settings", _raise)
    warnings: list[str] = []

    assert assemble._build_playoff_context(21, [], [], warnings) is None
    assert any("League settings unavailable" in w for w in warnings)



# --- generate_structured_recap + share text: new voice-first schema ----------

def _playoff_snapshot() -> WeeklyFactSnapshot:
    matchup_id = "week-21:alpha-vs-beta"
    return WeeklyFactSnapshot(
        league={"id": "league-1", "slug": "test", "name": "Test"},
        season=2026,
        week=21,
        week_dates={"start": "2026-03-16", "end": "2026-03-22"},
        matchups=[
            {
                "matchup_id": matchup_id,
                "evidence_id": matchup_id,
                "home_team": "Alpha",
                "away_team": "Beta",
                "home_category_wins": 6,
                "away_category_wins": 3,
                "ties": 0,
                "winner": "Alpha",
                "categories": [],
            }
        ],
        standings=[],
        power_rankings=[],
        transactions=[],
        season_stats=[],
        award_candidates=[],
        data_quality=DataQualityReport(ready=True, checks={}),
        playoff_context=PlayoffContext(
            round_label="Semifinals",
            round_index=2,
            total_rounds=3,
            is_championship=False,
            advancing_teams=["Alpha"],
            eliminated_teams=["Beta"],
        ),
    )


def _new_payload(matchup_id: str) -> dict:
    return {
        "headline": "Separation Week.",
        "intro": "The bracket tightened.",
        "matchup_takeaways": [
            {
                "matchup_id": matchup_id,
                "woj": "Alpha controlled the matchup.",
                "barkley": "Beta never had a chance.",
                "stephen_a": "Alpha is BUILT for this!",
                "insight": "Alpha took the volume categories and never let it flip.",
            }
        ],
        "award_explanations": [],
    }


def test_generate_playoff_week_needs_no_special_fields(monkeypatch):
    """Playoff weeks now weave stakes into the prose -- the new schema has no
    playoff-specific fields, so a plain valid payload generates fine."""
    snapshot = _playoff_snapshot()
    matchup_id = snapshot.matchups[0]["matchup_id"]
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate,
        "_complete_structured",
        lambda *a, **k: RecapGeneratedContent(**_new_payload(matchup_id)).model_dump_json(),
    )

    result = generate.generate_structured_recap(snapshot)
    assert result.headline == "Separation Week."
    assert result.matchup_takeaways[0].stephen_a == "Alpha is BUILT for this!"


def test_share_text_assembles_header_voices_and_link():
    snapshot = _playoff_snapshot()
    matchup_id = snapshot.matchups[0]["matchup_id"]
    content = RecapGeneratedContent(**_new_payload(matchup_id))

    format_share_text(snapshot, content)

    text = content.share_text
    # Deterministic header (facts) -- both teams named by construction.
    assert "Alpha def. Beta, 6-3" in text
    assert "Woj: Alpha controlled the matchup." in text
    assert "Stephen A: Alpha is BUILT for this!" in text
    assert "Read the published recap:" in text
