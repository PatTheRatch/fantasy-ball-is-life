"""Request-scoped ESPN league cache (PR E2), plus a cross-request MyLeague TTL cache.

Every FastAPI request that touches ESPN constructs a fresh ``League`` object
via ``connect()``, which makes 4 HTTP calls (~2.5 MB) regardless of the view
the caller actually needs. In the recap path, ``assemble_weekly_snapshot()``
calls ``connect()`` 4 separate times → 12 redundant requests. In the Draft
Room, a default 10-plan portfolio infers 11 ``MyLeague`` constructions →
44 requests.

This module provides a per-request ``ContextVar``-backed cache that stores one
``ESPNHandles`` per ``(league_id, season)`` key, scoped to the lifetime of a
single HTTP request. FastAPI middleware sets the ``ContextVar`` before the
route runs and resets it on response — no cross-request leakage, no global
singleton that outlives the ESPN cookie validity window.

Consumers (``connect()``, ``_handles()``) become cache-aware transparently:
no caller needs to pass a cache handle or change its signature.

MyLeague TTL cache (perf follow-up): the per-request cache above only
dedupes constructions *within* a single HTTP request. In production,
``MyLeague()`` construction has been observed taking 140-171s (vs. ~1-2.5s
locally against the same live league) — almost certainly a Render-specific
network/throttling issue, not a code-level cost. Recap readiness and
generate are separate HTTP requests that both build the same
``(league_id, season)`` MyLeague, and clicking between weeks in the admin UI
does the same — each paying that cost from scratch. ``_MY_LEAGUE_TTL_CACHE``
below adds a short-lived (90s) process-global cache, keyed by
``(league_id, season)``, mirroring the snapshot cache pattern in
``backend/recaps/assemble.py`` (E3). A per-key lock also collapses concurrent
callers (e.g. two overlapping requests for the same league/season, which is
exactly what production logs showed) into a single ESPN fetch instead of
racing two independent slow fetches.
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
from typing import Optional

from backend.league.data_feed import ESPNHandles
from backend.league.fantasy import MyLeague  # exported so tests can patch it

_CACHE_VAR: contextvars.ContextVar[Optional["ESPNRequestCache"]] = (
    contextvars.ContextVar("espn_request_cache", default=None)
)

# --- cross-request MyLeague TTL cache -----------------------------------------

_MY_LEAGUE_TTL_SECONDS = 90
_MY_LEAGUE_TTL_CACHE: dict[tuple[int, int], tuple[float, Any]] = {}
"""key = (league_id, season), value = (monotonic timestamp, MyLeague instance)."""

_MY_LEAGUE_LOCKS: dict[tuple[int, int], threading.Lock] = {}
_MY_LEAGUE_LOCKS_GUARD = threading.Lock()


def _get_my_league_lock(key: tuple[int, int]) -> threading.Lock:
    with _MY_LEAGUE_LOCKS_GUARD:
        lock = _MY_LEAGUE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _MY_LEAGUE_LOCKS[key] = lock
        return lock


def _my_league_ttl_get(key: tuple[int, int]):
    entry = _MY_LEAGUE_TTL_CACHE.get(key)
    if entry is None:
        return None
    ts, ml = entry
    if time.monotonic() - ts > _MY_LEAGUE_TTL_SECONDS:
        _MY_LEAGUE_TTL_CACHE.pop(key, None)
        return None
    return ml


def _my_league_ttl_put(key: tuple[int, int], ml) -> None:
    _MY_LEAGUE_TTL_CACHE[key] = (time.monotonic(), ml)


def _clear_my_league_ttl_cache() -> None:
    """Test hook: reset the cross-request MyLeague TTL cache."""
    _MY_LEAGUE_TTL_CACHE.clear()


# --- cross-request WeeklyScoreboard TTL cache ---------------------------------
# Power rankings / season stats need only the box-score matchup view, not the
# full MyLeague (pro schedule, player map, draft). They fetch a narrow, single-
# call WeeklyScoreboard; this caches it with the same TTL + single-flight policy
# as MyLeague above so readiness -> generate and week-to-week clicks reuse it.

_SCOREBOARD_TTL_SECONDS = 90
_SCOREBOARD_TTL_CACHE: dict[tuple[int, int], tuple[float, Any]] = {}
_SCOREBOARD_LOCKS: dict[tuple[int, int], threading.Lock] = {}
_SCOREBOARD_LOCKS_GUARD = threading.Lock()


def _get_scoreboard_lock(key: tuple[int, int]) -> threading.Lock:
    with _SCOREBOARD_LOCKS_GUARD:
        lock = _SCOREBOARD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _SCOREBOARD_LOCKS[key] = lock
        return lock


def _scoreboard_ttl_get(key: tuple[int, int]):
    entry = _SCOREBOARD_TTL_CACHE.get(key)
    if entry is None:
        return None
    ts, sb = entry
    if time.monotonic() - ts > _SCOREBOARD_TTL_SECONDS:
        _SCOREBOARD_TTL_CACHE.pop(key, None)
        return None
    return sb


def _clear_scoreboard_ttl_cache() -> None:
    """Test hook: reset the cross-request scoreboard TTL cache."""
    _SCOREBOARD_TTL_CACHE.clear()


def get_cached_scoreboard(league_id: int, year: int) -> Any:
    """Return a (possibly cached) ``WeeklyScoreboard`` via the narrow fetch.

    Mirrors :func:`get_cached_my_league`'s 90s TTL + per-key single-flight, but
    builds a ``WeeklyScoreboard`` from a single-call ESPN fetch (box scores
    only) instead of the full 4-call ``MyLeague``.
    """
    from backend.league.scoreboard_fetch import fetch_scoreboard

    key = (league_id, year)
    sb = _scoreboard_ttl_get(key)
    if sb is not None:
        logging.info("get_cached_scoreboard: TTL-cache hit for (%s, %s)", league_id, year)
        return sb

    lock = _get_scoreboard_lock(key)
    with lock:
        sb = _scoreboard_ttl_get(key)
        if sb is not None:
            logging.info(
                "get_cached_scoreboard: TTL-cache hit for (%s, %s) after lock wait",
                league_id, year,
            )
            return sb
        started = time.perf_counter()
        sb = fetch_scoreboard(league_id, year)
        logging.info(
            "get_cached_scoreboard: narrow fetch for (%s, %s) took %.2fs",
            league_id, year, time.perf_counter() - started,
        )
        _SCOREBOARD_TTL_CACHE[key] = (time.monotonic(), sb)
        return sb


class ESPNRequestCache:
    """Per-request store that reuses one ``ESPNHandles`` per league key.

    The cache lives on a ``ContextVar`` — each request gets its own copy
    via middleware. ``connect()`` and ``_my_league()`` write entries;
    everyone else reads transparently.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[int, int], ESPNHandles] = {}
        self._my_league_store: dict[tuple[int, int], Any] = {}
        self.hits: int = 0
        self.misses: int = 0

    def get(self, league_id: int, season: int) -> Optional[ESPNHandles]:
        """Return the cached ``ESPNHandles``, or ``None`` on a miss.
        Increments ``hits`` or ``misses`` automatically (diagnostic counters)."""
        entry = self._store.get((league_id, season))
        if entry is not None:
            self.hits += 1
        else:
            self.misses += 1
        return entry

    def put(self, league_id: int, season: int, handles: ESPNHandles) -> None:
        """Cache an ``ESPNHandles`` for this request."""
        self._store[(league_id, season)] = handles

    def get_my_league(self, league_id: int, season: int) -> Optional[Any]:
        """Return the cached ``MyLeague``, or ``None`` on a miss.
        Increments ``hits`` or ``misses`` automatically."""
        entry = self._my_league_store.get((league_id, season))
        if entry is not None:
            self.hits += 1
        else:
            self.misses += 1
        return entry

    def put_my_league(self, league_id: int, season: int, my_league: Any) -> None:
        """Cache a ``MyLeague`` for this request."""
        self._my_league_store[(league_id, season)] = my_league


