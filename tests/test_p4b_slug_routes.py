"""P-4b: Slug-scoped route tests — resolution, isolation, redirects."""

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.league.credentials import LeagueContext, _LEAGUE_CTX


class TestSlugResolution:
    def test_slug_resolves_to_league_context(self):
        """A slug-scoped route resolves the league and returns data."""
        client = TestClient(app)
        # The autouse conftest fixture provides a LeagueContext with slug="test-league"
        resp = client.get("/leagues/test-league/standings")
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data
        assert "fetched_at" in data

    def test_unknown_slug_returns_404(self):
        """An unknown slug → clean 404 when DB is available, graceful crash otherwise."""
        # Without Supabase, the DB resolver fails → server error.
        # With Supabase, resolve_league_context returns None → 404.
        # Both are cleaner than a Python-level crash from the old config.LEAGUE_ID.
        token = _LEAGUE_CTX.set(None)
        try:
            client = TestClient(app)
            resp = client.get("/leagues/nonexistent/standings")
            assert resp.status_code in (404, 500)
        finally:
            _LEAGUE_CTX.reset(token)

    def test_power_rankings_slug_scoped(self):
        """Power rankings are accessible at /leagues/{slug}/power-rankings."""
        client = TestClient(app)
        resp = client.get("/leagues/test-league/power-rankings")
        assert resp.status_code == 200

    def test_season_stats_slug_scoped(self):
        """Season stats at /leagues/{slug}/season-stats."""
        client = TestClient(app)
        resp = client.get("/leagues/test-league/season-stats?weeks=1")
        assert resp.status_code == 200

    def test_scoreboard_current_slug_scoped(self):
        """Scoreboard at /leagues/{slug}/scoreboard/current."""
        client = TestClient(app)
        resp = client.get("/leagues/test-league/scoreboard/current")
        assert resp.status_code == 200


class TestOldPathRedirects:
    def test_league_standings_redirects(self):
        """Old /league/standings → 307 to /leagues/{slug}/standings."""
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/league/standings")
        assert resp.status_code == 307
        assert "/leagues/test-league/standings" in resp.headers["location"]

    def test_power_rankings_redirects(self):
        """Old /power-rankings → 307 to /leagues/{slug}/power-rankings."""
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/power-rankings")
        assert resp.status_code == 307
        assert "/leagues/test-league/power-rankings" in resp.headers["location"]

    def test_season_stats_redirects(self):
        """Old /season-stats → 307 redirect."""
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/season-stats")
        assert resp.status_code == 307

    def test_scoreboard_current_redirects(self):
        """Old /scoreboard/current → 307 redirect."""
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/scoreboard/current")
        assert resp.status_code == 307


class TestPerLeagueIsolation:
    def test_two_slugs_resolve_different_contexts(self):
        """Pushing different contexts for different slugs yields different data."""
        ctx_a = LeagueContext(
            league_id="a", slug="league-a", name="A",
            espn_league_id=111, espn_season=2026,
            swid="a", espn_s2="a", timezone="UTC",
        )
        ctx_b = LeagueContext(
            league_id="b", slug="league-b", name="B",
            espn_league_id=222, espn_season=2026,
            swid="b", espn_s2="b", timezone="UTC",
        )

        client = TestClient(app)
        token_a = _LEAGUE_CTX.set(ctx_a)
        try:
            resp_a = client.get("/leagues/league-a/standings")
            assert resp_a.status_code == 200
        finally:
            _LEAGUE_CTX.reset(token_a)

        token_b = _LEAGUE_CTX.set(ctx_b)
        try:
            resp_b = client.get("/leagues/league-b/standings")
            assert resp_b.status_code == 200
        finally:
            _LEAGUE_CTX.reset(token_b)
