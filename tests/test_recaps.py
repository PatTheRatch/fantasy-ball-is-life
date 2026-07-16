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

    # FIX-A: Team of the Week now uses single-week all-play from
    # snapshot.single_week_all_play.  The _snapshot() fixture does not
    # include all-play data, so TotW is absent in fixture tests.
    # When single_week_all_play is populated (live assembly), the award
    # selects the field-wide winner.
    assert by_id["biggest-upset"]["winner"] == "Alpha"
    assert by_id["biggest-upset"]["facts"]["rank_gap"] == 1


def _valid_structured_payload(snapshot):
    return {
        "headline": "Alpha Owns the Week.",
        "intro": "Alpha handled Beta and the standings shifted.",
        "synopsis": [
            "Alpha keeps separating from the field.",
            "Beta is running out of runway.",
        ],
        "matchup_takeaways": [
            {
                "matchup_id": "week-1:alpha-vs-beta",
                "woj": "Alpha controlled the matchup start to finish.",
                "barkley": "Beta got run off the floor.",
                "stephen_a": "Alpha is for REAL!",
                "insight": "Alpha won six categories to three on volume scoring.",
            }
        ],
        "ranking_explanations": [
            {"team": "Alpha", "text": "Still the class of the league."},
            {"team": "Beta", "text": "Slipping fast without a clear category edge."},
        ],
        "award_explanations": [
            {"award_id": award["award_id"], "text": f"{award['winner']} earned it."}
            for award in snapshot.award_candidates
        ],
    }


def test_generate_rejects_missing_matchup_coverage(monkeypatch):
    snapshot = _snapshot()
    snapshot.award_candidates = select_awards(snapshot)
    payload = _valid_structured_payload(snapshot)
    payload["matchup_takeaways"] = []  # coverage miss
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate, "_complete_structured", lambda *args, **kwargs: json.dumps(payload)
    )

    with pytest.raises(ValueError, match="one takeaway per matchup"):
        generate.generate_structured_recap(snapshot)


def test_generate_accepts_valid_three_voice_payload(monkeypatch):
    snapshot = _snapshot()
    snapshot.award_candidates = select_awards(snapshot)
    payload = _valid_structured_payload(snapshot)
    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(
        generate, "_complete_structured", lambda *args, **kwargs: json.dumps(payload)
    )

    result = generate.generate_structured_recap(snapshot)

    assert result.headline == "Alpha Owns the Week."
    takeaway = result.matchup_takeaways[0]
    assert takeaway.woj and takeaway.barkley and takeaway.stephen_a and takeaway.insight


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


# --- generate_draft: power-rankings persistence + reuse ----------------------
# Recap + power rankings generate together in one LLM call (the point of this
# suite), but rankings are persisted per (league, season, week) and reused on
# every later regeneration for that week, so redrafting the narrative doesn't
# re-ask the LLM for rankings text that has no reason to change.

def _generated_payload(matchup_id: str, ranking_team: str = "Alpha") -> dict:
    return {
        "headline": "Headline",
        "intro": "Intro.",
        "synopsis": [],
        "matchup_takeaways": [
            {
                "matchup_id": matchup_id,
                "woj": "w", "barkley": "b", "stephen_a": "s", "insight": "i",
            }
        ],
        "ranking_explanations": [{"team": ranking_team, "text": "grounded take"}],
        "award_explanations": [],
    }


def _mock_generate_draft_deps(monkeypatch, snapshot):
    monkeypatch.setattr(
        service, "require_admin",
        lambda *a, **k: {"id": "league-1", "slug": "test", "name": "Test"},
    )
    monkeypatch.setattr(service, "assemble_weekly_snapshot", lambda **kw: snapshot)
    monkeypatch.setattr(service, "select_awards", lambda s: [])
    monkeypatch.setattr(service, "format_share_text", lambda snap, content: content)


