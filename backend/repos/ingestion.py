"""Ingestion repositories: providers, runs, raw payloads (all ``global`` scope).

Global-scoped, so these are plain session repositories — no tenancy filter, same
as the ``AuthBootstrapRepository`` seam in S1-05. The pipeline reads/writes them
directly; every consumer-level query goes through the run or payload ledger.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.ingestion import IngestionRun, Provider, RawPayload


class ProviderRepository:
    """Look up the ``providers`` reference table."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_key(self, key: str) -> Provider | None:
        return self.session.scalars(select(Provider).where(Provider.key == key)).one_or_none()

    def add(self, provider: Provider) -> None:
        self.session.add(provider)


class IngestionRunRepository:
    """The run ledger."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, run_id: uuid.UUID) -> IngestionRun | None:
        return self.session.get(IngestionRun, run_id)

    def add(self, run: IngestionRun) -> None:
        self.session.add(run)


class RawPayloadRepository:
    """Immutable raw evidence, keyed for change detection and dedupe."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, payload: RawPayload) -> None:
        self.session.add(payload)

    def latest_for(self, provider_id: uuid.UUID, endpoint: str) -> RawPayload | None:
        """The most recently fetched payload for ``(provider_id, endpoint)``."""
        return self.session.scalars(
            select(RawPayload)
            .where(RawPayload.provider_id == provider_id, RawPayload.endpoint == endpoint)
            .order_by(RawPayload.fetched_at.desc())
        ).first()

    def find_by_hash(
        self, provider_id: uuid.UUID, endpoint: str, content_hash: str
    ) -> RawPayload | None:
        """An existing payload with the same content hash (change detection).

        Backed by ``raw_payloads_hash_idx`` — this is the query that lets an
        unchanged payload skip normalization entirely (D16).
        """
        return self.session.scalars(
            select(RawPayload).where(
                RawPayload.provider_id == provider_id,
                RawPayload.endpoint == endpoint,
                RawPayload.content_hash == content_hash,
            )
        ).first()
