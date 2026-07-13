"""PR E3 — snapshot reuse across recap readiness and generation.

assemble_weekly_snapshot() is called once for readiness and again for
generation within seconds of each other. A short-TTL app-level cache
(60 s, max 3 entries, LRU eviction) avoids redoing the full ESPN
assembly when the two requests arrive seconds apart.
"""

import time
from unittest.mock import Mock, patch

from backend.recaps.assemble import (
    _cache_get,
    _cache_key,
    _cache_put,
    _clear_snapshot_cache,
    _CACHE_TTL_SECONDS,
    assemble_weekly_snapshot,
)


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

    # Rewind the timestamp so it looks expired
    from backend.recaps import assemble

    old_ts = assemble._CACHE[key][0]
    assemble._CACHE[key] = (old_ts - _CACHE_TTL_SECONDS - 1, sn)

    assert _cache_get(key) is None  # expired entry should be evicted


def test_cache_lru_eviction():
    from backend.commentary.schemas import WeeklyFactSnapshot
    from backend.recaps import assemble

    sn = WeeklyFactSnapshot.__new__(WeeklyFactSnapshot)
    # Fill all 3 slots
    for i in range(3):
        _cache_put((i, 2026, 1), sn)
        _cache_put((i, 2026, 2), sn)  # update so ts is distinct

    # The 4th should evict the oldest
    _cache_put((0, 2026, 1), WeeklyFactSnapshot.__new__(WeeklyFactSnapshot))
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
    the exact same object, and the ESPN lambdas must run only once."""
    from backend.recaps import assemble

    _clear_snapshot_cache()

    call_count = 0

    def _counting_standings():
        nonlocal call_count
        call_count += 1
        return []

    def _counting_rankings(**kwargs):
        nonlocal call_count
        call_count += 1
        return []

    def _counting_scoreboard(**kwargs):
        nonlocal call_count
        call_count += 1
        return []

    def _counting_transactions(**kwargs):
        nonlocal call_count
        call_count += 1
        return []

    def _counting_season_stats(**kwargs):
        nonlocal call_count
        call_count += 1
        return []

    def _fake_settings():
        return {}

    import backend.api.routers.league as league_api

    monkeypatch.setattr(league_api, "league_standings", _counting_standings)
    monkeypatch.setattr(league_api, "power_rankings", _counting_rankings)
    monkeypatch.setattr(league_api, "scoreboard_current", _counting_scoreboard)
    monkeypatch.setattr(league_api, "transactions_week", _counting_transactions)
    monkeypatch.setattr(league_api, "season_stats", _counting_season_stats)
    monkeypatch.setattr(league_api, "league_settings", _fake_settings)
    monkeypatch.setattr(assemble, "_CACHE_TTL_SECONDS", 30)

    league = {"id": 1, "slug": "test", "name": "Test", "recap_voice": None}

    s1 = assemble_weekly_snapshot(
        league=league, season=2026, week=1,
        week_start="2025-10-01", week_end="2025-10-07",
    )
    first_count = call_count

    s2 = assemble_weekly_snapshot(
        league=league, season=2026, week=1,
        week_start="2025-10-01", week_end="2025-10-07",
    )

    assert s1 is s2
    assert call_count == first_count  # no additional calls


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
