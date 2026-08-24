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
    ec_keyset,
    generate_ec_keypair,
    generate_rsa_keypair,
    keyset,
    sign_es256_token,
    sign_hs256_with_public_key,
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


def test_es256_token_verifies() -> None:
    """The actual defect: Supabase signs ES256 (P-256), so it must verify."""
    private, public = generate_ec_keypair()
    token = sign_es256_token(private, kid="k1", sub="sub-123", email="pat@x.com")

    principal = verify_token(
        token, ec_keyset(public, "k1"), issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
    )

    assert principal == Principal(auth_subject="sub-123", email="pat@x.com")


def test_algorithm_confusion_is_rejected() -> None:
    """A forged ``alg: HS256`` header, signed with the public key as the HMAC
    secret, must be rejected. The verifier derives RS256 from the trusted JWK,
    never from the token header."""
    _, public = generate_rsa_keypair()
    token = sign_hs256_with_public_key(public, kid="k1", sub="sub-123")

    with pytest.raises(InvalidToken):
        verify_token(
            token, keyset(public, "k1"), issuer=DEFAULT_ISSUER, audience=DEFAULT_AUDIENCE
        )


def test_unsupported_kty_raises_invalid_token() -> None:
    """An unknown key type is a typed InvalidToken, not a library crash."""
    private, _ = generate_rsa_keypair()
    token = sign_token(private, kid="k1", sub="sub-123")

    with pytest.raises(InvalidToken):
        verify_token(
            token,
            {"k1": {"kty": "OKP", "kid": "k1"}},
            issuer=DEFAULT_ISSUER,
            audience=DEFAULT_AUDIENCE,
        )


def test_jwk_declaring_hs256_is_rejected() -> None:
    """The allowlist is {RS256, ES256} — a keyset entry claiming HS256 fails."""
    private, _ = generate_rsa_keypair()
    token = sign_token(private, kid="k1", sub="sub-123")

    with pytest.raises(InvalidToken):
        verify_token(
            token,
            {"k1": {"kty": "RSA", "kid": "k1", "alg": "HS256"}},
            issuer=DEFAULT_ISSUER,
            audience=DEFAULT_AUDIENCE,
        )
