"""Shared model infrastructure: UUIDv7 primary keys and timestamp columns.

These land here in S1-05 with their first consumers (the identity models),
per the S1-04 decision to defer them until a real table needed them.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
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
