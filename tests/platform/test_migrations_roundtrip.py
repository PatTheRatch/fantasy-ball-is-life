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

from backend.domain.categories import NINE_CAT

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


def _enum_exists(url: str, name: str) -> bool:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT 1 FROM pg_type WHERE typname = :name AND typtype = 'e'"),
                {"name": name},
            )
            return result.scalar() is not None
    finally:
        engine.dispose()


def _category_keys(url: str) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT key FROM categories"))
            return {row[0] for row in result}
    finally:
        engine.dispose()


IDENTITY_TABLES = ("users", "managers", "manager_user_links")
FANTASY_TABLES = (
    "leagues",
    "league_seasons",
    "categories",
    "league_season_categories",
    "fantasy_teams",
    "fantasy_team_seasons",
    "matchup_periods",
    "fantasy_team_season_managers",
)
NBA_TABLES = ("nba_seasons",)
ENUM_TYPES = (
    "provider_key",
    "league_season_status",
    "category_kind",
    "period_type",
    "period_status",
    "manager_role",
)


def test_migrations_apply_and_roll_back() -> None:
    url = _test_url()
    cfg = _config(url)
    all_tables = IDENTITY_TABLES + FANTASY_TABLES + NBA_TABLES
    expected_keys = {c.key for c in NINE_CAT}

    command.upgrade(cfg, "head")
    assert _extension_exists(url, "citext"), "citext should exist after upgrade"
    for table in all_tables:
        assert _table_exists(url, table), f"{table} should exist after upgrade"
    for enum in ENUM_TYPES:
        assert _enum_exists(url, enum), f"{enum} type should exist after upgrade"
    assert _category_keys(url) == expected_keys, "nine standard categories should be seeded"

    command.downgrade(cfg, "base")
    assert not _extension_exists(url, "citext"), "citext should be gone after downgrade"
    for table in all_tables:
        assert not _table_exists(url, table), f"{table} should be gone after downgrade"
    for enum in ENUM_TYPES:
        assert not _enum_exists(url, enum), f"{enum} type should be gone after downgrade"

    command.upgrade(cfg, "head")
    assert _extension_exists(url, "citext"), "citext should exist after re-apply"
    for table in all_tables:
        assert _table_exists(url, table), f"{table} should exist after re-apply"
    for enum in ENUM_TYPES:
        assert _enum_exists(url, enum), f"{enum} type should exist after re-apply"
    assert _category_keys(url) == expected_keys, "categories should be re-seeded on re-apply"
