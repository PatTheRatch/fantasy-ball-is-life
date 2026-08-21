"""Scoped repository bases.

The scope is a *required* constructor argument (no default), so constructing a
scoped repository without one is a ``TypeError`` — tenancy is structural, not a
convention (charter D26). Every read goes through :meth:`scoped_select`, which
applies the scope's key column; there is no unscoped query path on these bases.
"""

from __future__ import annotations

from typing import Any, ClassVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from backend.platform.db import Base
from backend.repos.scope import LeagueScope, UserScope


class UserScopedRepository:
    """Base for repositories over user-scoped data."""

    #: The model column carrying the user key (e.g. ``user_id``, or ``id`` on
    #: the ``users`` table itself). Subclasses override where needed.
    scope_column: ClassVar[str] = "user_id"

    def __init__(self, scope: UserScope, session: Session) -> None:
        self.scope = scope
        self.session = session

    def scoped_select(self, model: type[Base]) -> Select[Any]:
        """A ``SELECT`` pre-filtered to the scope's user key."""
        column = getattr(model, self.scope_column)
        return select(model).where(column == self.scope.user_id)


class LeagueScopedRepository:
    """Base for repositories over league-scoped data.

    Delivered structurally in S1-05 (no league-scoped table exists yet); its
    first real table lands in S1-06.
    """

    scope_column: ClassVar[str] = "league_id"

    def __init__(self, scope: LeagueScope, session: Session) -> None:
        self.scope = scope
        self.session = session

    def scoped_select(self, model: type[Base]) -> Select[Any]:
        """A ``SELECT`` pre-filtered to the scope's league key."""
        column = getattr(model, self.scope_column)
        return select(model).where(column == self.scope.league_id)
