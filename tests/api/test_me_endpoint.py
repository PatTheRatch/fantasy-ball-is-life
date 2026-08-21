"""`GET /api/v1/me` end-to-end: signed token → verify → get-or-create → DTO.

Postgres-backed (``TEST_DATABASE_URL``) because user resolution hits the
``users`` table.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from backend.api.app import create_app
from tests.api.jwt_helpers import (
    DEFAULT_AUDIENCE,
    DEFAULT_ISSUER,
    generate_rsa_keypair,
    keyset,
    sign_token,
)

KID = "k1"


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    migrated_session_factory: sessionmaker[Session],
) -> Iterator[tuple[TestClient, RSAPrivateKey]]:
    monkeypatch.setenv("SUPABASE_JWT_ISSUER", DEFAULT_ISSUER)
    monkeypatch.setenv("SUPABASE_JWT_AUDIENCE", DEFAULT_AUDIENCE)
    private, public = generate_rsa_keypair()
    app = create_app(keyset=keyset(public, KID), session_factory=migrated_session_factory)
    with TestClient(app) as test_client:
        yield test_client, private


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_me_returns_user_for_valid_token(client: tuple[TestClient, RSAPrivateKey]) -> None:
    test_client, private = client
    token = sign_token(private, kid=KID, sub="sub-123", email="pat@x.com")

    resp = test_client.get("/api/v1/me", headers=_auth(token))

    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "pat@x.com"
    assert body["display_name"] == "pat@x.com"
    assert body["id"]


def test_me_is_stable_across_calls(client: tuple[TestClient, RSAPrivateKey]) -> None:
    test_client, private = client
    token = sign_token(private, kid=KID, sub="sub-456", email="new@x.com")

    first = test_client.get("/api/v1/me", headers=_auth(token))
    second = test_client.get("/api/v1/me", headers=_auth(token))

    assert first.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_me_returns_401_for_missing_token(client: tuple[TestClient, RSAPrivateKey]) -> None:
    test_client, _ = client
    assert test_client.get("/api/v1/me").status_code == 401


def test_me_returns_401_for_invalid_token(client: tuple[TestClient, RSAPrivateKey]) -> None:
    test_client, private = client
    token = sign_token(private, kid=KID, sub="sub-1", audience="wrong-audience")
    assert test_client.get("/api/v1/me", headers=_auth(token)).status_code == 401
