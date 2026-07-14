import json
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from backend.commentary import generate, prompts
from backend.commentary.schemas import (
    DataQualityReport,
    RecapGeneratedContent,
    WeeklyFactSnapshot,
)
from backend.recaps import auth, service
from backend.recaps.assemble import STAT_ORDER, canonical_matchups
from backend.recaps.awards import select_awards
from backend.recaps.sharing import format_share_text
from backend.recaps.store import RecapStore, RecapStoreError


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


def _four_four_tie_rows(espn_winner):
    # 4 categories to home, 4 to away, 1 tied -- a real "4-4, tiebreak" week.
    rows = []
    for index, stat in enumerate(STAT_ORDER):
        if stat == "TO":
            home_value = away_value = 50  # the tied category
        elif index < 4:
            home_value, away_value = 10, 5  # home wins
        else:
            home_value, away_value = 5, 10  # away wins
        rows.append(
            {
                "home_team": "Fantastic5",
                "away_team": "Brighton",
                "stat": stat,
                "current_home_score": home_value,
                "current_away_score": away_value,
                "espn_winner": espn_winner,
            }
        )
    return rows


def test_canonical_matchups_uses_espn_winner_to_break_a_tie():
    matchup = canonical_matchups(_four_four_tie_rows("HOME"), 21)[0]

    assert matchup["home_category_wins"] == matchup["away_category_wins"] == 4
    assert matchup["winner"] == "Fantastic5"
    assert matchup["tiebreak_resolved"] is True


def test_canonical_matchups_stays_tie_when_espn_winner_undecided():
    matchup = canonical_matchups(_four_four_tie_rows("UNDECIDED"), 21)[0]

    assert matchup["winner"] == "Tie"
    assert matchup["tiebreak_resolved"] is False


def test_canonical_matchups_stays_tie_when_espn_winner_missing():
    matchup = canonical_matchups(_four_four_tie_rows(None), 21)[0]

    assert matchup["winner"] == "Tie"
    assert matchup["tiebreak_resolved"] is False


def test_canonical_matchups_ignores_espn_winner_when_tally_is_decisive():
    rows = []
    for stat in STAT_ORDER:
        rows.append(
            {
                "home_team": "Alpha",
                "away_team": "Beta",
                "stat": stat,
                "current_home_score": 10,
                "current_away_score": 5,
                # Deliberately contradicts the tally -- should be ignored
                # since the tally itself isn't tied.
                "espn_winner": "AWAY",
            }
        )

    matchup = canonical_matchups(rows, 1)[0]

    assert matchup["winner"] == "Alpha"
    assert matchup["tiebreak_resolved"] is False


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
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate,
        "_complete_structured",
        lambda *args, **kwargs: json.dumps(payload),
    )

    with pytest.raises(ValueError, match="unknown evidence"):
        generate.generate_structured_recap(snapshot)


def _valid_structured_payload(snapshot):
    return {
        "headline": "Alpha owns the week",
        "dek": "A grounded recap.",
        "lead_story": ["Alpha won six categories against Beta."],
        "matchup_takeaways": [
            {
                "matchup_id": "week-1:alpha-vs-beta",
                "text": "Alpha took six categories.",
                "evidence_ids": ["week-1:alpha-vs-beta"],
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
        "whatsapp_summary": "Alpha ran through Beta this week, and Alpha takes home the hardware too.",
        "whatsapp_full": "Alpha ran through Beta this week, in full detail. Alpha also takes home the hardware.",
    }


def test_generate_rejects_whatsapp_missing_a_team_mention(monkeypatch):
    snapshot = _snapshot()
    snapshot.award_candidates = select_awards(snapshot)
    payload = _valid_structured_payload(snapshot)
    payload["whatsapp_summary"] = "Alpha had a huge week."  # Beta never named
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate, "_complete_structured", lambda *args, **kwargs: json.dumps(payload)
    )

    with pytest.raises(ValueError, match="whatsapp_summary"):
        generate.generate_structured_recap(snapshot)


def test_generate_accepts_whatsapp_mentioning_every_team_and_award_winner(monkeypatch):
    snapshot = _snapshot()
    snapshot.award_candidates = select_awards(snapshot)
    payload = _valid_structured_payload(snapshot)
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate, "_complete_structured", lambda *args, **kwargs: json.dumps(payload)
    )

    result = generate.generate_structured_recap(snapshot)

    assert "Alpha" in result.whatsapp_summary
    assert "Beta" in result.whatsapp_summary


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