def get_request_cache() -> Optional[ESPNRequestCache]:
    """Return the per-request cache, or ``None`` outside an HTTP context."""
    return _CACHE_VAR.get()


def set_request_cache(cache: Optional[ESPNRequestCache]) -> None:
    """Set (or clear) the per-request cache."""
    _CACHE_VAR.set(cache)


def get_cached_my_league(league_id: int, year: int) -> Any:
    """Return a (possibly cached) ``MyLeague`` for the given league and season.

    Checks the per-request cache first, then the cross-request 90s TTL cache,
    before constructing a new ``MyLeague`` (4 ESPN requests). A per-key lock
    collapses concurrent misses (e.g. readiness and generate arriving close
    together) into a single ESPN fetch. Returns the uncached result when no
    request cache is active (CLI / tests) — the TTL cache still applies.

    Lives in the league layer (not ``api.deps``) so the Draft optimizer can
    import it without an upward dependency.
    """
    cache = get_request_cache()
    if cache is not None:
        existing = cache.get_my_league(league_id, year)
        if existing is not None:
            logging.info(
                "get_cached_my_league: request-cache hit for (%s, %s)", league_id, year
            )
            return existing

    key = (league_id, year)
    ml = _my_league_ttl_get(key)
    if ml is not None:
        logging.info("get_cached_my_league: TTL-cache hit for (%s, %s)", league_id, year)
        if cache is not None:
            cache.put_my_league(league_id, year, ml)
        return ml

    lock = _get_my_league_lock(key)
    with lock:
        # Re-check: another thread may have populated the TTL cache while we
        # were waiting on the lock (the "overlapping concurrent requests"
        # case observed in production).
        ml = _my_league_ttl_get(key)
        if ml is not None:
            logging.info(
                "get_cached_my_league: TTL-cache hit for (%s, %s) after lock wait",
                league_id, year,
            )
        else:
            started = time.perf_counter()
            ml = MyLeague(league_id, year)
            logging.info(
                "get_cached_my_league: MyLeague(%s, %s) construction took %.2fs",
                league_id, year, time.perf_counter() - started,
            )
            _my_league_ttl_put(key, ml)

    if cache is not None:
        cache.put_my_league(league_id, year, ml)

    return ml


class ESPNRequestCacheMiddleware:
    """FastAPI middleware that provisions a fresh ``ESPNRequestCache`` for every
    incoming HTTP or WebSocket request and tears it down on response. Attach
    via ``app.add_middleware(ESPNRequestCacheMiddleware)``.

    Uses raw ASGI middleware (not ``BaseHTTPMiddleware``) so the ``ContextVar``
    is set in the same task context as the route handler — ``BaseHTTPMiddleware``
    spawns a child task that breaks propagation.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        token = _CACHE_VAR.set(ESPNRequestCache())
        try:
            await self.app(scope, receive, send)
        finally:
            _CACHE_VAR.reset(token)
