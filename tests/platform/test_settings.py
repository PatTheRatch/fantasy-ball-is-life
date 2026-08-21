"""Settings accessors: fail loud on missing, never default silently."""

from __future__ import annotations

import pytest

from backend.platform.settings import (
    SettingsError,
    database_url,
    database_url_for_tests,
)


def test_database_url_raises_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(SettingsError, match="DATABASE_URL"):
        database_url()


def test_database_url_returns_value_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/db")
    assert database_url() == "postgresql+psycopg://u:p@localhost/db"


def test_database_url_for_tests_raises_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(SettingsError, match="TEST_DATABASE_URL"):
        database_url_for_tests()


def test_database_url_for_tests_is_distinct_from_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The test DB setting never falls back to DATABASE_URL."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost/prod")
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    with pytest.raises(SettingsError, match="TEST_DATABASE_URL"):
        database_url_for_tests()
