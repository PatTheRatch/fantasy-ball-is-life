"""Local JWT verification against a cached JWKS keyset.

Verifies a Supabase-issued JWT entirely in-process: signature, ``iss``,
``aud``, ``exp`` and ``sub``. The keyset is passed in (loaded once by the
caller), so verification never performs a network round trip — the reason we
don't use ``PyJWKClient``, which fetches per call.

Failures are typed (charter D28): ``ExpiredToken``, ``UnknownKey``, and
``InvalidToken`` for everything else — never a silent ``None``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt import PyJWTError
from jwt.algorithms import RSAAlgorithm
from jwt.exceptions import ExpiredSignatureError

#: A keyset indexed by ``kid`` for O(1) lookup during verification.
JwksKeyset = dict[str, dict[str, Any]]


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

    try:
        key = RSAAlgorithm.from_jwk(jwk)
    except PyJWTError as exc:
        raise InvalidToken("unusable signing key") from exc

    # A public JWK yields a public key; the union includes the private-key case
    # only for JWKs that carry a private component, which a keyset never does.
    public_key = cast("RSAPublicKey", key)

    try:
        claims = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
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
