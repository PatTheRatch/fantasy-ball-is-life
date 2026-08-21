"""Identity repository + service: get-or-create, citext email, scoped reads.

Postgres-backed (``TEST_DATABASE_URL``) because ``users.email`` is ``citext``.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.identity import Manager, ManagerUserLink, User
from backend.platform.auth import Principal
from backend.repos.identity import AuthBootstrapRepository, UserRepository
from backend.repos.scope import UserScope
from backend.services.identity import resolve_current_user


def test_find_by_auth_subject_returns_none_when_absent(db_session: Session) -> None:
    assert AuthBootstrapRepository(db_session).find_by_auth_subject("no-such-subject") is None


def test_resolve_creates_user_on_first_login_and_reuses(db_session: Session) -> None:
    principal = Principal(auth_subject="sub-1", email="pat@x.com")

    user = resolve_current_user(principal, AuthBootstrapRepository(db_session))
    db_session.commit()
    assert user.auth_subject == "sub-1"
    assert user.email == "pat@x.com"
    assert user.display_name == "pat@x.com"

    again = resolve_current_user(principal, AuthBootstrapRepository(db_session))
    assert again.id == user.id


def test_email_is_case_insensitive_unique(db_session: Session) -> None:
    resolve_current_user(
        Principal(auth_subject="sub-1", email="Pat@x.com"),
        AuthBootstrapRepository(db_session),
    )
    db_session.commit()

    resolve_current_user(
        Principal(auth_subject="sub-2", email="pat@X.com"),
        AuthBootstrapRepository(db_session),
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_user_repository_is_scoped_to_its_user(db_session: Session) -> None:
    user = resolve_current_user(
        Principal(auth_subject="sub-1", email="pat@x.com"),
        AuthBootstrapRepository(db_session),
    )
    db_session.commit()

    own = UserRepository(UserScope(user.id), db_session)
    assert own.get() is not None
    assert own.get().id == user.id

    other = UserRepository(UserScope(uuid.uuid4()), db_session)
    assert other.get() is None


def _manager_with_two_users(db_session: Session) -> tuple[Manager, User, User]:
    manager = Manager(display_name="Test Manager")
    user_a = User(auth_subject="sub-a", email="a@x.com", display_name="a@x.com")
    user_b = User(auth_subject="sub-b", email="b@x.com", display_name="b@x.com")
    db_session.add_all([manager, user_a, user_b])
    db_session.flush()
    return manager, user_a, user_b


def test_manager_link_allows_only_one_primary(db_session: Session) -> None:
    manager, user_a, user_b = _manager_with_two_users(db_session)

    db_session.add(
        ManagerUserLink(manager_id=manager.id, user_id=user_a.id, is_primary=True)
    )
    db_session.add(
        ManagerUserLink(manager_id=manager.id, user_id=user_b.id, is_primary=True)
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_manager_link_allows_multiple_non_primary(db_session: Session) -> None:
    manager, user_a, user_b = _manager_with_two_users(db_session)

    db_session.add(
        ManagerUserLink(manager_id=manager.id, user_id=user_a.id, is_primary=True)
    )
    db_session.add(
        ManagerUserLink(manager_id=manager.id, user_id=user_b.id, is_primary=False)
    )

    db_session.flush()  # one primary + one co-manager is fine — the index is partial