def test_share_text_appends_public_link_without_altering_model_narrative(monkeypatch):
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
        whatsapp_summary="Alpha survived Beta in a week nobody saw coming.",
        whatsapp_full="Alpha survived Beta in a week nobody saw coming, in full.",
    )
    monkeypatch.setattr(
        "backend.recaps.sharing.config.PUBLIC_APP_URL", "https://example.com"
    )

    result = format_share_text(snapshot, content)

    # The model's own narrative passes through untouched -- format_share_text
    # only appends the link it's the only thing the model can't know.
    assert result.whatsapp_summary.startswith(
        "Alpha survived Beta in a week nobody saw coming."
    )
    assert result.whatsapp_full.startswith(
        "Alpha survived Beta in a week nobody saw coming, in full."
    )
    assert "https://example.com/recap?season=2026&week=1" in result.whatsapp_summary
    assert "https://example.com/recap?season=2026&week=1" in result.whatsapp_full


def test_deepseek_structured_completion_uses_json_mode(monkeypatch):
    response = Mock()
    response.ok = True
    response.json.return_value = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": '{"headline":"Test"}'},
            }
        ]
    }
    post = Mock(return_value=response)
    monkeypatch.setattr(generate.requests, "post", post)
    monkeypatch.setattr(generate.config, "RECAP_LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(generate.config, "DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(generate.config, "DEEPSEEK_MODEL", "deepseek-v4-flash")

    result = generate._complete_structured(
        "Return json.", "Use this schema.", max_tokens=1000
    )

    assert result == '{"headline":"Test"}'
    request = post.call_args.kwargs
    assert request["json"]["model"] == "deepseek-v4-flash"
    assert request["json"]["response_format"] == {"type": "json_object"}


def test_store_rollback_validates_scope_and_returns_draft(monkeypatch):
    store = RecapStore(url="https://example.supabase.co", service_role_key="key")
    monkeypatch.setattr(
        store,
        "get_edition_by_id",
        Mock(
            return_value={
                "id": "edition-1",
                "league_id": "league-1",
                "season": 2026,
                "week": 1,
                "status": "published",
            }
        ),
    )
    request = Mock(
        return_value=[
            {
                "id": "edition-1",
                "status": "draft",
                "published_at": None,
            }
        ]
    )
    monkeypatch.setattr(store, "_request", request)

    result = store.rollback(
        "edition-1", league_id="league-1", season=2026, week=1
    )

    assert result["status"] == "draft"
    request.assert_called_once_with(
        "PATCH",
        "recap_editions",
        params={
            "id": "eq.edition-1",
            "league_id": "eq.league-1",
            "season": "eq.2026",
            "week": "eq.1",
        },
        json={"status": "draft", "published_at": None},
        prefer="return=representation",
    )


def test_store_rollback_rejects_wrong_league_before_patch(monkeypatch):
    store = RecapStore(url="https://example.supabase.co", service_role_key="key")
    monkeypatch.setattr(
        store,
        "get_edition_by_id",
        Mock(
            return_value={
                "id": "edition-1",
                "league_id": "another-league",
                "season": 2026,
                "week": 1,
            }
        ),
    )
    request = Mock()
    monkeypatch.setattr(store, "_request", request)

    with pytest.raises(RecapStoreError, match="not found"):
        store.rollback(
            "edition-1", league_id="league-1", season=2026, week=1
        )

    request.assert_not_called()


def test_service_rollback_validates_edition_and_calls_store(monkeypatch):
    store = Mock()
    store.get_edition_by_id.return_value = {
        "id": "edition-1",
        "league_id": "league-1",
        "season": 2026,
        "week": 1,
    }
    store.rollback.return_value = {"id": "edition-1", "status": "draft"}
    monkeypatch.setattr(
        service,
        "require_admin",
        lambda *_args, **_kwargs: {"id": "league-1"},
    )

    result = service.rollback_edition(
        store=store,
        slug="test",
        user_id="user-1",
        season=2026,
        week=1,
        edition_id="edition-1",
    )

    assert result["status"] == "draft"
    store.rollback.assert_called_once_with(
        "edition-1", league_id="league-1", season=2026, week=1
    )


def test_rollback_router_uses_rollback_service(monkeypatch):
    from backend.api.routers import recaps

    rollback = Mock(return_value={"id": "edition-1", "status": "draft"})
    monkeypatch.setattr(recaps.service, "rollback_edition", rollback)

    result = recaps.rollback_recap(
        slug="test",
        season=2026,
        week=1,
        body=recaps.EditionActionBody(edition_id="edition-1"),
        user={"id": "user-1"},
        store=Mock(),
    )

    assert result["status"] == "draft"
    rollback.assert_called_once()


def test_structured_recap_prompt_includes_league_voice_notes_when_set():
    snapshot_payload = {
        "league": {"id": "league-1", "slug": "test", "name": "Test", "recap_voice": "Mention the Alpha/Beta rivalry."},
    }

    system_prompt, _ = prompts.build_structured_recap_prompts(snapshot_payload)

    assert "LEAGUE-SPECIFIC VOICE NOTES" in system_prompt
    assert "Mention the Alpha/Beta rivalry." in system_prompt


def test_structured_recap_prompt_omits_voice_section_when_unset():
    snapshot_payload = {"league": {"id": "league-1", "slug": "test", "name": "Test"}}

    system_prompt, _ = prompts.build_structured_recap_prompts(snapshot_payload)

    assert "LEAGUE-SPECIFIC VOICE NOTES" not in system_prompt


def test_get_edition_by_id_normalizes_stored_snapshot(monkeypatch):
    store = Mock()
    store.get_edition_with_content_by_id.return_value = {
        "id": "edition-1",
        "league_id": "league-1",
        "season": 2026,
        "week": 21,
        "status": "superseded",
        "structured_content_json": {"headline": "Playoffs"},
        "league_week_snapshots": {
            "schema_version": "recap-facts-v1",
            "matchups_json": [{"matchup_id": "week-21:alpha-vs-beta"}],
            "standings_json": [{"team_name": "Alpha"}],
            "power_rankings_json": [],
            "transactions_json": [],
            "season_stats_json": [],
            "award_candidates_json": [],
            "data_quality_json": {"ready": True},
        },
    }
    monkeypatch.setattr(
        service,
        "require_admin",
        lambda *_args, **_kwargs: {"id": "league-1", "slug": "test", "name": "Test"},
    )

    result = service.get_edition_by_id(
        store=store,
        slug="test",
        user_id="user-1",
        season=2026,
        week=21,
        edition_id="edition-1",
    )

    store.get_edition_with_content_by_id.assert_called_once_with("edition-1")
    assert "league_week_snapshots" not in result
    assert result["snapshot"]["matchups"] == [{"matchup_id": "week-21:alpha-vs-beta"}]
    assert result["snapshot"]["standings"] == [{"team_name": "Alpha"}]
    assert result["snapshot"]["league"]["id"] == "league-1"
    assert result["snapshot"]["season"] == 2026
    assert result["snapshot"]["week"] == 21


def test_get_edition_by_id_404s_on_wrong_week(monkeypatch):
    store = Mock()
    store.get_edition_with_content_by_id.return_value = {
        "id": "edition-1",
        "league_id": "league-1",
        "season": 2026,
        "week": 20,
        "status": "draft",
        "structured_content_json": {},
    }
    monkeypatch.setattr(
        service,
        "require_admin",
        lambda *_args, **_kwargs: {"id": "league-1", "slug": "test", "name": "Test"},
    )

    with pytest.raises(HTTPException) as raised:
        service.get_edition_by_id(
            store=store,
            slug="test",
            user_id="user-1",
            season=2026,
            week=21,
            edition_id="edition-1",
        )

    assert raised.value.status_code == 404


def test_get_edition_by_id_404s_on_missing_edition(monkeypatch):
    store = Mock()
    store.get_edition_with_content_by_id.return_value = None
    monkeypatch.setattr(
        service,
        "require_admin",
        lambda *_args, **_kwargs: {"id": "league-1", "slug": "test", "name": "Test"},
    )

    with pytest.raises(HTTPException) as raised:
        service.get_edition_by_id(
            store=store,
            slug="test",
            user_id="user-1",
            season=2026,
            week=21,
            edition_id="missing",
        )

    assert raised.value.status_code == 404


def test_edition_router_uses_get_edition_by_id_service(monkeypatch):
    from backend.api.routers import recaps

    fetch = Mock(return_value={"id": "edition-1", "status": "superseded"})
    monkeypatch.setattr(recaps.service, "get_edition_by_id", fetch)

    result = recaps.recap_edition(
        slug="test",
        season=2026,
        week=21,
        edition_id="edition-1",
        user={"id": "user-1"},
        store=Mock(),
    )

    assert result["status"] == "superseded"
    fetch.assert_called_once()


def test_store_get_edition_with_content_by_id_selects_snapshot_embed(monkeypatch):
    store = RecapStore(url="https://example.supabase.co", service_role_key="key")
    request = Mock(return_value=[{"id": "edition-1"}])
    monkeypatch.setattr(store, "_request", request)

    result = store.get_edition_with_content_by_id("edition-1")

    assert result == {"id": "edition-1"}
    request.assert_called_once_with(
        "GET",
        "recap_editions",
        params={
            "id": "eq.edition-1",
            "select": store._EDITION_WITH_SNAPSHOT_SELECT,
            "limit": "1",
        },
    )


def test_invalid_structured_recap_uses_provider_neutral_error(monkeypatch):
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate, "_complete_structured", lambda *args, **kwargs: "{}"
    )

    with pytest.raises(ValueError, match="LLM returned an invalid structured recap"):
        generate.generate_structured_recap(_snapshot())


