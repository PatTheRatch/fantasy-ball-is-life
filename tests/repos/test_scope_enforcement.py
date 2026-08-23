"""Scope enforcement: scoped repositories cannot be built without a scope, and
their queries auto-filter to the scope (cross-tenant reads return nothing).

Uses throwaway models on a shared base so the scoped base is proven
generically, without touching the identity tables (whose ``citext`` email
would require Postgres).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Uuid, create_engine
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

from backend.models.base import uuid7
from backend.platform.db import Base
from backend.repos.base import (
    LeagueScopedRepository,
    LeagueSeasonScopedRepository,
    UserScopedRepository,
)
from backend.repos.matchups import LeagueSeasonRepository, MatchupRepository
from backend.repos.scope import LeagueScope, LeagueSeasonScope, UserScope


class ScopedUserRow(Base):
    __tablename__ = "test_user_scoped_rows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class ScopedLeagueRow(Base):
    __tablename__ = "test_league_scoped_rows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    league_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


class ScopedSeasonRow(Base):
    __tablename__ = "test_season_scoped_rows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    league_season_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(
        engine,
        tables=[
            ScopedUserRow.__table__,
            ScopedLeagueRow.__table__,
            ScopedSeasonRow.__table__,
        ],
    )
    with Session(engine) as s:
        yield s


def test_user_scoped_repo_requires_scope(session: Session) -> None:
    with pytest.raises(TypeError):
        UserScopedRepository(session=session)  # type: ignore[call-arg]


def test_league_scoped_repo_requires_scope(session: Session) -> None:
    with pytest.raises(TypeError):
        LeagueScopedRepository(session=session)  # type: ignore[call-arg]


def test_user_scoped_select_filters_to_scope(session: Session) -> None:
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    session.add_all([ScopedUserRow(user_id=user_a), ScopedUserRow(user_id=user_b)])
    session.commit()

    repo = UserScopedRepository(UserScope(user_a), session)
    rows = session.scalars(repo.scoped_select(ScopedUserRow)).all()

    assert [r.user_id for r in rows] == [user_a]


def test_league_scoped_select_filters_to_scope(session: Session) -> None:
    league_a, league_b = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [ScopedLeagueRow(league_id=league_a), ScopedLeagueRow(league_id=league_b)]
    )
    session.commit()

    repo = LeagueScopedRepository(LeagueScope(league_a), session)
    rows = session.scalars(repo.scoped_select(ScopedLeagueRow)).all()

    assert [r.league_id for r in rows] == [league_a]


def test_cross_tenant_read_returns_nothing(session: Session) -> None:
    session.add(ScopedUserRow(user_id=uuid.uuid4()))
    session.commit()

    repo = UserScopedRepository(UserScope(uuid.uuid4()), session)
    rows = session.scalars(repo.scoped_select(ScopedUserRow)).all()

    assert rows == []


def test_league_season_scoped_repo_requires_scope(session: Session) -> None:
    with pytest.raises(TypeError):
        LeagueSeasonScopedRepository(session=session)  # type: ignore[call-arg]


def test_league_season_scoped_select_filters_to_scope(session: Session) -> None:
    season_a, season_b = uuid.uuid4(), uuid.uuid4()
    session.add_all(
        [
            ScopedSeasonRow(league_season_id=season_a),
            ScopedSeasonRow(league_season_id=season_b),
        ]
    )
    session.commit()

    repo = LeagueSeasonScopedRepository(LeagueSeasonScope(season_a), session)
    rows = session.scalars(repo.scoped_select(ScopedSeasonRow)).all()

    assert [r.league_season_id for r in rows] == [season_a]


def test_league_season_scoped_cross_tenant_returns_nothing(session: Session) -> None:
    session.add(ScopedSeasonRow(league_season_id=uuid.uuid4()))
    session.commit()

    repo = LeagueSeasonScopedRepository(LeagueSeasonScope(uuid.uuid4()), session)
    rows = session.scalars(repo.scoped_select(ScopedSeasonRow)).all()

    assert rows == []


def test_real_league_repos_require_scope(session: Session) -> None:
    # charter D26: the structural assertion that is the point of this bite —
    # a league repository cannot be constructed without a scope.
    with pytest.raises(TypeError):
        LeagueSeasonRepository(session=session)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        MatchupRepository(session=session)  # type: ignore[call-arg]
