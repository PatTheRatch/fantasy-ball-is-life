"""P-4b: Slug-scoped league resolution dependency.

Injects the league context onto the ``_LEAGUE_CTX`` ContextVar for the
request lifetime, then yields it for route handlers. Unknown slug → 404.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException

from backend.league.credentials import (
    LeagueContext,
    _LEAGUE_CTX,
    get_league_context,
    resolve_league_context,
)


def _resolve_slug(slug: str) -> LeagueContext:
    """Resolve a league slug → LeagueContext for the request.

    Pushes the context onto ``_LEAGUE_CTX`` so ``get_league_context()``
    returns it for the rest of the request. Unknown slug → 404.

    Checks the ContextVar first (test/CLI-injected context), then falls
    back to DB resolution.
    """
    # Check ContextVar first (tests/CLI can push a stub)
    existing = get_league_context()
    if existing is not None and existing.slug == slug:
        return existing

    # Resolve from DB
    ctx = resolve_league_context(slug=slug)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"League not found: {slug}")
    _LEAGUE_CTX.set(ctx)
    return ctx


LeagueSlugDep = Depends(_resolve_slug)
"""FastAPI dependency: inject ``LeagueContext`` for the current {slug}."""
