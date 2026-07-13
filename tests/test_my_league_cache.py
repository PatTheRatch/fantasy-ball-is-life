"""PR F — MyLeague caching via E2's request-scoped ContextVar store.

_my_league() and the Draft optimizer construct a new MyLeague every call,
each making 4 ESPN requests. The recap's power_rankings() and season_stats()
call _my_league() twice per assembly, and the Draft Room calls it once per
solve (11+ for a 10-plan portfolio).

This cache extends E2's ESPNRequestCache with a MyLeague store. _my_league()
checks the cache before constructing; the Draft optimizer now routes through
_my_league() instead of calling MyLeague() directly.

Wins:
- Recap: power_rankings + season_stats → 1 MyLeague construction (was 2)
- Draft Room: 10-plan portfolio → 1 MyLeague construction (was 11)
- Full recap assembly: 22 ESPN requests → ~6 (with E2 + E3 + this)
"""

from unittest.mock import Mock, patch

import pytest

from backend.league.cache import ESPNRequestCache


# --- unit tests: ESPNRequestCache MyLeague store ------------------------------

def test_my_league_cache_returns_none_on_miss():
    c = ESPNRequestCache()
    assert c.get_my_league(1, 2026) is None


def test_my_league_cache_stores_and_retrieves():
    c = ESPNRequestCache()
    mock_ml = object()
    c.put_my_league(1, 2026, mock_ml)
    assert c.get_my_league(1, 2026) is mock_ml
    assert c.get_my_league(2, 2026) is None
    assert c.get_my_league(1, 2025) is None


def test_my_league_cache_counts_hits_and_misses():
    c = ESPNRequestCache()
    c.put_my_league(1, 2026, object())
    c.get_my_league(1, 2026)  # hit
    c.get_my_league(1, 2026)  # hit
    c.get_my_league(2, 2026)  # miss
    assert c.hits == 2
    assert c.misses == 1


def test_my_league_store_isolated_from_handles_store():
    c = ESPNRequestCache()
    from backend.league.data_feed import ESPNHandles

    h = ESPNHandles(league=Mock())
    ml = object()
    c.put(1, 2026, h)
    c.put_my_league(1, 2026, ml)
    assert c.get(1, 2026) is h
    assert c.get_my_league(1, 2026) is ml


# --- integration: _my_league() uses the cache ---------------------------------

def test_my_league_reuses_cached_instance(monkeypatch):
    """Two calls to _my_league() in the same request: second returns
    the cached instance, and MyLeague constructor runs only once."""
    from fastapi.testclient import TestClient

    from backend.api.main import app
    from backend.api.deps import _my_league
    from backend.api import deps as dmod

    client = TestClient(app)
    call_count = 0

    original_ml = dmod.MyLeague

    def _counting_ml(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # Return a real-ish mock that won't crash downstream consumers
        ml = Mock(spec=original_ml)
        ml.settings = Mock()
        ml.settings.reg_season_count = 20
        ml.settings.team_count = 14
        ml.stat_categories = []
        ml.length_of_schedule = 20
        return ml

    monkeypatch.setattr(dmod, "MyLeague", _counting_ml)

    @app.get("/__test_my_league_reuse__")
    def _reuse():
        ml1 = _my_league()
        ml2 = _my_league()
        return {"same": ml1 is ml2, "count": call_count}

    resp = client.get("/__test_my_league_reuse__")
    data = resp.json()
    assert data["same"] is True
    assert data["count"] == 1


def test_my_league_works_without_cache_outside_request(monkeypatch):
    """CLI / Streamlit contexts have no middleware → _my_league() must still work."""
    from backend.league.cache import set_request_cache
    from backend.api import deps as dmod

    set_request_cache(None)

    mock_ml = Mock()
    monkeypatch.setattr(dmod, "MyLeague", Mock(return_value=mock_ml))

    from backend.api.deps import _my_league

    ml = _my_league()
    assert ml is mock_ml


def test_my_league_isolation_between_requests(monkeypatch):
    """Request A's cached MyLeague must not leak into Request B."""
    from fastapi.testclient import TestClient

    from backend.api.main import app
    from backend.api.deps import _my_league
    from backend.api import deps as dmod

    client = TestClient(app)
    call_count = 0

    def _counting_ml(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        ml = Mock()
        ml.settings = Mock()
        ml.settings.reg_season_count = 20
        ml.settings.team_count = 14
        ml.stat_categories = []
        ml.length_of_schedule = 20
        return ml

    monkeypatch.setattr(dmod, "MyLeague", _counting_ml)

    @app.get("/__test_ml_req_a__")
    def _req_a():
        _my_league()
        return {"ok": True}

    @app.get("/__test_ml_req_b__")
    def _req_b():
        _my_league()
        return {"ok": True}

    client.get("/__test_ml_req_a__")
    client.get("/__test_ml_req_b__")
    assert call_count == 2  # One construction per request
