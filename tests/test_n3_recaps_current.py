"""N-3: GET /leagues/{slug}/recaps/current — per-league season resolution.

Hermetic: the RecapStore dependency is overridden with a stub.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api.routers.recaps import get_recap_store
from backend.recaps.store import RecapStore


class StubStore:
    def __init__(self, league: dict[str, Any] | None, published=None):
        self.league = league
        self.published = published or []
        self.published_calls: list[tuple[str, int]] = []

    def get_league_by_slug(self, slug):
        return self.league if self.league and self.league["slug"] == slug else None

    def list_published(self, league_id, season):
        self.published_calls.append((league_id, season))
        return self.published


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.pop(get_recap_store, None)


def _use(store: StubStore) -> None:
    app.dependency_overrides[get_recap_store] = lambda: store


LEAGUE = {
    "id": "uuid-1",
    "slug": "other-league",
    "name": "Other League",
    "logo_url": None,
    "accent_color": "#123456",
    "visibility": "public",
    "espn_season": 2025,
}


class TestCurrentRecaps:
    def test_returns_configured_season_and_archive(self, client):
        store = StubStore(LEAGUE, published=[{"week": 3, "headline": "W3"}])
        _use(store)
        resp = client.get("/leagues/other-league/recaps/current")
        assert resp.status_code == 200
        body = resp.json()
        assert body["season"] == 2025
        assert body["league"]["slug"] == "other-league"
        assert body["league"]["name"] == "Other League"
        assert body["archive"] == [{"week": 3, "headline": "W3"}]
        # The archive was fetched for the league's own season, not a default.
        assert store.published_calls == [("uuid-1", 2025)]

    def test_unknown_slug_is_404(self, client):
        _use(StubStore(None))
        assert client.get("/leagues/nope/recaps/current").status_code == 404

    def test_missing_espn_season_is_500_not_wrong_data(self, client):
        league = dict(LEAGUE, espn_season=None)
        _use(StubStore(league))
        resp = client.get("/leagues/other-league/recaps/current")
        assert resp.status_code == 500

    def test_private_league_returns_meta_with_empty_archive(self, client):
        league = dict(LEAGUE, visibility="private")
        store = StubStore(league, published=[{"week": 9}])
        _use(store)
        resp = client.get("/leagues/other-league/recaps/current")
        assert resp.status_code == 200
        body = resp.json()
        assert body["season"] == 2025
        assert body["archive"] == []
        assert store.published_calls == []

    def test_literal_current_not_swallowed_by_season_route(self, client):
        """/recaps/current must match the literal route, and numeric seasons
        must keep hitting the archive route."""
        store = StubStore(LEAGUE, published=[{"week": 1}])
        _use(store)
        assert client.get("/leagues/other-league/recaps/current").status_code == 200
        resp = client.get("/leagues/other-league/recaps/2025")
        assert resp.status_code == 200
        assert resp.json() == [{"week": 1}]


class TestStoreSelectsSeason:
    def test_get_league_by_slug_selects_espn_season(self, monkeypatch):
        captured = {}

        def fake_request(self, method, path, *, params=None, json=None, prefer=None):
            captured["params"] = params
            return [dict(LEAGUE)]

        monkeypatch.setattr(RecapStore, "_request", fake_request)
        store = RecapStore(url="http://x", service_role_key="k")
        row = store.get_league_by_slug("other-league")
        assert "espn_season" in captured["params"]["select"]
        assert row["espn_season"] == 2025
