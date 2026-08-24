"""Local JWT verification against a cached JWKS keyset.

Verifies a Supabase-issued JWT entirely in-process: signature, ``iss``,
``aud``, ``exp`` and ``sub``. The keyset is passed in (loaded once by the
caller), so verification never performs a network round trip — the reason we
don't use ``PyJWKClient``, which fetches per call.

Both Supabase signing key types are supported: ``RS256`` (RSA) and ``ES256``
(P-256). The signature algorithm is derived from the *trusted JWK*, never from
the token header — an attacker who sets ``alg: HS256`` and signs with the
public key as an HMAC secret is rejected because the header is not consulted
for the algorithm.

Failures are typed (charter D28): ``ExpiredToken``, ``UnknownKey``, and
``InvalidToken`` for everything else — never a silent ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWTError
from jwt.algorithms import ECAlgorithm, RSAAlgorithm
from jwt.exceptions import ExpiredSignatureError

#: A keyset indexed by ``kid`` for O(1) lookup during verification.
JwksKeyset = dict[str, dict[str, Any]]

#: The only signature algorithms the verifier will accept. Derived from the
#: trusted JWK, never from the token header. ``HS256`` and ``none`` are
#: deliberately absent — they are the algorithm-confusion vector.
ALLOWED_ALGORITHMS = frozenset({"RS256", "ES256"})


@dataclass(frozen=True)
class Principal:
    """The authenticated subject extracted from a verified token."""

    auth_subject: str
    email: str | None


class AuthError(Exception):
    """Base class for all token verification failures."""


class InvalidToken(AuthError):
    """Token is malformed, wrongly signed, or fails ``iss``/``aud`` checks."""


class ExpiredToken(AuthError):
    """The token's ``exp`` claim has passed."""


class UnknownKey(AuthError):
    """The token's ``kid`` is absent from the configured keyset."""


def index_keyset(jwks: dict[str, Any]) -> JwksKeyset:
    """Convert a raw JWKS document (``{"keys": [...]}``) to a kid-indexed map."""
    return {key["kid"]: key for key in jwks.get("keys", [])}


def _algorithm_for(jwk: dict[str, Any]) -> str:
    """Return the one permitted signature algorithm for a trusted JWK.

    The algorithm is derived from the JWK alone — its ``alg`` if present,
    otherwise its key type — and validated against the allowlist. It is never
    read from the token header, which is untrusted input (the classic
    algorithm-confusion attack: a forged ``alg: HS256`` header, signed with the
    public key as the HMAC secret).
    """
    alg = jwk.get("alg")
    if alg is not None:
        if not isinstance(alg, str) or alg not in ALLOWED_ALGORITHMS:
            raise InvalidToken(f"unsupported alg {alg!r}")
        return alg
    kty = jwk.get("kty")
    if kty == "RSA":
        return "RS256"
    if kty == "EC":
        return "ES256"
    raise InvalidToken(f"unsupported kty {kty!r}")


def verify_token(
    token: str,
    keyset: JwksKeyset,
    *,
    issuer: str,
    audience: str,
) -> Principal:
    """Verify ``token`` against ``keyset`` and return the authenticated subject."""
    try:
        header = jwt.get_unverified_header(token)
    except PyJWTError as exc:
        raise InvalidToken("malformed token header") from exc

    kid = header.get("kid")
    jwk = keyset.get(kid) if isinstance(kid, str) else None
    if jwk is None:
        raise UnknownKey(f"no key for kid={kid!r}")

    # The permitted algorithm is derived from the trusted JWK, never the token
    # header. Passed as a single-element list so PyJWT rejects any header whose
    # ``alg`` does not match the key's algorithm.
    algorithm = _algorithm_for(jwk)

    try:
        # A public JWK yields a public key; the union includes the private-key
        # case only for JWKs that carry a private component, which a keyset
        # never does. ``Any`` stands in for "RSAPublicKey | EllipticCurvePublicKey".
        key: Any = (
            RSAAlgorithm.from_jwk(jwk)
            if algorithm == "RS256"
            else ECAlgorithm.from_jwk(jwk)
        )
    except PyJWTError as exc:
        raise InvalidToken("unusable signing key") from exc

    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            issuer=issuer,
            audience=audience,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except ExpiredSignatureError as exc:
        raise ExpiredToken("token has expired") from exc
    except PyJWTError as exc:
        raise InvalidToken(str(exc)) from exc

    auth_subject = claims.get("sub")
    if not isinstance(auth_subject, str):
        raise InvalidToken("missing sub claim")

    email = claims.get("email")
    return Principal(auth_subject=auth_subject, email=email if isinstance(email, str) else None)
