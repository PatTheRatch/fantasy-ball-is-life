"""Shared model infrastructure: UUIDv7 primary keys and timestamp columns.

These land here in S1-05 with their first consumers (the identity models),
per the S1-04 decision to defer them until a real table needed them.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column


def uuid7() -> uuid.UUID:
    """Return a time-ordered UUIDv7 (RFC 9562), application-generated.

    The 48-bit millisecond timestamp sits in the high bits, so keys sort
    roughly in insertion order — index locality without exposing a row count
    (schema README §Identifiers). The random bits come from ``os.urandom``.
    """
    timestamp_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    raw = bytearray(16)
    raw[0:6] = timestamp_ms.to_bytes(6, "big")
    raw[6:16] = os.urandom(10)
    raw[6] = (raw[6] & 0x0F) | 0x70  # version 7 (0111)
    raw[8] = (raw[8] & 0x3F) | 0x80  # variant 10 (RFC 4122)
    return uuid.UUID(bytes=bytes(raw))


class CreatedAtMixin:
    """``created_at`` only, for immutable fact/reference tables.

    README §Timestamps: ``updated_at`` signals mutability, so it must be absent
    on tables that are never updated. Use :class:`TimestampMixin` for mutable
    tables, this mixin for immutable ones.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimestampMixin:
    """``created_at`` / ``updated_at``, per schema README §Timestamps.

    ``timestamptz`` only; ``created_at`` is server-defaulted, ``updated_at`` is
    bumped by the ORM on update.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class LineageMixin:
    """``ingestion_run_id`` provenance column (S1-08; charter D17).

    Records which ingestion run most recently wrote (or created) the row, so the
    provenance of any canonical fact is one join away (04-provider-ingestion
    "every canonical fact in 02 and 03 carries ``ingestion_run_id``"). Nullable:
    reference/franchise rows populated outside the pipeline (seeds, user action)
    simply leave it null.
    """

    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ingestion_runs.id"), nullable=True
    )


class ProviderLineageMixin:
    """Full lineage (README §Lineage) for pipeline-only facts.

    ``ingestion_run_id`` is NOT NULL here (unlike :class:`LineageMixin`) because
    these tables are never seed- or user-populated — every row is derived from a
    provider payload, so provenance is mandatory. ``observed_at`` records when
    the source reported the fact; ``normalizer_version`` records which parser
    produced the row (D17). The ``superseded_by_id``/``superseded_at`` self-FK is
    defined per-table (a mixin cannot reference its own table name).
    """

    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ingestion_runs.id"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    normalizer_version: Mapped[str] = mapped_column(Text, nullable=False)
