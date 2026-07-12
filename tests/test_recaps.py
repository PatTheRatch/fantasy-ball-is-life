import json
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from backend.commentary import generate
from backend.commentary.schemas import (
    DataQualityReport,
    RecapGeneratedContent,
    WeeklyFactSnapshot,
)
from backend.recaps import auth, service
from backend.recaps.assemble import STAT_ORDER, canonical_matchups
from backend.recaps.awards import select_awards
from backend.recaps.sharing import format_share_text


def _snapshot(*, ready: bool = True) -> WeeklyFactSnapshot:
    matchup_id = "week-1:alpha-vs-beta"
    return WeeklyFactSnapshot(
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
        standings=[
            {
                "team_name": "Alpha",
                "standing": 2,
                "evidence_id": "standing:alpha",
            },
            {
                "team_name": "Beta",
                "standing": 1,
                "evidence_id": "standing:beta",
            },
        ],
        power_rankings=[],
        transactions=[],
        season_stats=[],
        award_candidates=[],
        data_quality=DataQualityReport(
            ready=ready,
            warnings=[] if ready else ["Missing transactions"],
            checks={"transactions_available": ready},
        ),
    )


def test_canonical_matchups_treats_lower_turnovers_as_winner():
    rows = []
    for stat in STAT_ORDER:
        rows.append(
            {
                "home_team": "Alpha",
                "away_team": "Beta",
                "stat": stat,
                "current_home_score": 5 if stat == "TO" else 10,
                "current_away_score": 8 if stat == "TO" else 9,
            }
        )

    matchup = canonical_matchups(rows, 1)[0]

    assert matchup["home_category_wins"] == 9
    turnover = next(
        row for row in matchup["categories"] if row["stat"] == "TO"
    )
    assert turnover["winner"] == "home"


def test_awards_use_deterministic_matchup_and_standing_facts():
    awards = select_awards(_snapshot())
    by_id = {award["award_id"]: award for award in awards}

    assert by_id["team-of-the-week"]["winner"] == "Alpha"
    assert by_id["biggest-upset"]["winner"] == "Alpha"
    assert by_id["biggest-upset"]["facts"]["rank_gap"] == 1


def test_structured_generation_rejects_unknown_evidence(monkeypatch):
    snapshot = _snapshot()
    snapshot.award_candidates = select_awards(snapshot)
    payload = {
        "headline": "Alpha owns the week",
        "dek": "A grounded recap.",
        "lead_story": ["Alpha won 6-3."],
        "matchup_takeaways": [
            {
                "matchup_id": "week-1:alpha-vs-beta",
                "text": "Alpha took six categories.",
                "evidence_ids": ["made-up:evidence"],
            }
        ],
        "ranking_explanations": [],
        "award_explanations": [
            {
                "award_id": award["award_id"],
                "text": f"{award['winner']} earned it.",
                "evidence_ids": award["evidence_ids"],
            }
            for award in snapshot.award_candidates
        ],
        "whatsapp_summary": "Summary",
        "whatsapp_full": "Full recap",
    }
    monkeypatch.setattr(generate, "_require_api_key", lambda: None)
    monkeypatch.setattr(generate, "_complete", lambda *args, **kwargs: json.dumps(payload))

    with pytest.raises(ValueError, match="unknown evidence"):
        generate.generate_structured_recap(snapshot)


def test_incomplete_data_requires_generate_anyway(monkeypatch):
    snapshot = _snapshot(ready=False)
    store = Mock()
    monkeypatch.setattr(
        service,
        "require_admin",
        lambda *_args, **_kwargs: {
            "id": "league-1",
            "slug": "test",
            "name": "Test",
        },
    )
    monkeypatch.setattr(service, "assemble_weekly_snapshot", lambda **_kwargs: snapshot)
    monkeypatch.setattr(service, "select_awards", lambda _snapshot: [])

    with pytest.raises(HTTPException) as raised:
        service.generate_draft(
            store=store,
            slug="test",
            user_id="user-1",
            season=2026,
            week=1,
            week_start="2025-10-20",
            week_end="2025-10-26",
            generate_anyway=False,
        )

    assert raised.value.status_code == 409
    store.insert_snapshot.assert_not_called()


def test_supabase_auth_rejects_missing_bearer_before_network(monkeypatch):
    request = Mock()
    monkeypatch.setattr(auth.requests, "get", request)

    with pytest.raises(HTTPException) as raised:
        auth.require_supabase_user(None)

    assert raised.value.status_code == 401
    request.assert_not_called()


def test_generate_endpoint_rejects_anonymous_before_store_or_anthropic():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    response = TestClient(app).post(
        "/leagues/patriot-games/recaps/2026/1/generate",
        json={
            "week_start": "2025-10-20",
            "week_end": "2025-10-26",
            "generate_anyway": False,
        },
    )

    assert response.status_code == 401


def test_copy_summary_contains_every_matchup_and_public_link(monkeypatch):
    snapshot = _snapshot()
    content = RecapGeneratedContent(
        headline="Alpha owns the week",
        dek="A grounded recap.",
        lead_story=["Alpha won six categories."],
        matchup_takeaways=[
            {
                "matchup_id": "week-1:alpha-vs-beta",
                "text": "Alpha controlled the matchup.",
                "evidence_ids": ["week-1:alpha-vs-beta"],
            }
        ],
        ranking_explanations=[],
        award_explanations=[],
        whatsapp_summary="model draft",
        whatsapp_full="model draft",
    )
    monkeypatch.setattr(
        "backend.recaps.sharing.config.PUBLIC_APP_URL", "https://example.com"
    )

    result = format_share_text(snapshot, content)

    assert "Alpha 6–3 Beta" in result.whatsapp_summary
    assert "https://example.com/recap?season=2026&week=1" in result.whatsapp_summary
