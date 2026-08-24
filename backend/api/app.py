"""Application factory.

Bare ``create_app()`` wires the JWKS keyset and the database session factory
from the environment — the production path, and the runbook's command. Passing
``keyset`` / ``session_factory`` explicitly overrides them; ``load_from_env=False``
builds the no-config app the route-policy matrix test needs (no database, no
network).

Known limitation (out of scope for H-11): the keyset is loaded once at startup,
so if Supabase rotates signing keys, every token fails ``UnknownKey`` until the
process restarts. Rotation is manual and rare, and there is no deployment yet,
so the exposure is zero. Follow-up: a bounded refetch on ``UnknownKey`` with a
cooldown so a flood of bad tokens cannot cause a fetch storm.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from backend.api.routers import health, identity, periods, standings
from backend.platform.auth import JwksKeyset, index_keyset
from backend.platform.db import make_engine, make_session_factory
from backend.platform.settings import database_url, jwt_jwks_url

#: The JWKS fetch timeout. A startup fetch that hangs is a crash-loop, not an
#: error — S1-02's transport lesson (an unbounded request is a hang).
JWKS_FETCH_TIMEOUT_SECONDS = 5.0


class JwksFetchError(RuntimeError):
    """The JWKS could not be fetched or parsed at startup."""


def _fetch_jwks(url: str) -> dict[str, Any]:
    """Fetch and parse the JWKS document from ``url`` (with an explicit timeout)."""
    try:
        with urllib.request.urlopen(url, timeout=JWKS_FETCH_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except (OSError, ValueError) as exc:
        raise JwksFetchError(f"could not fetch JWKS from {url}: {exc}") from exc

    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise JwksFetchError(f"invalid JWKS from {url}: {exc}") from exc

    if not isinstance(document, dict):
        raise JwksFetchError(f"invalid JWKS from {url}: expected a JSON object")
    return document


def _load_keyset_from_env() -> JwksKeyset:
    """Load the JWKS keyset from ``SUPABASE_JWKS_URL``, indexed by ``kid``."""
    return index_keyset(_fetch_jwks(jwt_jwks_url()))


def _build_session_factory_from_env() -> sessionmaker[Session]:
    """Build a session factory bound to the ``DATABASE_URL`` engine."""
    return make_session_factory(make_engine(database_url()))


def create_app(
    *,
    keyset: JwksKeyset | None = None,
    session_factory: sessionmaker[Session] | None = None,
    load_from_env: bool = True,
) -> FastAPI:
    """Build the FastAPI app.

    ``keyset`` and ``session_factory`` are injectable for tests; explicit values
    take precedence and ``load_from_env`` governs only what was not supplied.
    Bare ``create_app()`` therefore loads both from the environment (the
    production path), while ``create_app(load_from_env=False)`` builds the
    no-config app — the route-policy matrix test enumerates routes with no
    database and no network.

    A missing setting or a failed JWKS fetch raises here, during construction,
    rather than returning an app that answers ``/health`` while 500ing every
    authenticated route (charter D28: no silent degradation).
    """
    if load_from_env:
        if keyset is None:
            keyset = _load_keyset_from_env()
        if session_factory is None:
            session_factory = _build_session_factory_from_env()

    app = FastAPI()
    app.state.jwks_keyset = keyset
    app.state.session_factory = session_factory

    app.include_router(health.router)
    app.include_router(identity.router)
    app.include_router(standings.router)
    app.include_router(periods.router)
    return app
