"""Playoff-narrative recap feature: round detection, advancement, next-round
pairing, evidence-bound generation validation, and WhatsApp formatting.
"""
from unittest.mock import Mock

import pytest

from backend.commentary import generate
from backend.commentary.schemas import (
    DataQualityReport,
    PlayoffContext,
    PlayoffMatchupRecap,
    PlayoffOutlook,
    PlayoffStoryline,
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
    ]

    context = assemble._build_playoff_context(21, matchups, [])

    assert context is not None
    assert context.round_label == "Semifinals"
    assert set(context.advancing_teams) == {"TTW", "Fantastic5"}
    assert set(context.eliminated_teams) == {"Optimize", "Brighton"}
    assert len(context.next_round_matchups) == 1


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
    assert assemble._build_playoff_context(5, [], []) is None


def test_assemble_playoff_context_none_and_warns_when_settings_fail(monkeypatch):
    def _raise():
        raise RuntimeError("ESPN unavailable")

    monkeypatch.setattr(assemble.league_api, "league_settings", _raise)
    warnings: list[str] = []

    assert assemble._build_playoff_context(21, [], warnings) is None
    assert any("League settings unavailable" in w for w in warnings)


# --- generate_structured_recap: playoff field validation --------------------

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
            next_round_matchups=[],
        ),
    )


def _base_content_kwargs(matchup_id: str) -> dict:
    return dict(
        headline="Alpha survives",
        dek="A grounded recap.",
        lead_story=["Alpha won six categories."],
        matchup_takeaways=[
            {"matchup_id": matchup_id, "text": "Alpha controlled it.", "evidence_ids": [matchup_id]}
        ],
        ranking_explanations=[],
        award_explanations=[],
        # Free prose, but the completeness backstop requires every matchup
        # team to be named in both fields.
        whatsapp_summary="Alpha survived Beta in the semifinals.",
        whatsapp_full="Alpha survived Beta in the semifinals, in full detail.",
    )


def test_generate_requires_playoff_matchup_recap_for_every_matchup(monkeypatch):
    snapshot = _playoff_snapshot()
    matchup_id = snapshot.matchups[0]["matchup_id"]
    payload = _base_content_kwargs(matchup_id)
    payload.update(
        playoff_matchup_recaps=[],  # missing -- should fail
        playoff_outlook=[{"team": "Alpha", "text": "Peaking.", "evidence_ids": [matchup_id]}],
        playoff_storylines=[{"title": "Survival", "text": "Barely.", "evidence_ids": [matchup_id]}],
        playoff_final_line="Onward.",
    )
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate, "_complete_structured", lambda *a, **k: RecapGeneratedContent(**payload).model_dump_json()
    )

    with pytest.raises(ValueError, match="playoff_matchup_recap"):
        generate.generate_structured_recap(snapshot)


def test_generate_requires_playoff_outlook_for_every_advancing_team(monkeypatch):
    snapshot = _playoff_snapshot()
    matchup_id = snapshot.matchups[0]["matchup_id"]
    payload = _base_content_kwargs(matchup_id)
    payload.update(
        playoff_matchup_recaps=[
            {
                "matchup_id": matchup_id,
                "result_summary": "Alpha def. Beta 6-3",
                "text": "Alpha controlled it from the start.",
                "evidence_ids": [matchup_id],
            }
        ],
        playoff_outlook=[],  # missing Alpha -- should fail
        playoff_storylines=[{"title": "Survival", "text": "Barely.", "evidence_ids": [matchup_id]}],
        playoff_final_line="Onward.",
    )
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate, "_complete_structured", lambda *a, **k: RecapGeneratedContent(**payload).model_dump_json()
    )

    with pytest.raises(ValueError, match="playoff_outlook"):
        generate.generate_structured_recap(snapshot)


def test_generate_requires_at_least_one_storyline(monkeypatch):
    snapshot = _playoff_snapshot()
    matchup_id = snapshot.matchups[0]["matchup_id"]
    payload = _base_content_kwargs(matchup_id)
    payload.update(
        playoff_matchup_recaps=[
            {
                "matchup_id": matchup_id,
                "result_summary": "Alpha def. Beta 6-3",
                "text": "Alpha controlled it from the start.",
                "evidence_ids": [matchup_id],
            }
        ],
        playoff_outlook=[{"team": "Alpha", "text": "Peaking.", "evidence_ids": [matchup_id]}],
        playoff_storylines=[],
        playoff_final_line="Onward.",
    )
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate, "_complete_structured", lambda *a, **k: RecapGeneratedContent(**payload).model_dump_json()
    )

    with pytest.raises(ValueError, match="playoff_storyline"):
        generate.generate_structured_recap(snapshot)


