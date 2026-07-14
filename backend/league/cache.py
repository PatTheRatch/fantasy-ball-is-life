"""Request-scoped ESPN league cache (PR E2).

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
"""

from __future__ import annotations

import contextvars
import logging
import time
from typing import Optional

from backend.league.data_feed import ESPNHandles
from backend.league.fantasy import MyLeague  # exported so tests can patch it

_CACHE_VAR: contextvars.ContextVar[Optional["ESPNRequestCache"]] = (
    contextvars.ContextVar("espn_request_cache", default=None)
)


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

    Checks the per-request cache first; constructs a new ``MyLeague`` (4 ESPN
    requests) on a miss, then stores it. Returns the uncached result when no
    request cache is active (CLI / Streamlit).

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

    started = time.perf_counter()
    ml = MyLeague(league_id, year)
    logging.info(
        "get_cached_my_league: MyLeague(%s, %s) construction took %.2fs",
        league_id, year, time.perf_counter() - started,
    )

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
