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
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from backend.models.ingestion import IngestionRun, RawPayload
from backend.repos.ingestion import (
    IngestionRunRepository,
    ProviderRepository,
    RawPayloadRepository,
)

#: Bump whenever the raw→canonical mapping changes; every run records it (D17).
NORMALIZER_VERSION = "1.0.0"

RUN_RUNNING = "running"
RUN_SUCCEEDED = "succeeded"
RUN_PARTIAL = "partial"
RUN_FAILED = "failed"

#: Bound on the ``ingestion_runs.error`` message — keep it a message, not a
#: traceback (D28: the reason is a fact the owner should see).
_ERROR_MAX_LEN = 1000


class IngestionError(Exception):
    """The run could not be started (unknown provider, missing dependency)."""


def content_hash(payload: dict[str, object]) -> str:
    """sha256 hex digest of the canonical JSON — the dedupe/change-detection key.

    Keys are sorted and separators fixed so the hash is independent of dict key
    order and JSON whitespace: two equal payloads always hash equal.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _format_error(exc: Exception) -> str:
    """A bounded, human-readable error for ``ingestion_runs.error`` (D28)."""
    return f"{type(exc).__name__}: {exc}"[:_ERROR_MAX_LEN]


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

    @contextmanager
    def run_scope(
        self,
        provider_key: str,
        kind: str,
        *,
        connection_id: uuid.UUID | None = None,
        league_season_id: uuid.UUID | None = None,
        replayed_from_run_id: uuid.UUID | None = None,
    ) -> Iterator[IngestionRun]:
        """Open a run and guarantee it reaches a terminal status on exit.

        charter D28: job outcomes are queryable data, not log lines. On entry
        the run is committed as ``running`` so it is durable immediately — this
        is what lets the ``failed`` write survive the rollback on the exception
        path, and what makes an in-flight run queryable while it works. On
        normal exit the run is committed with whatever terminal status the body
        set via :meth:`finish_run` (defaulting to ``succeeded`` if the body set
        none). On an exception the partial work is rolled back, the run is
        stamped ``failed`` with the error and committed, and the original
        exception is re-raised unchanged.
        """
        run = self.start_run(
            provider_key,
            kind,
            connection_id=connection_id,
            league_season_id=league_season_id,
            replayed_from_run_id=replayed_from_run_id,
        )
        # The column's ``running`` is a server_default (fires only on INSERT);
        # set it in memory too so the backstop check below is reliable.
        run.status = RUN_RUNNING
        self.runs.commit()

        try:
            yield run
        except Exception as exc:
            # Roll back the half-written work *and* clear any aborted
            # transaction, so the failed write below cannot itself raise
            # PendingRollbackError and mask the real error.
            self.runs.rollback()
            failed_run = self.runs.get(run.id)
            if failed_run is not None:
                self.finish_run(failed_run, RUN_FAILED, error=_format_error(exc))
                self.runs.commit()
            raise

        if run.status == RUN_RUNNING:
            self.finish_run(run, RUN_SUCCEEDED)
        self.runs.commit()

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