def test_generate_draft_persists_rankings_on_first_generation(monkeypatch):
    snapshot = _snapshot()
    store = Mock()
    store.get_power_rankings.return_value = None  # nothing cached for this week yet
    store.next_version.return_value = 1
    store.insert_snapshot.return_value = {"id": "snap-1"}
    store.insert_edition.return_value = {"id": "ed-1"}
    _mock_generate_draft_deps(monkeypatch, snapshot)

    captured: dict = {}

    def fake_generate(snap, **kwargs):
        captured.update(kwargs)
        return RecapGeneratedContent(**_generated_payload("week-1:alpha-vs-beta"))

    monkeypatch.setattr(service, "generate_structured_recap", fake_generate)

    service.generate_draft(
        store=store, slug="test", user_id="user-1", season=2026, week=1,
        week_start="2025-10-20", week_end="2025-10-26", generate_anyway=False,
    )

    assert captured["skip_ranking_explanations"] is False
    store.insert_power_rankings.assert_called_once()
    inserted = store.insert_power_rankings.call_args[0][0]
    assert inserted["league_id"] == "league-1"
    assert inserted["season"] == 2026
    assert inserted["week"] == 1
    assert inserted["ranking_explanations_json"] == [{"team": "Alpha", "text": "grounded take"}]


def test_generate_draft_reuses_cached_rankings_and_skips_llm_section(monkeypatch):
    snapshot = _snapshot()
    store = Mock()
    store.get_power_rankings.return_value = {
        "ranking_explanations_json": [{"team": "Cached Team", "text": "from storage"}]
    }
    store.next_version.return_value = 2
    store.insert_snapshot.return_value = {"id": "snap-2"}
    store.insert_edition.return_value = {"id": "ed-2"}
    _mock_generate_draft_deps(monkeypatch, snapshot)

    captured: dict = {}

    def fake_generate(snap, **kwargs):
        captured.update(kwargs)
        # Even if the model wrote something here, the cached blurbs must win.
        payload = _generated_payload("week-1:alpha-vs-beta", ranking_team="Fresh Team")
        return RecapGeneratedContent(**payload)

    monkeypatch.setattr(service, "generate_structured_recap", fake_generate)

    edition = service.generate_draft(
        store=store, slug="test", user_id="user-1", season=2026, week=1,
        week_start="2025-10-20", week_end="2025-10-26", generate_anyway=False,
    )

    assert captured["skip_ranking_explanations"] is True
    store.insert_power_rankings.assert_not_called()  # already cached -- don't redo it
    saved = store.insert_edition.call_args[0][0]["structured_content_json"]
    assert saved["ranking_explanations"] == [{"team": "Cached Team", "text": "from storage"}]


def test_generate_draft_survives_power_rankings_insert_race(monkeypatch):
    """A concurrent generate_draft for the same brand-new week can win the
    insert first (unique constraint on league/season/week); this generation
    still succeeded and must not fail the whole draft over a lost cache-write."""
    snapshot = _snapshot()
    store = Mock()
    store.get_power_rankings.return_value = None
    store.next_version.return_value = 1
    store.insert_snapshot.return_value = {"id": "snap-1"}
    store.insert_edition.return_value = {"id": "ed-1"}
    store.insert_power_rankings.side_effect = RecapStoreError("conflict")
    _mock_generate_draft_deps(monkeypatch, snapshot)
    monkeypatch.setattr(
        service, "generate_structured_recap",
        lambda snap, **kw: RecapGeneratedContent(**_generated_payload("week-1:alpha-vs-beta")),
    )

    edition = service.generate_draft(
        store=store, slug="test", user_id="user-1", season=2026, week=1,
        week_start="2025-10-20", week_end="2025-10-26", generate_anyway=False,
    )
    assert edition["id"] == "ed-1"


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


def test_share_text_assembles_facts_voices_and_link(monkeypatch):
    snapshot = _snapshot()
    content = RecapGeneratedContent(
        headline="Alpha Owns the Week.",
        intro="Alpha survived Beta in a week nobody saw coming.",
        matchup_takeaways=[
            {
                "matchup_id": "week-1:alpha-vs-beta",
                "woj": "Alpha controlled the matchup.",
                "barkley": "Beta got bullied.",
                "stephen_a": "Alpha is UNSTOPPABLE!",
                "insight": "Alpha won six categories to three.",
            }
        ],
        award_explanations=[],
    )
    monkeypatch.setattr(
        "backend.recaps.sharing.config.PUBLIC_APP_URL", "https://example.com"
    )

    content.synopsis = ["The field is separating.", "The bottom is falling out."]
    result = format_share_text(snapshot, content)
    text = result.share_text

    # Deterministic header (both teams named by construction) + the voices +link.
    assert text.startswith("Alpha Owns the Week.")
    assert "The field is separating." in text  # synopsis paragraphs included
    assert "Alpha def. Beta, 6-3" in text
    assert "Woj: Alpha controlled the matchup." in text
    assert "Barkley: Beta got bullied." in text
    assert "Stephen A: Alpha is UNSTOPPABLE!" in text
    assert "Insight: Alpha won six categories to three." in text
    assert "https://example.com/recap?season=2026&week=1" in text


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


