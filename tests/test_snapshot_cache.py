"""PR E3 — snapshot reuse across recap readiness and generation.

assemble_weekly_snapshot() is called once for readiness and again for
generation within seconds of each other. A short-TTL app-level cache
(60 s, max 3 entries, FIFO eviction) avoids redoing the full ESPN
assembly when the two requests arrive seconds apart.
"""

from unittest.mock import Mock, patch

import pytest
import time

from backend.recaps.assemble import (
    _cache_get,
    _cache_key,
    _cache_put,
    _clear_snapshot_cache,
    _CACHE_TTL_SECONDS,
    assemble_weekly_snapshot,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear the module-global cache before every test so they don't
    contaminate each other under reordering or -k selection."""
    _clear_snapshot_cache()


# --- unit tests: cache functions ----------------------------------------------

def test_cache_get_returns_none_on_miss():
    assert _cache_get((1, 2026, 5)) is None


def test_cache_put_and_get():
    from backend.commentary.schemas import WeeklyFactSnapshot

    sn = WeeklyFactSnapshot.__new__(WeeklyFactSnapshot)
    key = (1, 2026, 5)
    _cache_put(key, sn)
    assert _cache_get(key) is sn


def test_cache_evicts_stale_entry():
    from backend.commentary.schemas import WeeklyFactSnapshot

    sn = WeeklyFactSnapshot.__new__(WeeklyFactSnapshot)
    key = (1, 2026, 5)
    _cache_put(key, sn)

    from backend.recaps import assemble

    old_ts = assemble._CACHE[key][0]
    assemble._CACHE[key] = (old_ts - _CACHE_TTL_SECONDS - 1, sn)

    assert _cache_get(key) is None


def test_cache_fifo_eviction():
    """Max 3 entries; the 4th evicts the oldest by insertion time."""
    from backend.commentary.schemas import WeeklyFactSnapshot
    from backend.recaps import assemble

    sn = WeeklyFactSnapshot.__new__(WeeklyFactSnapshot)
    for i in range(3):
        _cache_put((i, 2026, 1), sn)

    before = set(assemble._CACHE.keys())
    _cache_put((99, 2026, 1), WeeklyFactSnapshot.__new__(WeeklyFactSnapshot))
    after = set(assemble._CACHE.keys())
    # Oldest key (0, 2026, 1) should be gone, new key present.
    assert (0, 2026, 1) in before
    assert (0, 2026, 1) not in after
    assert (99, 2026, 1) in after
    assert len(assemble._CACHE) == 3


def test_clear_snapshot_cache():
    from backend.commentary.schemas import WeeklyFactSnapshot

    sn = WeeklyFactSnapshot.__new__(WeeklyFactSnapshot)
    _cache_put((1, 2026, 1), sn)
    assert _cache_get((1, 2026, 1)) is sn
    _clear_snapshot_cache()
    assert _cache_get((1, 2026, 1)) is None


# --- integration: assemble_weekly_snapshot uses the cache ---------------------

def test_second_call_reuses_snapshot_from_cache(monkeypatch):
    """Two calls with the same params within the TTL: the second must return
    the exact same object, and the ESPN lambdas must run only once.

    Uses the autouse cache-clear fixture and directly populates the cache to
    bypass the data_quality.ready gate (which is tested separately).
    """
    from backend.recaps import assemble
    from backend.commentary.schemas import WeeklyFactSnapshot

    _clear_snapshot_cache()

    call_count = 0

    def _counting_standings():
        nonlocal call_count
        call_count += 1
        return []

    import backend.api.routers.league as league_api

    monkeypatch.setattr(league_api, "league_standings", _counting_standings)
    monkeypatch.setattr(league_api, "power_rankings", lambda **kw: [])
    monkeypatch.setattr(league_api, "scoreboard_current", lambda **kw: [])
    monkeypatch.setattr(league_api, "transactions_week", lambda **kw: [])
    monkeypatch.setattr(league_api, "season_stats", lambda **kw: [])
    monkeypatch.setattr(league_api, "league_settings", lambda: {})
    monkeypatch.setattr(assemble, "_CACHE_TTL_SECONDS", 30)

    league = {"id": 1, "slug": "test", "name": "Test", "recap_voice": None}

    # First call — assemble and stash in cache directly.
    s1 = assemble_weekly_snapshot(
        league=league, season=2026, week=1,
        week_start="2025-10-01", week_end="2025-10-07",
    )
    first_count = call_count
    # Use time.monotonic() so the TTL check doesn't expire it.
    assemble._CACHE[_cache_key(league, 2026, 1)] = (time.monotonic(), s1)

    # Second call — should be a cache hit.
    s2 = assemble_weekly_snapshot(
        league=league, season=2026, week=1,
        week_start="2025-10-01", week_end="2025-10-07",
    )

    assert s1 is s2
    assert call_count == first_count  # no additional ESPN calls


def test_different_week_is_cache_miss(monkeypatch):
    """A different week must NOT return the cached snapshot."""
    from backend.recaps import assemble

    _clear_snapshot_cache()

    call_count = 0

    def _counting_standings():
        nonlocal call_count
        call_count += 1
        return []

    import backend.api.routers.league as league_api

    monkeypatch.setattr(league_api, "league_standings", _counting_standings)
    monkeypatch.setattr(league_api, "power_rankings", lambda **kw: [])
    monkeypatch.setattr(league_api, "scoreboard_current", lambda **kw: [])
    monkeypatch.setattr(league_api, "transactions_week", lambda **kw: [])
    monkeypatch.setattr(league_api, "season_stats", lambda **kw: [])
    monkeypatch.setattr(league_api, "league_settings", lambda: {})
    monkeypatch.setattr(assemble, "_CACHE_TTL_SECONDS", 30)

    league = {"id": 1, "slug": "test", "name": "Test", "recap_voice": None}

    assemble_weekly_snapshot(
        league=league, season=2026, week=1,
        week_start="2025-10-01", week_end="2025-10-07",
    )
    after_first = call_count

    assemble_weekly_snapshot(
        league=league, season=2026, week=2,
        week_start="2025-10-08", week_end="2025-10-14",
    )

    assert call_count > after_first  # new assembly ran


def test_degraded_snapshot_not_cached(monkeypatch):
    """A snapshot assembled during an ESPN blip (data_quality.ready=False)
    must NOT be cached — the next request retries ESPN."""
    from backend.recaps import assemble

    _clear_snapshot_cache()

    call_count = 0

    def _count():
        nonlocal call_count
        call_count += 1
        return []  # empty → ready will be False

    import backend.api.routers.league as league_api

    monkeypatch.setattr(league_api, "league_standings", _count)
    monkeypatch.setattr(league_api, "power_rankings", lambda **kw: (_count() and []))
    monkeypatch.setattr(league_api, "scoreboard_current", lambda **kw: (_count() and []))
    monkeypatch.setattr(league_api, "transactions_week", lambda **kw: (_count() and []))
    monkeypatch.setattr(league_api, "season_stats", lambda **kw: (_count() and []))
    monkeypatch.setattr(league_api, "league_settings", lambda: {})
    monkeypatch.setattr(assemble, "_CACHE_TTL_SECONDS", 30)

    league = {"id": 1, "slug": "test", "name": "Test", "recap_voice": None}

    s1 = assemble_weekly_snapshot(
        league=league, season=2026, week=1,
        week_start="2025-10-01", week_end="2025-10-07",
    )
    assert call_count == 5  # all 5 lambdas ran
    assert s1.data_quality.ready is False

    # Second call — cache should NOT have stored it, so lambdas run again.
    assemble_weekly_snapshot(
        league=league, season=2026, week=1,
        week_start="2025-10-01", week_end="2025-10-07",
    )
    assert call_count == 10  # second full assembly
