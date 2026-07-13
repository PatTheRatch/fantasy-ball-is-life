"""Request-scoped ESPN league cache (PR E2).

Every FastAPI request that touches ESPN constructs a fresh ``League`` object
via ``connect()``, which makes 4 HTTP calls (~2.5 MB) regardless of the view
the caller actually needs. In the recap path, ``assemble_weekly_snapshot()``
calls ``connect()`` 5 separate times → 20 redundant requests. In the Draft
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
from typing import Optional

from backend.league.data_feed import ESPNHandles

_CACHE_VAR: contextvars.ContextVar[Optional["ESPNRequestCache"]] = (
    contextvars.ContextVar("espn_request_cache", default=None)
)


class ESPNRequestCache:
    """Per-request store that reuses one ``ESPNHandles`` per league key.

    The cache lives on a ``ContextVar`` — each request gets its own copy
    via middleware. Only ``connect()`` writes entries; everyone else reads
    transparently.
    """

    def __init__(self) -> None:
        self._store: dict[tuple[int, int], ESPNHandles] = {}
        self.hits: int = 0
        self.misses: int = 0

    def get(self, league_id: int, season: int) -> Optional[ESPNHandles]:
        """Return the cached ``ESPNHandles``, or ``None`` on a miss."""
        return self._store.get((league_id, season))

    def put(self, league_id: int, season: int, handles: ESPNHandles) -> None:
        """Cache an ``ESPNHandles`` for this request."""
        self._store[(league_id, season)] = handles

    def load(self, league_id: int, season: int) -> None:
        """Mark a cache access as a hit (caller verified the entry exists)."""
        self.hits += 1

    def load_miss(self, league_id: int, season: int) -> None:
        """Mark a cache access as a miss."""
        self.misses += 1


def get_request_cache() -> Optional[ESPNRequestCache]:
    """Return the per-request cache, or ``None`` outside an HTTP context."""
    return _CACHE_VAR.get()


def set_request_cache(cache: Optional[ESPNRequestCache]) -> None:
    """Set (or clear) the per-request cache."""
    _CACHE_VAR.set(cache)


class ESPNRequestCacheMiddleware:
    """FastAPI middleware that provisions a fresh ``ESPNRequestCache`` for every
    incoming request and tears it down on response. Attach via
    ``app.add_middleware(ESPNRequestCacheMiddleware)``.
    """

    _implements_flask_middleware = True  # tells FastAPI/Starlette this is ASGI middleware

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