def test_structured_recap_prompt_includes_ranking_explanations_by_default():
    snapshot_payload = {
        "league": {"id": "league-1", "slug": "test", "name": "Test"},
        "power_rankings": [{"team": "Alpha"}, {"team": "Beta"}],
    }

    _, user_prompt = prompts.build_structured_recap_prompts(snapshot_payload)

    assert '"ranking_explanations"' in user_prompt
    assert "write one for EVERY team in power_rankings" in user_prompt
    assert "['Alpha', 'Beta']" in user_prompt


def test_structured_recap_prompt_skips_ranking_explanations_when_cached():
    snapshot_payload = {
        "league": {"id": "league-1", "slug": "test", "name": "Test"},
        "power_rankings": [{"team": "Alpha"}, {"team": "Beta"}],
    }

    _, user_prompt = prompts.build_structured_recap_prompts(
        snapshot_payload, skip_ranking_explanations=True
    )

    assert '"ranking_explanations"' not in user_prompt
    assert "already generated and are reused as-is" in user_prompt


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


# --- get_public_snapshot: the deterministic /snapshot read path ---------------
# Regression for a NameError (`_not_found` was called but never defined), which
# turned every /snapshot request into a 500 in production.

def test_get_public_snapshot_normalizes_stored_edition():
    store = Mock()
    store.get_league_by_slug.return_value = {
        "id": "league-1", "slug": "test", "visibility": "public"
    }
    store.get_edition.return_value = {
        "season": 2026,
        "week": 10,
        "league_week_snapshots": {
            "matchups_json": [{"matchup_id": "week-10:a-vs-b"}],
            "power_rankings_json": [{"team": "Alpha"}],
        },
    }

    result = service.get_public_snapshot(store=store, slug="test", season=2026, week=10)

    # Normalized to the tabs' shape (matchups/power_rankings, not *_json).
    assert result["snapshot"]["matchups"] == [{"matchup_id": "week-10:a-vs-b"}]
    assert result["snapshot"]["power_rankings"] == [{"team": "Alpha"}]


def test_get_public_snapshot_assembles_when_no_edition(monkeypatch):
    # No stored recap -> the deterministic tabs must still get data (assembled
    # from ESPN), never a 404.
    store = Mock()
    store.get_league_by_slug.return_value = {
        "id": "league-1", "slug": "test", "visibility": "public"
    }
    store.get_edition.return_value = None

    fake = _snapshot()
    monkeypatch.setattr(service, "assemble_weekly_snapshot", lambda **_kwargs: fake)

    result = service.get_public_snapshot(store=store, slug="test", season=2026, week=10)

    assert result["snapshot"]["matchups"][0]["matchup_id"] == "week-1:alpha-vs-beta"


def test_get_public_snapshot_404s_when_league_not_public():
    store = Mock()
    store.get_league_by_slug.return_value = {
        "id": "league-1", "slug": "test", "visibility": "private"
    }

    with pytest.raises(HTTPException) as raised:
        service.get_public_snapshot(store=store, slug="test", season=2026, week=10)
    assert raised.value.status_code == 404


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


# --- malformed-JSON recovery (json_repair) ------------------------------------
# Regression for a prod 502: the LLM emitted almost-valid JSON with an unescaped
# double-quote inside a narrative string ("Expecting ',' delimiter"), and a bare
# json.loads threw away the whole ~60s generation.

def test_parse_json_object_passes_through_valid():
    assert generate._parse_json_object('{"a": 1, "b": [1, 2]}') == {"a": 1, "b": [1, 2]}


