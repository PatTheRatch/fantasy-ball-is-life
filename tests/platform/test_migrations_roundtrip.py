"""Migration round-trip: apply → roll back → re-apply against a real Postgres.

Runs only when ``TEST_DATABASE_URL`` is set (CI provides a Postgres service
and sets it). Locally it skips rather than faking a green check — a migration
that cannot be rolled back is exactly the failure this test exists to catch.

The URL is injected onto the Alembic config as ``sqlalchemy.url``, which
``migrations/env.py`` prefers over the ``DATABASE_URL`` setting, so the test
can never touch a development or production database.
"""

from __future__ import annotations

import os
import pathlib

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

REPO = pathlib.Path(__file__).resolve().parent.parent.parent


def _test_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL not set; runs in CI against the Postgres service")
    return url


def _config(url: str) -> Config:
    cfg = Config(str(REPO / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _extension_exists(url: str, name: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = :name"),
                {"name": name},
            )
            return result.scalar() is not None
    finally:
        engine.dispose()


def _table_exists(url: str, name: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = :name"
                ),
                {"name": name},
            )
            return result.scalar() is not None
    finally:
        engine.dispose()


IDENTITY_TABLES = ("users", "managers", "manager_user_links")


def test_migrations_apply_and_roll_back() -> None:
    url = _test_url()
    cfg = _config(url)

    command.upgrade(cfg, "head")
    assert _extension_exists(url, "citext"), "citext should exist after upgrade"
    for table in IDENTITY_TABLES:
        assert _table_exists(url, table), f"{table} should exist after upgrade"

    command.downgrade(cfg, "base")
    assert not _extension_exists(url, "citext"), "citext should be gone after downgrade"
    for table in IDENTITY_TABLES:
        assert not _table_exists(url, table), f"{table} should be gone after downgrade"

    command.upgrade(cfg, "head")
    assert _extension_exists(url, "citext"), "citext should exist after re-apply"
    for table in IDENTITY_TABLES:
        assert _table_exists(url, table), f"{table} should exist after re-apply"
