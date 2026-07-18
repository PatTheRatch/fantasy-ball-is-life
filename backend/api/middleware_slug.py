"""P-4b: ASGI middleware — resolve league slug → LeagueContext per request.

The problem: a sync router-level dependency does ``_LEAGUE_CTX.set(ctx)``
in a threadpool call, but the sync handler runs in a *different* threadpool
call — the ContextVar is discarded between them. A ``Depends`` return-value
injection works for individual handlers but doesn't reach the global
``_resolve_ctx()`` / ``get_league_context()`` paths used by ``_snapshot_read``,
``_handles()``, and the rest of the data layer.

Fix: **ASGI middleware** that:
1. Extracts the ``{slug}`` from ``scope["path"]`` when it matches
   ``/leagues/{slug}/...``.
2. Calls ``resolve_league_context(slug=slug)`` to fetch from the DB.
3. Sets ``_LEAGUE_CTX.set(ctx)`` so every downstream call — dependency,
   handler body, helper — sees the same context.
4. Resets ``_LEAGUE_CTX`` in a ``finally`` to prevent cross-request leaks.

For paths that don't match the slug pattern (``/admin/...``, ``/optimizer/...``,
flat legacy redirects, etc.) the middleware is a no-op — the single-league
interim path in ``_resolve_ctx()`` fills in for those.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from backend.league.credentials import (
    _LEAGUE_CTX,
    resolve_league_context,
)

#: Match /leagues/{slug}/... → capture group 1 = slug
_SLUG_PATH_RE = re.compile(r"^/leagues/([^/]+)([/?].*)?$")


class LeagueSlugMiddleware:
    """ASGI middleware: resolve slug → LeagueContext for the request lifetime."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "").rstrip("/") or "/"
        m = _SLUG_PATH_RE.match(path)
        slug = m.group(1) if m else None

        if slug is None:
            # Not a slug-scoped path — let the single-league interim handle it
            await self.app(scope, receive, send)
            return

        ctx = resolve_league_context(slug=slug)
        if ctx is not None:
            token = _LEAGUE_CTX.set(ctx)
            try:
                await self.app(scope, receive, send)
            finally:
                _LEAGUE_CTX.reset(token)
        else:
            # Slug not found — let the router-level dependency return 404
            await self.app(scope, receive, send)
