"""P-4b: Slug-scoped route tests — routing, response envelopes, redirects.

Hermetic: no Supabase or ESPN needed. ``_snapshot_read`` is stubbed so
endpoints return canned data without hitting the DB.
"""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.league.credentials import _LEAGUE_CTX


@pytest.fixture
def stub_snapshot(monkeypatch):
    """Replace _snapshot_read with a hermetic stub returning canned data."""
    def _fake(phase, *, season=None):
        return ({"phase": phase, "rows": []}, "2026-07-18T00:00:00Z")
    monkeypatch.setattr(
        "backend.api.routers.league._snapshot_read",
        _fake,
    )


class TestSlugResolution:
    def test_slug_resolves_standings(self, stub_snapshot):
        """GET /leagues/{slug}/standings → 200 with {data, fetched_at} envelope."""
        client = TestClient(app)
        resp = client.get("/leagues/test-league/standings")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert "fetched_at" in body

    def test_unknown_slug_returns_404(self, stub_snapshot):
        """An unknown slug → exact 404 (not 500, not a crash)."""
        token = _LEAGUE_CTX.set(None)
        try:
            client = TestClient(app)
            resp = client.get("/leagues/nonexistent/standings")
            assert resp.status_code == 404
        finally:
            _LEAGUE_CTX.reset(token)

    def test_power_rankings_200(self, stub_snapshot):
        """Power rankings at /leagues/{slug}/power-rankings → 200."""
        client = TestClient(app)
        resp = client.get("/leagues/test-league/power-rankings")
        assert resp.status_code == 200

    def test_season_stats_200(self, stub_snapshot):
        """Season stats at /leagues/{slug}/season-stats → 200."""
        client = TestClient(app)
        resp = client.get("/leagues/test-league/season-stats?weeks=1")
        assert resp.status_code == 200


class TestOldPathRedirects:
    def test_league_standings_redirects(self):
        """Old /league/standings → 307 to /leagues/{slug}/standings."""
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/league/standings")
        assert resp.status_code == 307
        assert "/leagues/" in resp.headers["location"]
        assert "/standings" in resp.headers["location"]

    def test_power_rankings_redirects(self):
        """Old /power-rankings → 307 with query string preserved."""
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/power-rankings?weeks=1-5&recent_weeks=3")
        assert resp.status_code == 307
        loc = resp.headers["location"]
        assert "/leagues/" in loc
        assert "/power-rankings?" in loc
        assert "weeks=1-5" in loc
        assert "recent_weeks=3" in loc

    def test_season_stats_redirect_preserves_query(self):
        """Old /season-stats?weeks=1 → query string survives redirect."""
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/season-stats?weeks=1")
        assert resp.status_code == 307
        assert "weeks=1" in resp.headers["location"]
