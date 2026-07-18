"""P-4b: Middleware isolation tests — prove slug → context resolves per-request.

These tests work WITHOUT the top-level conftest ContextVar. They stub
resolve_league_context and wrap a trivial handler, so they exercise the
middleware's slug→context resolution directly. If the middleware regresses
(ContextVar discarded across threadpool), these catch it.
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware_slug import LeagueSlugMiddleware
from backend.league.credentials import LeagueContext, _LEAGUE_CTX, get_league_context


def _build_test_app():
    """Minimal FastAPI app with the slug middleware and a context-echo handler."""
    app = FastAPI()

    @app.get("/leagues/{slug}/whoami")
    def whoami(slug: str):
        ctx = get_league_context()
        if ctx is None:
            return {"slug": slug, "ctx": None}
        return {"slug": slug, "espn_league_id": ctx.espn_league_id}

    app.add_middleware(LeagueSlugMiddleware)
    return app


@pytest.fixture
def stub_resolver():
    """Stub resolve_league_context(slug=...) → canned LeagueContext."""
    ctx_map = {
        "league-a": LeagueContext(
            league_id="a", slug="league-a", name="A",
            espn_league_id=111, espn_season=2026,
            swid="a-s", espn_s2="a-s2", timezone="UTC",
        ),
        "league-b": LeagueContext(
            league_id="b", slug="league-b", name="B",
            espn_league_id=222, espn_season=2026,
            swid="b-s", espn_s2="b-s2", timezone="UTC",
        ),
    }

    def _resolve(*, slug=None, store=None):
        return ctx_map.get(slug)

    return _resolve


class TestMiddlewareIsolation:
    def test_two_slugs_yield_different_league_ids(self, stub_resolver):
        """GET /leagues/league-a/whoami → 111, GET /leagues/league-b/whoami → 222.

        No top-level ContextVar is pushed — the middleware resolves the slug
        from the URL and sets _LEAGUE_CTX per request.
        """
        app = _build_test_app()
        _LEAGUE_CTX.set(None)  # clear any leaked state

        with patch("backend.api.middleware_slug.resolve_league_context", side_effect=stub_resolver):
            client = TestClient(app)

            resp_a = client.get("/leagues/league-a/whoami")
            assert resp_a.status_code == 200
            assert resp_a.json()["espn_league_id"] == 111

            resp_b = client.get("/leagues/league-b/whoami")
            assert resp_b.status_code == 200
            assert resp_b.json()["espn_league_id"] == 222

    def test_unknown_slug_returns_ctx_none(self, stub_resolver):
        """Unknown slug → middleware can't resolve → //ctx is None."""
        app = _build_test_app()
        _LEAGUE_CTX.set(None)

        with patch("backend.api.middleware_slug.resolve_league_context", side_effect=stub_resolver):
            client = TestClient(app)
            resp = client.get("/leagues/nonexistent/whoami")
            assert resp.status_code == 200
            assert resp.json()["ctx"] is None

    def test_context_does_not_leak_between_requests(self, stub_resolver):
        """After a request for league-a, a non-slug path has no context."""
        app = _build_test_app()
        _LEAGUE_CTX.set(None)

        @app.get("/flat/whoami")
        def flat_whoami():
            ctx = get_league_context()
            return {"ctx": ctx.espn_league_id if ctx else None}

        with patch("backend.api.middleware_slug.resolve_league_context", side_effect=stub_resolver):
            client = TestClient(app)

            # Request league-a first
            resp_a = client.get("/leagues/league-a/whoami")
            assert resp_a.json()["espn_league_id"] == 111

            # Non-slug request must NOT see league-a's context
            resp_flat = client.get("/flat/whoami")
            assert resp_flat.json()["ctx"] is None
