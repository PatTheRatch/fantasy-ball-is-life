"""Typed accessors for process configuration.

Settings are read lazily, at call time, never at import time. A missing
required value raises :class:`SettingsError` with the variable named in the
message — a silent default would hide a misconfigured deploy (charter D28:
failures are visible, never silent).
"""

from __future__ import annotations

import os


class SettingsError(RuntimeError):
    """A required setting is missing or empty."""


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SettingsError(f"required setting {name} is not set")
    return value


def database_url() -> str:
    """The SQLAlchemy URL for the application database (``DATABASE_URL``)."""
    return _require("DATABASE_URL")


def database_url_for_tests() -> str:
    """The SQLAlchemy URL for the test database (``TEST_DATABASE_URL``).

    Distinct from ``DATABASE_URL`` so a test run can never accidentally point
    at a development or production database. Named to avoid the ``test`` prefix
    so pytest never mistakes the accessor for a test when imported.
    """
    return _require("TEST_DATABASE_URL")


def jwt_issuer() -> str:
    """The expected ``iss`` claim on a Supabase-issued JWT."""
    return _require("SUPABASE_JWT_ISSUER")


def jwt_audience() -> str:
    """The expected ``aud`` claim on a Supabase-issued JWT."""
    return _require("SUPABASE_JWT_AUDIENCE")


def jwt_jwks_url() -> str:
    """The URL of the JWKS keyset used to verify Supabase-issued JWTs."""
    return _require("SUPABASE_JWKS_URL")
