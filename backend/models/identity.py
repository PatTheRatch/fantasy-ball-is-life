"""Identity domain: users, managers, and the user↔manager link.

Schema: docs/v2/schema/01-identity.md. Charter Decisions 9 (co-managers) and
13 (User ≠ Manager) — a login ``User`` is not a fantasy ``Manager``; the
relationship is many-to-many and optional in both directions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import enums
from backend.models.base import CreatedAtMixin, TimestampMixin, uuid7
from backend.platform.db import Base


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    auth_subject: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(CITEXT, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )


class Manager(TimestampMixin, Base):
    __tablename__ = "managers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    # Deliberately thin — a manager is an identity, not a profile. No user_id
    # column: the relationship is many-to-many and optional in both directions.
    display_name: Mapped[str] = mapped_column(Text, nullable=False)


class ManagerUserLink(Base):
    __tablename__ = "manager_user_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    manager_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("managers.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    linked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("manager_id", "user_id", name="uq_manager_user_links_manager_user"),
        Index(
            "manager_user_links_one_primary_idx",
            "manager_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )


class FantasyTeamSeasonManager(CreatedAtMixin, Base):
    """Who managed a team in a season, including co-managers. Scope:
    ``league_season`` · Freshness: ``synced``.

    Charter D9 (co-managers) is the multiple-rows case, distinguished by
    ``role``. ``from_date``/``to_date`` handle mid-season handover; both null is
    the common case (a team owned all season). Defined in ``01-identity.md``; it
    references ``fantasy_team_seasons``, so it lands with the fantasy core.
    """

    __tablename__ = "fantasy_team_season_managers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    # FK name is abbreviated (no `_fantasy_team_seasons` referred suffix): the
    # full convention name exceeds Postgres' 63-char identifier limit, and the
    # column name already names the referred table.
    fantasy_team_season_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "fantasy_team_seasons.id",
            name="fk_fantasy_team_season_managers_fantasy_team_season_id",
        ),
        nullable=False,
    )
    manager_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("managers.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(
        enums.manager_role, nullable=False, server_default=text("'owner'")
    )
    from_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    to_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "fantasy_team_season_id", "manager_id", "from_date",
            name="uq_fantasy_team_season_managers_season_manager_from",
        ),
        Index("ftsm_manager_idx", "manager_id"),
        Index("ftsm_team_season_idx", "fantasy_team_season_id"),
    )
