"""Identity domain: users, managers, and the user↔manager link.

Schema: docs/v2/schema/01-identity.md. Charter Decisions 9 (co-managers) and
13 (User ≠ Manager) — a login ``User`` is not a fantasy ``Manager``; the
relationship is many-to-many and optional in both directions.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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

from backend.models.base import TimestampMixin, uuid7
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
