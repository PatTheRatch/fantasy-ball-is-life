"""JWT verification: valid, expired, wrong-audience, unknown-kid, wrong-key."""

from __future__ import annotations

import pytest

from backend.platform.auth import (
    ExpiredToken,
    InvalidToken,
    Principal,
    UnknownKey,
    verify_token,
)
from tests.api.jwt_helpers import (
    DEFAULT_AUDIENCE,
    DEFAULT_ISSUER,
    generate_rsa_keypair,
    keyset,
    sign_token,
)


def test_verify_valid_token_returns_principal() -> None:
    private, public = generate_rsa_keypair()
    token = sign_token(private, kid="k1", sub="sub-123", email="pat@x.com")

    principal = verify_token(
        token, keyset(public, "k1"), issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )

    assert principal == Principal(auth_subject="sub-123", email="pat@x.com")


def test_expired_token_raises_typed_error() -> None:
    private, public = generate_rsa_keypair()
    token = sign_token(private, kid="k1", sub="sub-123", expires_in=-60)

    with pytest.raises(ExpiredToken):
        verify_token(token, keyset(public, "k1"), issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE)


def test_wrong_audience_raises_typed_error() -> None:
    private, public = generate_rsa_keypair()
    token = sign_token(private, kid="k1", sub="sub-123", audience="wrong-audience")

    with pytest.raises(InvalidToken):
        verify_token(token, keyset(public, "k1"), issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE)


def test_wrong_issuer_raises_typed_error() -> None:
    private, public = generate_rsa_keypair()
    token = sign_token(private, kid="k1", sub="sub-123", issuer="https://evil.example/auth/v1")

    with pytest.raises(InvalidToken):
        verify_token(token, keyset(public, "k1"), issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE)


def test_unknown_kid_raises_typed_error() -> None:
    private, public = generate_rsa_keypair()
    token = sign_token(private, kid="k1", sub="sub-123")

    with pytest.raises(UnknownKey):
        verify_token(
            token,
            keyset(public, "other-kid"),
            issuer=DEFAULT_ISSUER,
            audience=DEFAULT_AUDIENCE,
        )


def test_token_signed_with_wrong_key_raises_typed_error() -> None:
    private, _ = generate_rsa_keypair()
    _, other_public = generate_rsa_keypair()
    token = sign_token(private, kid="k1", sub="sub-123")

    with pytest.raises(InvalidToken):
        verify_token(
            token,
            keyset(other_public, "k1"),
            issuer=DEFAULT_ISSUER,
            audience=DEFAULT_AUDIENCE,
        )
