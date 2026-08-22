"""Identity crosswalk models (04-provider-ingestion): provider identities,
links, and the review queue.

Charter D18 (ambiguous matches are flagged, never silently fuzzy-matched) and
D19 (durable, permanent crosswalk) land here. A provider record is a
``provider_identity``; its tie to an FCP entity is an ``identity_link``; and a
record that cannot be confidently resolved is a row in the review queue —
counted, never dropped. A wrong link is superseded, never deleted.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import enums
from backend.models.base import CreatedAtMixin, uuid7
from backend.platform.db import Base


class ProviderIdentity(Base):
    """One external entity FCP has ever seen, before any judgement about what it
    maps to. Scope: ``global`` · Freshness: ``synced``.

    ``provider_entity_id`` is nullable for sources with no stable id (e.g. a BBM
    export has names and nothing else) — exactly the case that must not be
    silently resolved.
    """

    __tablename__ = "provider_identities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("providers.id"), nullable=False
    )
    entity_kind: Mapped[str] = mapped_column(enums.provider_entity_kind, nullable=False)
    provider_entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_attributes: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )  # team, position, dob — matching evidence
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "provider_id", "entity_kind", "provider_entity_id",
            name="uq_provider_identities_provider_entity",
        ),
        CheckConstraint(
            "provider_entity_id IS NOT NULL OR raw_name IS NOT NULL",
            name="ck_provider_identities_id_or_name",
        ),
    )


class IdentityLink(CreatedAtMixin, Base):
    """A durable mapping: provider identity → FCP entity. Scope: ``global`` ·
    Freshness: ``reference``.

    Charter D19 — the permanent crosswalk. ``fcp_entity_id`` is polymorphic by
    ``fcp_entity_kind``, so one table serves players, teams and managers. A wrong
    link is *superseded* (``superseded_by_id`` / ``superseded_at``), never
    deleted — the fact that we once believed a mapping is itself history. Only
    one active (non-superseded) link per provider identity (partial unique
    index).
    """

    __tablename__ = "identity_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    provider_identity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("provider_identities.id"), nullable=False
    )
    fcp_entity_kind: Mapped[str] = mapped_column(enums.provider_entity_kind, nullable=False)
    fcp_entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    match_method: Mapped[str] = mapped_column(enums.match_method, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3, asdecimal=False), nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("identity_links.id"), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "identity_links_active_idx",
            "provider_identity_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        Index("identity_links_entity_idx", "fcp_entity_kind", "fcp_entity_id"),
    )


class IdentityReviewQueue(CreatedAtMixin, Base):
    """An unresolved provider identity awaiting human review. Scope: ``global``
    · Freshness: ``derived``.

    Charter D18: "prefer unknown over confidently wrong." A failed match is a
    row here, counted on the status page, and blocks nothing. ``candidates``
    holds the near-misses with their scores and evidence so a reviewer can judge
    without re-deriving the match.
    """

    __tablename__ = "identity_review_queue"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    # FK name abbreviated (no `_provider_identities` suffix): the full convention
    # name would exceed Postgres' 63-char identifier limit.
    provider_identity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("provider_identities.id", name="fk_identity_review_queue_provider_identity_id"),
        nullable=False,
    )
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ingestion_runs.id"), nullable=False
    )
    reason: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # empty_name|empty_pool|no_candidate|low_confidence|ambiguous|fuzzy_name
    candidates: Mapped[list[object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'")
    )  # [{fcp_entity_id, name, score}]
    status: Mapped[str] = mapped_column(
        enums.review_status, nullable=False, server_default=text("'open'")
    )
    resolved_link_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("identity_links.id"), nullable=True
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "identity_review_open_idx",
            "status",
            "created_at",
            postgresql_where=text("status = 'open'"),
        ),
    )