# ── F2-1 archive endpoint ──────────────────────────────────────────

def test_store_list_published_returns_weeks_ordered(monkeypatch):
    """list_published selects published weeks sorted by week.asc."""
    store = RecapStore(url='https://example.supabase.co', service_role_key='key')
    request = Mock(return_value=[
        {'week': 1, 'headline': 'Week One', 'published_at': '2026-01-15T00:00:00Z'},
        {'week': 3, 'headline': 'Week Three', 'published_at': '2026-01-29T00:00:00Z'},
    ])
    monkeypatch.setattr(store, '_request', request)
    result = store.list_published('league-1', 2026)
    assert result == [
        {'week': 1, 'headline': 'Week One', 'published_at': '2026-01-15T00:00:00Z'},
        {'week': 3, 'headline': 'Week Three', 'published_at': '2026-01-29T00:00:00Z'},
    ]
    request.assert_called_once_with(
        'GET', 'recap_editions',
        params={
            'league_id': 'eq.league-1', 'season': 'eq.2026',
            'status': 'eq.published',
            'select': 'week,structured_content_json->headline,published_at',
            'order': 'week.asc',
        },
    )

def test_store_list_published_returns_empty_on_none(monkeypatch):
    store = RecapStore(url='https://example.supabase.co', service_role_key='key')
    monkeypatch.setattr(store, '_request', Mock(return_value=[]))
    assert store.list_published('league-1', 2026) == []

def test_store_list_published_handles_missing_headline(monkeypatch):
    store = RecapStore(url='https://example.supabase.co', service_role_key='key')
    monkeypatch.setattr(store, '_request', Mock(return_value=[
        {'week': 1, 'published_at': '2026-01-15T00:00:00Z'},
    ]))
    result = store.list_published('league-1', 2026)
    assert result == [{'week': 1, 'published_at': '2026-01-15T00:00:00Z'}]

def test_service_get_published_archive_404s_on_non_public_league(monkeypatch):
    store = Mock()
    store.get_league_by_slug.return_value = {'id': 'league-1', 'visibility': 'private'}
    with pytest.raises(HTTPException, match='Published recap not found.'):
        service.get_published_archive(store=store, slug='test', season=2026)

def test_service_get_published_archive_returns_list_on_public(monkeypatch):
    store = Mock()
    store.get_league_by_slug.return_value = {'id': 'league-1', 'visibility': 'public'}
    store.list_published.return_value = [{'week': 1, 'headline': 'Week One'}]
    result = service.get_published_archive(store=store, slug='test', season=2026)
    assert result == [{'week': 1, 'headline': 'Week One'}]
    store.list_published.assert_called_once_with('league-1', 2026)
