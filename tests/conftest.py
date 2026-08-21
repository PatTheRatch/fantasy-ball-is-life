"""Shared fixtures.

The secret-scrubbing fixture is ported verbatim in spirit from V1, where it
was the single best piece of test infrastructure: it removes deployment
secrets from the environment before every test, so a local run is structurally
identical to a clean CI run. "Passes locally, fails in CI" caused by a leaked
env var becomes impossible — the dependency fails everywhere, so it is caught
before push.
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from backend.platform.db import make_engine, make_session_factory

REPO = pathlib.Path(__file__).resolve().parent.parent

SCRUBBED_SECRETS = (
    "DATABASE_URL",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWKS_URL",
    "SUPABASE_JWT_ISSUER",
    "SUPABASE_JWT_AUDIENCE",
    "CRED_ENCRYPTION_KEY",
    "WORKER_SECRET",
    "ESPN_SWID",
    "ESPN_S2",
    "ESPN_LEAGUE_ID",
    "ESPN_SEASON",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "RESEND_API_KEY",
)


@pytest.fixture(autouse=True)
def _scrub_ambient_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove deployment secrets from the environment for every test.

    Autouse fixtures run before test-requested ones at the same scope, so a
    fixture that legitimately needs a value can still set it afterwards.
    """
    for name in SCRUBBED_SECRETS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def db_url() -> str:
    """The test database URL, or skip when unset (CI provides a Postgres)."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; runs in CI against the Postgres service")
    return url


@pytest.fixture
def migrated_session_factory(db_url: str) -> Iterator[sessionmaker[Session]]:
    """Migrate the test DB to head, truncate identity tables, and hand out a
    session factory bound to it."""
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")

    engine = make_engine(db_url)
    with Session(engine) as session:
        for table in ("manager_user_links", "managers", "users"):
            session.execute(text(f'TRUNCATE "{table}" CASCADE'))
        session.commit()

    try:
        yield make_session_factory(engine)
    finally:
        engine.dispose()


@pytest.fixture
def db_session(migrated_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """A truncated, migrated session for repository/service tests."""
    with migrated_session_factory() as session:
        yield session