def test_parse_json_object_repairs_unescaped_quote():
    bad = '{"headline": "The "Dream Team" rolls", "n": 3}'
    with pytest.raises(json.JSONDecodeError):
        json.loads(bad)  # confirms this is the real prod failure shape
    out = generate._parse_json_object(bad)
    assert out["n"] == 3
    assert "Dream Team" in out["headline"]


def test_generate_retries_with_feedback_then_succeeds(monkeypatch):
    # First LLM response misses the matchup cardinality; after the corrective
    # re-prompt the second response is valid — the recap should succeed on
    # attempt 2 instead of hard-failing (502) on attempt 1.
    snapshot = _snapshot()
    snapshot.award_candidates = select_awards(snapshot)
    good = _valid_structured_payload(snapshot)
    bad = {**good, "matchup_takeaways": []}  # 0 takeaways != the snapshot's matchups

    calls = {"n": 0}

    def fake(system_prompt, user_prompt, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps(bad)
        # The retry must carry the corrective feedback naming the required ids.
        assert "REJECTED" in user_prompt
        return json.dumps(good)

    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(generate, "_complete_structured", fake)

    result = generate.generate_structured_recap(snapshot)
    assert calls["n"] == 2
    assert result.matchup_takeaways


def test_generate_raises_after_exhausting_retries(monkeypatch):
    snapshot = _snapshot()
    snapshot.award_candidates = select_awards(snapshot)
    bad = {**_valid_structured_payload(snapshot), "matchup_takeaways": []}
    calls = {"n": 0}

    def fake(*a, **k):
        calls["n"] += 1
        return json.dumps(bad)

    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(generate, "_complete_structured", fake)

    with pytest.raises(ValueError, match="after 3 attempts"):
        generate.generate_structured_recap(snapshot)
    assert calls["n"] == 3


def test_generate_recovers_from_malformed_llm_json(monkeypatch):
    snapshot = _snapshot()
    snapshot.award_candidates = select_awards(snapshot)
    payload = _valid_structured_payload(snapshot)
    payload["headline"] = "Alpha owns the week"
    # Corrupt exactly like prod: unescaped quotes inside a string value.
    malformed = json.dumps(payload).replace(
        "Alpha owns the week", 'Alpha owns the "big" week'
    )
    with pytest.raises(json.JSONDecodeError):
        json.loads(malformed)  # strict parse must fail, else the test is moot

    monkeypatch.setattr(generate, "_require_recap_api_key", lambda: None)
    monkeypatch.setattr(generate, "_complete_structured", lambda *a, **k: malformed)

    result = generate.generate_structured_recap(snapshot)
    assert "big" in result.headline


# ── Matchup enrichments: GP + Catalyst ────────────────────────────────

_COUNTING_STATS = ["PTS", "REB", "AST", "STL", "BLK", "3PM"]


def _make_scoreboard_row(
    home_team="Alpha",
    away_team="Beta",
    stat="PTS",
    home_score=100,
    away_score=90,
    *,
    home_gp=None,
    away_gp=None,
    home_leader_name=None,
    home_leader_value=None,
    home_team_total=None,
    away_leader_name=None,
    away_leader_value=None,
    away_team_total=None,
    espn_winner=None,
):
    row = {
        "home_team": home_team,
        "away_team": away_team,
        "stat": stat,
        "current_home_score": home_score,
        "current_away_score": away_score,
        "espn_winner": espn_winner,
        "home_games_played": home_gp,
        "away_games_played": away_gp,
    }
    if stat in {"PTS", "REB", "AST", "STL", "BLK", "3PM"}:
        row.update({
            "home_catalyst_leader_name": home_leader_name,
            "home_catalyst_leader_value": home_leader_value,
            "home_catalyst_team_total": home_team_total,
            "away_catalyst_leader_name": away_leader_name,
            "away_catalyst_leader_value": away_leader_value,
            "away_catalyst_team_total": away_team_total,
        })
    else:
        row.update({
            "home_catalyst_leader_name": None,
            "home_catalyst_leader_value": None,
            "home_catalyst_team_total": None,
            "away_catalyst_leader_name": None,
            "away_catalyst_leader_value": None,
            "away_catalyst_team_total": None,
        })
    return row


def _nine_cat_rows(home="Alpha", away="Beta", **overrides):
    """Build a full 9-cat scoreboard for one matchup.  *overrides* accepts
    keyword args like ``home_gp=28``, ``PTS_home_leader_name=\"Jokic\"``,
    ``PTS_home_leader_value=120``, ``PTS_home_team_total=450``."""
    rows = []
    for stat in STAT_ORDER:
        kwargs: dict[str, Any] = {}
        kwargs["home_team"] = home
        kwargs["away_team"] = away
        kwargs["stat"] = stat
        # Default: home wins every cat by a comfortable margin (ratio > 0.10).
        kwargs["home_score"] = overrides.get("home_score", 100)
        kwargs["away_score"] = overrides.get("away_score", 50)
        kwargs["home_gp"] = overrides.get("home_gp")
        kwargs["away_gp"] = overrides.get("away_gp")
        # Pull per-stat leader values from overrides when present.
        for side in ("home", "away"):
            for field in ("leader_name", "leader_value", "team_total"):
                key = f"{stat}_{side}_{field}"
                kwargs[f"{side}_{field}"] = overrides.get(key)
        # Per-stat score overrides (e.g. PTS_home_score=95).
        for side in ("home", "away"):
            key = f"{stat}_{side}_score"
            if key in overrides:
                kwargs[f"{side}_score"] = overrides[key]
        rows.append(_make_scoreboard_row(**kwargs))
    return rows


class TestMatchupGP:
    def test_gp_attached_to_matchup(self):
        rows = _nine_cat_rows(home_gp=32, away_gp=28)
        matchups = canonical_matchups(rows, 1)
        assert len(matchups) == 1
        m = matchups[0]
        assert m["home_games_played"] == 32
        assert m["away_games_played"] == 28

    def test_gp_none_when_absent(self):
        rows = _nine_cat_rows()  # no home_gp/away_gp passed
        matchups = canonical_matchups(rows, 1)
        m = matchups[0]
        assert m["home_games_played"] is None
        assert m["away_games_played"] is None


class TestCategoryCatalyst:
    def test_carried_when_share_above_half(self):
        """Player with >60% share reports shape='carried' with correct share."""
        rows = _nine_cat_rows(
            PTS_home_score=450,
            PTS_away_score=50,
            PTS_home_leader_name="Jokic",
            PTS_home_leader_value=300,
            PTS_home_team_total=450,
            # Away also needs valid totals (won't be used — home wins)
            PTS_away_leader_name="Bench",
            PTS_away_leader_value=1,
            PTS_away_team_total=50,
        )
        matchups = canonical_matchups(rows, 1)
        m = matchups[0]
        pts = next(c for c in m["categories"] if c["stat"] == "PTS")
        cat = pts["catalyst"]
        assert cat["leader_name"] == "Jokic"
        assert cat["leader_value"] == 300.0
        assert cat["team_total"] == 450.0
        assert cat["share"] == pytest.approx(0.6667, abs=1e-4)
        assert cat["shape"] == "carried"

    def test_team_effort_when_share_below_half(self):
        rows = _nine_cat_rows(
            PTS_home_score=450,
            PTS_away_score=50,
            PTS_home_leader_name="Jokic",
            PTS_home_leader_value=100,
            PTS_home_team_total=450,
            PTS_away_leader_name="Bench",
            PTS_away_leader_value=1,
            PTS_away_team_total=50,
        )
        matchups = canonical_matchups(rows, 1)
        m = matchups[0]
        pts = next(c for c in m["categories"] if c["stat"] == "PTS")
        assert pts["catalyst"]["shape"] == "team effort"

    def test_sanity_gate_drops_mismatched_total(self):
        """When player-sum ≠ official value, catalyst is dropped."""
        rows = _nine_cat_rows(
            PTS_home_leader_name="Jokic",
            PTS_home_leader_value=300,
            PTS_home_team_total=999,  # way off the official 100
            PTS_away_leader_name="Bench",
            PTS_away_leader_value=1,
            PTS_away_team_total=50,
        )
        matchups = canonical_matchups(rows, 1)
        m = matchups[0]
        pts = next(c for c in m["categories"] if c["stat"] == "PTS")
        assert "catalyst" not in pts

    def test_bench_players_excluded_via_missing_data(self):
        """bench players would have leader_name=None (no active-slot data)."""
        rows = _nine_cat_rows(
            PTS_home_leader_name=None,  # no active leader
            PTS_home_leader_value=None,
            PTS_home_team_total=None,
            PTS_away_leader_name="Someone",
            PTS_away_leader_value=10,
            PTS_away_team_total=50,
        )
        matchups = canonical_matchups(rows, 1)
        m = matchups[0]
        pts = next(c for c in m["categories"] if c["stat"] == "PTS")
        # Home won PTS (100 > 50) but has no leader data — catalyst skipped.
        assert "catalyst" not in pts

    def test_to_fg_ft_never_produce_catalyst(self):
        rows = _nine_cat_rows()
        matchups = canonical_matchups(rows, 1)
        m = matchups[0]
        for cat in m["categories"]:
            if cat["stat"] in ("TO", "FG%", "FT%"):
                assert "catalyst" not in cat, f"{cat['stat']} should not have catalyst"

    def test_max_two_catalysts_per_matchup(self):
        """Even if many categories qualify, ≤2 are selected."""
        rows = _nine_cat_rows()
        # Make every counting stat very close (margin_ratio → 0).
        for stat in _COUNTING_STATS:
            idx = STAT_ORDER.index(stat)
            rows[idx]["current_home_score"] = 100
            rows[idx]["current_away_score"] = 99
            rows[idx]["home_catalyst_leader_name"] = "Star"
            rows[idx]["home_catalyst_leader_value"] = 40
            rows[idx]["home_catalyst_team_total"] = 100
            rows[idx]["away_catalyst_leader_name"] = "Role"
            rows[idx]["away_catalyst_leader_value"] = 10
            rows[idx]["away_catalyst_team_total"] = 99
        matchups = canonical_matchups(rows, 1)
        m = matchups[0]
        assert len(m["catalysts"]) <= 2
        # Should be the two smallest margin_ratios.
        margins = [c["margin"] for c in m["catalysts"]]
        assert margins == sorted(margins)

    def test_catalyst_only_for_winning_side(self):
        """Away-winning category gets away leader, not home."""
        rows = _nine_cat_rows()
        # Make home lose PTS.
        pts_row = rows[STAT_ORDER.index("PTS")]
        pts_row["current_home_score"] = 50
        pts_row["current_away_score"] = 100
        pts_row["home_catalyst_leader_name"] = "Loser"
        pts_row["home_catalyst_leader_value"] = 25
        pts_row["home_catalyst_team_total"] = 50
        pts_row["away_catalyst_leader_name"] = "Winner"
        pts_row["away_catalyst_leader_value"] = 80
        pts_row["away_catalyst_team_total"] = 100
        matchups = canonical_matchups(rows, 1)
        m = matchups[0]
        pts = next(c for c in m["categories"] if c["stat"] == "PTS")
        assert pts["winner"] == "away"
        assert pts["catalyst"]["leader_name"] == "Winner"

    def test_notability_close_margin_qualifies(self):
        """margin_ratio ≤ 0.10 qualifies for notability."""
        rows = _nine_cat_rows(
            PTS_home_score=100,
            PTS_away_score=95,  # margin=5, ratio=0.05
            PTS_home_leader_name="Jokic",
            PTS_home_leader_value=40,
            PTS_home_team_total=100,
            PTS_away_leader_name="X",
            PTS_away_leader_value=10,
            PTS_away_team_total=95,
        )
        matchups = canonical_matchups(rows, 1)
        m = matchups[0]
        assert any(c["stat"] == "PTS" for c in m["catalysts"])

    def test_notability_concentrated_qualifies(self):
        """share ≥ 0.60 qualifies even with wide margin."""
        rows = _nine_cat_rows(
            PTS_home_score=100,
            PTS_away_score=30,  # wide margin (ratio=0.70)
            PTS_home_leader_name="Jokic",
            PTS_home_leader_value=70,  # 70/100 = 0.70 share
            PTS_home_team_total=100,
            PTS_away_leader_name="X",
            PTS_away_leader_value=1,
            PTS_away_team_total=30,
        )
        matchups = canonical_matchups(rows, 1)
        m = matchups[0]
        assert any(c["stat"] == "PTS" for c in m["catalysts"])

    def test_tied_category_no_catalyst(self):
        """A tied category has no winner → no catalyst."""
        rows = _nine_cat_rows()
        pts_row = rows[STAT_ORDER.index("PTS")]
        pts_row["current_home_score"] = 100
        pts_row["current_away_score"] = 100  # tie
        matchups = canonical_matchups(rows, 1)
        m = matchups[0]
        pts = next(c for c in m["categories"] if c["stat"] == "PTS")
        assert "catalyst" not in pts


# ── lineup_catalyst_data: the real box-score extraction path ──────────
# These exercise data_feed.lineup_catalyst_data directly (bench exclusion,
# leader selection, active-slot summation) — the logic the synthetic
# canonical_matchups tests above never touch because they inject the
# already-computed catalyst fields.
from backend.league.data_feed import lineup_catalyst_data


class _FakePlayer:
    """Minimal BoxPlayer stand-in: name, slot_position, points_breakdown."""

    def __init__(self, name, slot_position, points_breakdown):
        self.name = name
        self.slot_position = slot_position
        self.points_breakdown = points_breakdown


class TestLineupCatalystData:
    def test_empty_lineup_returns_empty(self):
        assert lineup_catalyst_data([]) == {}
        assert lineup_catalyst_data(None) == {}

    def test_active_sum_and_leader(self):
        lineup = [
            _FakePlayer("Jokic", "PG", {"PTS": 300, "REB": 120}),
            _FakePlayer("Role", "SG", {"PTS": 150, "REB": 40}),
        ]
        out = lineup_catalyst_data(lineup)
        assert out["PTS"]["team_total"] == 450.0
        assert out["PTS"]["leader_name"] == "Jokic"
        assert out["PTS"]["leader_value"] == 300.0
        assert out["REB"]["leader_name"] == "Jokic"
        assert out["REB"]["team_total"] == 160.0

    def test_bench_and_ir_excluded_from_total(self):
        lineup = [
            _FakePlayer("Starter", "SF", {"STL": 20}),
            _FakePlayer("Benched", "BE", {"STL": 100}),
            _FakePlayer("Injured", "IR", {"STL": 100}),
            _FakePlayer("FreeAgent", "FA", {"STL": 100}),
        ]
        out = lineup_catalyst_data(lineup)
        # Only the SF's 20 counts; bench/IR/FA are dropped.
        assert out["STL"]["team_total"] == 20.0
        assert out["STL"]["leader_name"] == "Starter"

    def test_leader_is_max_not_first(self):
        lineup = [
            _FakePlayer("Small", "PG", {"BLK": 2}),
            _FakePlayer("Big", "C", {"BLK": 9}),
            _FakePlayer("Mid", "PF", {"BLK": 5}),
        ]
        out = lineup_catalyst_data(lineup)
        assert out["BLK"]["leader_name"] == "Big"
        assert out["BLK"]["leader_value"] == 9.0
        assert out["BLK"]["team_total"] == 16.0

    def test_non_counting_stats_absent_from_output(self):
        lineup = [_FakePlayer("A", "PG", {"PTS": 10, "FG%": 0.5, "TO": 3})]
        out = lineup_catalyst_data(lineup)
        assert set(out.keys()) == {"PTS", "REB", "AST", "STL", "BLK", "3PM"}
        assert "FG%" not in out
        assert "TO" not in out

    def test_missing_breakdown_and_nonnumeric_are_safe(self):
        lineup = [
            _FakePlayer("NoData", "PG", {}),
            _FakePlayer("Garbage", "SG", {"AST": "not-a-number"}),
            _FakePlayer("Real", "SF", {"AST": 12}),
        ]
        out = lineup_catalyst_data(lineup)
        assert out["AST"]["team_total"] == 12.0
        assert out["AST"]["leader_name"] == "Real"
        # A stat nobody recorded yields no leader, zero total.
        assert out["PTS"]["leader_name"] is None
        assert out["PTS"]["team_total"] == 0.0

    def test_missing_slot_position_defaults_to_excluded_fa(self):
        # A player object without slot_position falls back to "FA" -> excluded.
        class _NoSlot:
            name = "Ghost"
            points_breakdown = {"PTS": 50}

        out = lineup_catalyst_data([_NoSlot()])
        assert out["PTS"]["team_total"] == 0.0
        assert out["PTS"]["leader_name"] is None
