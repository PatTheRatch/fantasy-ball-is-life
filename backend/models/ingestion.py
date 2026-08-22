"""Ingestion models: providers, connections, runs, and raw evidence.

Schema: ``docs/v2/schema/04-provider-ingestion.md``. These make charter §6
("replay beats patching") and D16 (raw retention) real: the pipeline persists
raw payloads *before* interpreting them, and every run records which normalizer
version produced the canonical rows, so a mapping bug is fixed by shipping a new
version and re-running over the stored payloads — never by refetching.

Each class docstring states its scope + freshness (README §Scope / §Freshness).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import enums
from backend.models.base import CreatedAtMixin, TimestampMixin, uuid7
from backend.platform.db import Base


class Provider(CreatedAtMixin, Base):
    """A data source. Scope: ``global`` · Freshness: ``reference``.

    Yahoo/Sleeper are rows from day one even though no adapter exists (charter
    D5) — the multi-provider intent is visible in the data, not aspirational.
    """

    __tablename__ = "providers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(enums.provider_key, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # fantasy_platform|stats|projections|manual — manual sources have no platform
    # character, so "manual" is a fourth honest kind, not a bug.
    kind: Mapped[str] = mapped_column(Text, nullable=False)


class ProviderConnection(TimestampMixin, Base):
    """Credentials/connection to one provider for one league. Scope: ``league``
    (platform connections) · Freshness: ``reference``.

    Separate from ``league_seasons`` so one connection can serve several seasons
    and credential ownership is distinct from league identity. ``status`` and
    ``last_error`` are stored, not logged (D28) — "cookies expired" is a fact the
    owner should see, not a stack trace.
    """

    __tablename__ = "provider_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("providers.id"), nullable=False
    )
    league_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leagues.id"), nullable=True
    )
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # Envelope-encrypted application-side; the key never leaves the app. Both are
    # nullable: encryption is wired in a later slice, not a S1-08 concern.
    credentials_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    credentials_key_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'unverified'")
    )  # unverified|ok|invalid|expired
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class IngestionRun(CreatedAtMixin, Base):
    """One pipeline run. Scope: ``global`` · Freshness: ``event``.

    ``status = 'partial'`` is a first-class outcome (D28): a run that got
    matchups but not transactions says so, rather than succeeding quietly with
    half the data. ``replayed_from_run_id`` records that this run reinterpreted a
    previous run's stored payloads rather than fetching fresh.
    """

    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("providers.id"), nullable=False
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("provider_connections.id"), nullable=True
    )
    league_season_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("league_seasons.id"), nullable=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # league_settings|matchups|...
    normalizer_version: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        enums.run_status, nullable=False, server_default=text("'running'")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )  # rows read/written/superseded/queued
    replayed_from_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ingestion_runs.id"), nullable=True
    )

    __table_args__ = (
        Index(
            "ingestion_runs_league_kind_idx",
            "league_season_id",
            "kind",
            text("started_at DESC"),
        ),
    )


class RawPayload(CreatedAtMixin, Base):
    """One immutable raw provider payload. Scope: ``global`` · Freshness: ``event``.

    Charter D16. ``content_hash`` is a sha256 over the canonical JSON — the basis
    for change detection (an unchanged payload skips normalization) and for
    replay (a mapping bug is fixed by re-running over these, no refetch).
    ``payload`` is stored inline by default; ``storage_ref`` is nullable from day
    one so large payloads can move to object storage without a schema change.
    """

    __tablename__ = "raw_payloads"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("ingestion_runs.id"), nullable=False
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("providers.id"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    request_params: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'")
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, object] | None] = mapped_column(JSONB, nullable=True)
    storage_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "payload IS NOT NULL OR storage_ref IS NOT NULL",
            name="ck_raw_payloads_payload_or_storage",
        ),
        Index("raw_payloads_run_idx", "ingestion_run_id"),
        Index("raw_payloads_hash_idx", "provider_id", "endpoint", "content_hash"),
    )
