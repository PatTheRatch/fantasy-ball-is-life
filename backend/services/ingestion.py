"""Ingestion service: the run lifecycle and raw-payload persistence.

This is the "persist before interpret" spine (charter §6): a run is opened, raw
payloads are captured and stored with a content hash *before* any interpretation,
and the run is then closed as ``succeeded``, ``partial`` or ``failed`` (D28 —
partial is a first-class outcome, not a silent success). Normalization (raw →
canonical rows) is the *next* stage and consumes these stored payloads.

The service is the orchestration; the mapping/upsert logic for each entity type
lands with the sync slice (S1-10). ``NORMALIZER_VERSION`` is the version string
recorded on every run so a mapping bug is fixed by shipping a new version and
re-running over stored payloads, never by refetching.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime

from backend.models.ingestion import IngestionRun, RawPayload
from backend.repos.ingestion import (
    IngestionRunRepository,
    ProviderRepository,
    RawPayloadRepository,
)

#: Bump whenever the raw→canonical mapping changes; every run records it (D17).
NORMALIZER_VERSION = "1.0.0"

RUN_SUCCEEDED = "succeeded"
RUN_PARTIAL = "partial"
RUN_FAILED = "failed"


class IngestionError(Exception):
    """The run could not be started (unknown provider, missing dependency)."""


def content_hash(payload: dict[str, object]) -> str:
    """sha256 hex digest of the canonical JSON — the dedupe/change-detection key.

    Keys are sorted and separators fixed so the hash is independent of dict key
    order and JSON whitespace: two equal payloads always hash equal.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IngestionService:
    """Orchestrates one pipeline run: start → record raw → finish."""

    def __init__(
        self,
        providers: ProviderRepository,
        runs: IngestionRunRepository,
        payloads: RawPayloadRepository,
    ) -> None:
        self.providers = providers
        self.runs = runs
        self.payloads = payloads

    def start_run(
        self,
        provider_key: str,
        kind: str,
        connection_id: uuid.UUID | None = None,
        league_season_id: uuid.UUID | None = None,
        replayed_from_run_id: uuid.UUID | None = None,
    ) -> IngestionRun:
        """Open a run in ``running`` state, resolving the provider by key."""
        provider = self.providers.get_by_key(provider_key)
        if provider is None:
            raise IngestionError(f"unknown provider key: {provider_key!r}")

        run = IngestionRun(
            provider_id=provider.id,
            connection_id=connection_id,
            league_season_id=league_season_id,
            kind=kind,
            normalizer_version=NORMALIZER_VERSION,
            replayed_from_run_id=replayed_from_run_id,
        )
        self.runs.add(run)
        return run

    def record_payload(
        self,
        run: IngestionRun,
        endpoint: str,
        payload: dict[str, object],
        request_params: dict[str, object] | None = None,
        http_status: int | None = None,
        fetched_at: datetime | None = None,
    ) -> RawPayload:
        """Store one raw payload, hashing it for change detection (D16).

        ``payload`` is stored inline (``storage_ref`` stays null until object
        storage is warranted); the hash is computed here, never supplied, so it
        cannot drift from the bytes it identifies.
        """
        raw = RawPayload(
            ingestion_run_id=run.id,
            provider_id=run.provider_id,
            endpoint=endpoint,
            request_params=request_params or {},
            fetched_at=fetched_at or datetime.now(UTC),
            http_status=http_status,
            content_hash=content_hash(payload),
            payload=payload,
        )
        self.payloads.add(raw)
        return raw

    def finish_run(
        self,
        run: IngestionRun,
        status: str,
        stats: dict[str, object] | None = None,
        error: str | None = None,
    ) -> IngestionRun:
        """Close a run as ``succeeded``, ``partial`` or ``failed`` (D28)."""
        if status not in (RUN_SUCCEEDED, RUN_PARTIAL, RUN_FAILED):
            raise ValueError(f"invalid run status: {status!r}")
        run.status = status
        run.finished_at = datetime.now(UTC)
        run.stats = stats or {}
        run.error = error
        return run
