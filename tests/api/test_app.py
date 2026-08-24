"""``create_app`` wiring: the production path loads JWKS + session from env,
and the no-config path stays network-free for the route-policy matrix test."""

from __future__ import annotations

import pytest

from backend.api import app as app_module
from backend.api.app import JwksFetchError, create_app
from backend.platform.settings import SettingsError
from tests.api.jwt_helpers import (
    DEFAULT_AUDIENCE,
    DEFAULT_ISSUER,
    generate_rsa_keypair,
    public_jwk,
)


def test_create_app_without_env_builds_no_config() -> None:
    """The matrix test's precondition: no environment, no database, no network."""
    app = create_app(load_from_env=False)

    assert app.state.jwks_keyset is None
    assert app.state.session_factory is None


def test_create_app_loads_keyset_and_session_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bare ``create_app()`` wires both pieces from the environment."""
    _, public = generate_rsa_keypair()
    document = {"keys": [public_jwk(public, "k1")]}
    monkeypatch.setattr(app_module, "_fetch_jwks", lambda url: document)
    monkeypatch.setenv(
        "SUPABASE_JWKS_URL",
        "https://fake.supabase.co/auth/v1/.well-known/jwks.json",
    )
    monkeypatch.setenv("SUPABASE_JWT_ISSUER", DEFAULT_ISSUER)
    monkeypatch.setenv("SUPABASE_JWT_AUDIENCE", DEFAULT_AUDIENCE)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://fcp:fcp@localhost:5432/fcp")

    app = create_app()

    assert app.state.jwks_keyset is not None
    assert "k1" in app.state.jwks_keyset
    assert app.state.session_factory is not None


def test_create_app_raises_on_missing_setting() -> None:
    """A missing setting fails at construction, not on the first request.

    ``conftest`` scrubs ``SUPABASE_JWKS_URL``, so bare ``create_app()`` must
    raise rather than return an app that 500s every authenticated route.
    """
    with pytest.raises(SettingsError):
        create_app()


def test_create_app_raises_on_failing_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A JWKS fetch failure fails at construction (fail fast, no silent app)."""

    def _boom(url: str) -> dict[str, object]:
        raise JwksFetchError("network down")

    monkeypatch.setattr(app_module, "_fetch_jwks", _boom)
    monkeypatch.setenv("SUPABASE_JWKS_URL", "https://fake.supabase.co/jwks.json")

    with pytest.raises(JwksFetchError):
        create_app()
