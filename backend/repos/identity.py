"""Identity repositories: the scoped user repository and the bootstrap seam."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.identity import User
from backend.repos.base import UserScopedRepository


class AuthBootstrapRepository:
    """Resolves ``auth_subject → user`` during login bootstrap.

    This is the one legitimate *unscoped* read: before a user is resolved there
    is no ``user_id`` to scope on. It is narrowly named and explicitly tested so
    it reads as a declared exception to the scope rule, not a silent hole (D26).
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_by_auth_subject(self, auth_subject: str) -> User | None:
        return self.session.scalars(
            select(User).where(User.auth_subject == auth_subject)
        ).one_or_none()

    def add(self, user: User) -> None:
        self.session.add(user)


class UserRepository(UserScopedRepository):
    """Scoped access to a user's own record (``users.id == scope.user_id``)."""

    scope_column = "id"

    def get(self) -> User | None:
        return self.session.scalars(self.scoped_select(User)).one_or_none()
