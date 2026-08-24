"""Helpers for signing and verifying JWTs with a locally-generated keypair.

No network and no shared secrets: each test mints its own RSA keypair, builds
a JWK from the public key, and signs tokens with the private key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
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


def generate_ec_keypair() -> tuple[ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey]:
    """A fresh P-256 keypair (the curve Supabase signs ES256 tokens with)."""
    private = ec.generate_private_key(ec.SECP256R1())
    return private, private.public_key()


def ec_public_jwk(public_key: ec.EllipticCurvePublicKey, kid: str) -> dict[str, str]:
    numbers = public_key.public_numbers()
    return {
        "kty": "EC",
        "kid": kid,
        "use": "sig",
        "alg": "ES256",
        "crv": "P-256",
        "x": _b64url(numbers.x.to_bytes(32, "big")),
        "y": _b64url(numbers.y.to_bytes(32, "big")),
    }


def ec_keyset(public_key: ec.EllipticCurvePublicKey, kid: str) -> dict[str, dict[str, str]]:
    return {kid: ec_public_jwk(public_key, kid)}


def sign_es256_token(
    private_key: ec.EllipticCurvePrivateKey,
    *,
    kid: str,
    sub: str,
    email: str | None = None,
    issuer: str = DEFAULT_ISSUER,
    audience: str = DEFAULT_AUDIENCE,
    expires_in: int = 300,
) -> str:
    """Sign a Supabase-style ES256 JWT with a P-256 private key."""
    claims: dict[str, object] = {
        "sub": sub,
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + expires_in,
    }
    if email is not None:
        claims["email"] = email
    return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": kid})


def sign_hs256_with_public_key(
    public_key: RSAPublicKey,
    *,
    kid: str,
    sub: str,
    issuer: str = DEFAULT_ISSUER,
    audience: str = DEFAULT_AUDIENCE,
    expires_in: int = 300,
) -> str:
    """The algorithm-confusion attack, encoded as a token.

    Signs an HS256 token using the RSA *public* key's bytes as the HMAC secret,
    and stamps the header ``alg: HS256``. Crafted by hand rather than through
    ``jwt.encode``, because PyJWT itself refuses to use an asymmetric key as an
    HMAC secret — a real attacker has no such guardrail. A verifier that
    derives the algorithm from the trusted keyset (which says ``RS256``) must
    reject this; a verifier that trusts the header's ``alg`` would be vulnerable.
    """
    header = {"alg": "HS256", "kid": kid, "typ": "JWT"}
    claims = {
        "sub": sub,
        "iss": issuer,
        "aud": audience,
        "exp": int(time.time()) + expires_in,
    }
    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode())
    claims_b64 = _b64url(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header_b64}.{claims_b64}"

    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    signature = hmac.new(public_pem, signing_input.encode("ascii"), hashlib.sha256).digest()

    return f"{signing_input}.{_b64url(signature)}"
