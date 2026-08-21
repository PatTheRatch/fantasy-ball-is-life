"""Helpers for signing and verifying JWTs with a locally-generated keypair.

No network and no shared secrets: each test mints its own RSA keypair, builds
a JWK from the public key, and signs tokens with the private key.
"""

from __future__ import annotations

import base64
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

DEFAULT_ISSUER = "https://test.supabase.co/auth/v1"
DEFAULT_AUDIENCE = "authenticated"


def generate_rsa_keypair() -> tuple[RSAPrivateKey, RSAPublicKey]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def public_jwk(public_key: RSAPublicKey, kid: str) -> dict[str, str]:
    numbers = public_key.public_numbers()
    n = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
    e = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
    return {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _b64url(n),
        "e": _b64url(e),
    }


def keyset(public_key: RSAPublicKey, kid: str) -> dict[str, dict[str, str]]:
    return {kid: public_jwk(public_key, kid)}


def sign_token(
    private_key: RSAPrivateKey,
    *,
    kid: str,
    sub: str,
    email: str | None = None,
    issuer: str = DEFAULT_ISSUER,
    audience: str = DEFAULT_AUDIENCE,
    expires_in: int = 300,
    extra_claims: dict[str, object] | None = None,
) -> str:
    """Sign a Supabase-style JWT. ``expires_in`` is seconds from now."""
    claims: dict[str, object] = {
        "sub": sub,
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + expires_in,
    }
    if email is not None:
        claims["email"] = email
    if extra_claims:
        claims.update(extra_claims)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})