def test_generate_accepts_a_complete_playoff_payload(monkeypatch):
    snapshot = _playoff_snapshot()
    matchup_id = snapshot.matchups[0]["matchup_id"]
    payload = _base_content_kwargs(matchup_id)
    payload.update(
        playoff_matchup_recaps=[
            {
                "matchup_id": matchup_id,
                "result_summary": "Alpha def. Beta 6-3",
                "text": "Alpha controlled it from the start.",
                "evidence_ids": [matchup_id],
            }
        ],
        playoff_outlook=[{"team": "Alpha", "text": "Peaking.", "evidence_ids": [matchup_id]}],
        playoff_storylines=[{"title": "Survival", "text": "Barely.", "evidence_ids": [matchup_id]}],
        playoff_final_line="Onward.",
    )
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate, "_complete_structured", lambda *a, **k: RecapGeneratedContent(**payload).model_dump_json()
    )

    result = generate.generate_structured_recap(snapshot)

    assert result.playoff_final_line == "Onward."
    assert result.playoff_outlook[0].team == "Alpha"


def test_generate_regular_season_week_ignores_playoff_fields(monkeypatch):
    matchup_id = "week-1:alpha-vs-beta"
    snapshot = WeeklyFactSnapshot(
        league={"id": "league-1", "slug": "test", "name": "Test"},
        season=2026,
        week=1,
        week_dates={"start": "2025-10-20", "end": "2025-10-26"},
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
    )
    payload = _base_content_kwargs(matchup_id)
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate, "_complete_structured", lambda *a, **k: RecapGeneratedContent(**payload).model_dump_json()
    )

    result = generate.generate_structured_recap(snapshot)

    assert result.playoff_matchup_recaps == []
    assert result.playoff_final_line is None


# --- sharing.format_share_text: playoff weeks -------------------------------
# The playoff framing (round label, who advanced, storylines, final line) is
# the model's job now, written directly into the WhatsApp prose per the
# prompt; format_share_text no longer rebuilds labeled bullet sections.

def test_share_text_passes_playoff_prose_through_untouched():
    snapshot = _playoff_snapshot()
    matchup_id = snapshot.matchups[0]["matchup_id"]
    prose = (
        "Semifinals are done: Alpha adapted and survived Beta 6-3. "
        "The best two teams remain."
    )
    content = RecapGeneratedContent(
        headline="Alpha survives",
        dek="A grounded recap.",
        lead_story=["Alpha won."],
        matchup_takeaways=[
            {"matchup_id": matchup_id, "text": "Alpha controlled it.", "evidence_ids": [matchup_id]}
        ],
        ranking_explanations=[],
        award_explanations=[],
        whatsapp_summary=prose,
        whatsapp_full=prose + " In full.",
        playoff_matchup_recaps=[
            PlayoffMatchupRecap(
                matchup_id=matchup_id,
                result_summary="Alpha def. Beta 6-3",
                text="Alpha adapted and survived.",
                evidence_ids=[matchup_id],
            )
        ],
        playoff_outlook=[
            PlayoffOutlook(team="Alpha", text="Battle-tested.", evidence_ids=[matchup_id])
        ],
        playoff_storylines=[
            PlayoffStoryline(title="Survival", text="Barely made it.", evidence_ids=[matchup_id])
        ],
        playoff_final_line="The best two teams remain.",
    )

    result = format_share_text(snapshot, content)

    assert result.whatsapp_summary.startswith(prose)
    assert result.whatsapp_full.startswith(prose + " In full.")
    # Only the public link is appended; no rebuilt bullet sections.
    assert "Read the published recap:" in result.whatsapp_summary
    assert "🏀 *" not in result.whatsapp_summary
    assert "What This Sets Up" not in result.whatsapp_summary


def test_generate_playoff_week_still_enforces_whatsapp_completeness(monkeypatch):
    import json as _json

    snapshot = _playoff_snapshot()
    matchup_id = snapshot.matchups[0]["matchup_id"]
    payload = _base_content_kwargs(matchup_id)
    payload.update(
        playoff_matchup_recaps=[
            {
                "matchup_id": matchup_id,
                "result_summary": "Alpha def. Beta 6-3",
                "text": "Alpha adapted and survived.",
                "evidence_ids": [matchup_id],
            }
        ],
        playoff_outlook=[{"team": "Alpha", "text": "Peaking.", "evidence_ids": [matchup_id]}],
        playoff_storylines=[{"title": "Survival", "text": "Barely.", "evidence_ids": [matchup_id]}],
        playoff_final_line="Onward.",
        whatsapp_summary="Alpha had a huge week.",  # Beta never named
        whatsapp_full="Alpha survived Beta, in full.",
    )
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate, "_complete_structured", lambda *a, **k: _json.dumps(payload)
    )

    with pytest.raises(ValueError, match="whatsapp_summary"):
        generate.generate_structured_recap(snapshot)
