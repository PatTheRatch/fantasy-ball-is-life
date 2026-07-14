"""Cross-request TTL + single-flight cache for the narrow WeeklyScoreboard fetch.

Power rankings / season stats fetch a box-score-only WeeklyScoreboard instead of
the full MyLeague. `get_cached_scoreboard` reuses it across the separate
readiness -> generate requests (and week-to-week clicks) within a 90s window,
and collapses concurrent misses into a single ESPN fetch.
"""
from unittest.mock import Mock

import pytest

from backend.league import cache
from backend.league.cache import _clear_scoreboard_ttl_cache, get_cached_scoreboard


@pytest.fixture(autouse=True)
def _reset():
    _clear_scoreboard_ttl_cache()
    yield
    _clear_scoreboard_ttl_cache()


def _patch_fetch(monkeypatch):
    """Patch the lazily-imported fetch_scoreboard; return the call counter."""
    calls = {"n": 0}

    def _fake(league_id, year, *a, **k):
        calls["n"] += 1
        return Mock(name=f"scoreboard-{league_id}-{year}")

    import backend.league.scoreboard_fetch as sf
    monkeypatch.setattr(sf, "fetch_scoreboard", _fake)
    return calls


def test_ttl_cache_reused_across_calls(monkeypatch):
    calls = _patch_fetch(monkeypatch)
    a = get_cached_scoreboard(1, 2026)
    b = get_cached_scoreboard(1, 2026)
    assert a is b
    assert calls["n"] == 1


def test_ttl_cache_isolated_by_key(monkeypatch):
    calls = _patch_fetch(monkeypatch)
    get_cached_scoreboard(1, 2026)
    get_cached_scoreboard(2, 2026)
    get_cached_scoreboard(1, 2025)
    assert calls["n"] == 3


def test_ttl_cache_expires(monkeypatch):
    calls = _patch_fetch(monkeypatch)
    fake_now = [1000.0]
    monkeypatch.setattr(cache.time, "monotonic", lambda: fake_now[0])
    get_cached_scoreboard(1, 2026)
    fake_now[0] += cache._SCOREBOARD_TTL_SECONDS + 1
    get_cached_scoreboard(1, 2026)
    assert calls["n"] == 2


def test_scoreboard_and_my_league_caches_are_independent(monkeypatch):
    _patch_fetch(monkeypatch)
    sb = get_cached_scoreboard(1, 2026)
    # A scoreboard entry must not satisfy a MyLeague lookup or vice-versa.
    assert cache._scoreboard_ttl_get((1, 2026)) is sb
    assert cache._my_league_ttl_get((1, 2026)) is None
