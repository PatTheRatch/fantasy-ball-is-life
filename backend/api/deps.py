"""FastAPI dependencies: auth, DB session, and the resolved current user."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.platform.auth import AuthError, ExpiredToken, Principal, verify_token
from backend.platform.settings import jwt_audience, jwt_issuer
from backend.repos.identity import AuthBootstrapRepository
from backend.services.identity import resolve_current_user


class UserDTO(BaseModel):
    """The authenticated user as returned by the identity endpoints."""

    id: uuid.UUID
    email: str
    display_name: str


def bearer_token(authorization: str | None = Header(default=None)) -> str:
    if authorization is None:
        raise HTTPException(status_code=401, detail="missing authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="malformed authorization header")
    return token


def current_principal(
    request: Request,
    token: str = Depends(bearer_token),
) -> Principal:
    """Verify the bearer token against the app's cached JWKS keyset."""
    keyset = request.app.state.jwks_keyset
    try:
        return verify_token(token, keyset, issuer=jwt_issuer(), audience=jwt_audience())
    except ExpiredToken as exc:
        raise HTTPException(status_code=401, detail="token expired") from exc
    except AuthError as exc:
        raise HTTPException(status_code=401, detail="invalid token") from exc


def get_db(request: Request) -> Iterator[Session]:
    """Yield a request-scoped session, committing on success and rolling back
    on error."""
    factory = request.app.state.session_factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_current_user(
    principal: Principal = Depends(current_principal),
    session: Session = Depends(get_db),
) -> UserDTO:
    """Resolve the authenticated principal to a user (get-or-create) and return
    its DTO. The business logic lives in ``services.identity``."""
    bootstrap = AuthBootstrapRepository(session)
    user = resolve_current_user(principal, bootstrap)
    # A newly-created user's UUIDv7 id is materialized on flush (the ``uuid7``
    # default is Python-side); flush so the DTO carries a real id.
    session.flush()
    return UserDTO(id=user.id, email=user.email, display_name=user.display_name)
