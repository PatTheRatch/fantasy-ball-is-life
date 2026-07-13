"""PR E2 — request-scoped ESPN league cache.

Every ``connect()`` call constructs a new ``League`` (4 ESPN requests, ~2.5 MB).
The recap path calls ``connect()`` 5 separate times, and the Draft Room calls
it 11+ times per portfolio. This middleware-backed cache reuses one
``ESPNHandles`` per HTTP request, transparently.

These tests verify:
- cache deduplication within a single request
- isolation across requests (no leakage)
- back-compat when cache is absent (e.g. CLI / Streamlit)
"""

from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.api.main import app
from backend.league import cache
from backend.league.cache import (
    ESPNRequestCache,
    ESPNRequestCacheMiddleware,
    get_request_cache,
    set_request_cache,
)
from backend.league.data_feed import connect

_FAKE_LEAGUE_ID = 123456
_FAKE_SEASON = 2026


# --- unit tests: ESPNRequestCache --------------------------------------------

def test_cache_returns_none_on_miss():
    c = ESPNRequestCache()
    assert c.get(1, 2026) is None


def test_cache_stores_and_retrieves_by_key():
    from backend.league.data_feed import ESPNHandles

    c = ESPNRequestCache()
    h = ESPNHandles(league=Mock())
    c.put(1, 2026, h)
    assert c.get(1, 2026) is h
    assert c.get(2, 2026) is None
    assert c.get(1, 2025) is None


def test_get_auto_counts_hits_and_misses():
    from backend.league.data_feed import ESPNHandles

    c = ESPNRequestCache()
    h = ESPNHandles(league=Mock())
    c.put(1, 2026, h)
    # Hit
    assert c.get(1, 2026) is h
    # Miss
    assert c.get(2, 2026) is None
    # Another hit
    assert c.get(1, 2026) is h
    assert c.hits == 2
    assert c.misses == 1


# --- unit tests: ContextVar lifecycle ----------------------------------------

def test_context_var_defaults_to_none():
    assert get_request_cache() is None


def test_set_and_clear_request_cache():
    c = ESPNRequestCache()
    set_request_cache(c)
    assert get_request_cache() is c
    set_request_cache(None)
    assert get_request_cache() is None


# --- integration: middleware provisions cache per request --------------------

def test_middleware_provisions_cache_during_request():
    """Any request through TestClient must have a cache available."""
    client = TestClient(app)

    @app.get("/__test_cache__")
    def _test_cache_endpoint():
        c = get_request_cache()
        return {"has_cache": c is not None, "type": type(c).__name__}

    resp = client.get("/__test_cache__")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_cache"] is True
    assert data["type"] == "ESPNRequestCache"


def test_middleware_clears_cache_after_request():
    """After a request completes, the ContextVar must be None again (no leak)."""
    client = TestClient(app)

    resp = client.get("/health")
    assert resp.status_code == 200
    # Outside a request context, no cache.
    assert get_request_cache() is None


def test_cache_isolates_between_requests():
    """Request A's cache must not be visible in Request B."""
    client = TestClient(app)
    cache_a = {}

    @app.get("/__test_cache_a__")
    def _cache_a():
        c = get_request_cache()
        c.put(1, 2026, "handles-a")
        cache_a["id"] = id(c)
        return {"id": id(c)}

    @app.get("/__test_cache_b__")
    def _cache_b():
        c = get_request_cache()
        return {
            "has_a_entry": c.get(1, 2026) is not None,
            "id_different": id(c) != cache_a.get("id"),
        }

    client.get("/__test_cache_a__")
    resp = client.get("/__test_cache_b__")
    data = resp.json()
    assert data["has_a_entry"] is False  # no leakage
    assert data["id_different"] is True  # different cache instance


# --- integration: connect() uses the cache transparently ---------------------

def test_connect_reuses_cached_handles(monkeypatch):
    """Inside a request context, the second connect() must return the cached
    handles (same object), and the League constructor must only be called once."""
    from backend.league import data_feed as df

    client = TestClient(app)
    call_count = 0

    def _counting_league(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        from espn_api.basketball import League as _League
        league = Mock(spec=_League)
        league.league_id = df.LEAGUE_ID
        return league

    monkeypatch.setattr(df, "League", _counting_league)

    @app.get("/__test_connect_reuse__")
    def _connect_reuse():
        h1 = connect()
        h2 = connect()
        return {"same": h1 is h2, "count": call_count}

    resp = client.get("/__test_connect_reuse__")
    data = resp.json()
    assert data["same"] is True
    assert data["count"] == 1


def test_connect_works_without_cache_outside_request(monkeypatch):
    """CLI / Streamlit contexts have no middleware → connect() must still work."""
    from backend.league import data_feed as df

    # Simulate: no cache ContextVar set.
    set_request_cache(None)

    mock_league = Mock()
    mock_league.league_id = _FAKE_LEAGUE_ID
    monkeypatch.setattr(df, "League", Mock(return_value=mock_league))

    h = connect()
    assert h.league is mock_league


def test_connect_refresh_after_middleware_lifecycle(monkeypatch):
    """After a request completes (cache cleared), the next request gets a fresh
    cache that again starts at miss."""
    from backend.league import data_feed as df

    client = TestClient(app)
    call_count = 0

    def _counting_league(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        from espn_api.basketball import League as _League
        league = Mock(spec=_League)
        league.league_id = df.LEAGUE_ID
        return league

    monkeypatch.setattr(df, "League", _counting_league)

    @app.get("/__test_refresh__")
    def _refresh():
        connect()
        return {"count": call_count}

    # Two separate requests — each should trigger one construction.
    r1 = client.get("/__test_refresh__")
    r2 = client.get("/__test_refresh__")
    assert r1.json()["count"] == 1
    assert r2.json()["count"] == 2  # fresh cache, new construction


def test_league_constructor_failure_does_not_cache_and_cleans_up(monkeypatch):
    """If the League constructor raises inside a request, nothing is cached
    and the ContextVar is still reset after the request returns — no leak."""
    from backend.league import data_feed as df

    client = TestClient(app)
    call_count = 0

    def _failing_league(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("ESPN unreachable")

    monkeypatch.setattr(df, "League", _failing_league)

    client = TestClient(app, raise_server_exceptions=False)

    @app.get("/__test_constructor_failure__")
    def _fail():
        connect()
        return {}

    resp = client.get("/__test_constructor_failure__")
    assert resp.status_code == 500
    assert call_count == 1
    # After the request returns, no cache should leak.
    assert get_request_cache() is None
