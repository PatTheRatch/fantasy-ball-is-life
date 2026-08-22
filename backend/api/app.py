"""Application factory."""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from backend.api.routers import health, identity, standings
from backend.platform.auth import JwksKeyset


def create_app(
    *,
    keyset: JwksKeyset | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    """Build the FastAPI app.

    ``keyset`` and ``session_factory`` are injectable for tests; the auth and
    DB dependencies read them from ``app.state``. Omitted, the app still builds
    (so the route-policy matrix test can enumerate routes without a database or
    keyset), but the endpoints that need them will fail if called.
    """
    app = FastAPI()
    app.state.jwks_keyset = keyset
    app.state.session_factory = session_factory

    app.include_router(health.router)
    app.include_router(identity.router)
    app.include_router(standings.router)
    return app
