"""Ingestion service: run lifecycle and content hashing (hermetic).

No database — the service is driven with fake repositories and real model
instances so the orchestration logic (hash determinism, run state transitions,
``partial`` as a first-class outcome) is tested without Postgres. Persistence is
covered by the migration round-trip test.
"""

from __future__ import annotations

import uuid
from unittest.mock import Mock

import pytest

from backend.models.ingestion import IngestionRun, Provider
from backend.services.ingestion import (
    NORMALIZER_VERSION,
    IngestionError,
    IngestionService,
    content_hash,
)

PROVIDER_ID = uuid.uuid4()
RUN_ID = uuid.uuid4()


def _provider() -> Provider:
    return Provider(id=PROVIDER_ID, key="espn", name="ESPN", kind="fantasy_platform")


def _run() -> IngestionRun:
    return IngestionRun(
        id=RUN_ID, provider_id=PROVIDER_ID, kind="league_settings",
        normalizer_version=NORMALIZER_VERSION,
    )


def _service(providers=None, runs=None, payloads=None) -> IngestionService:
    return IngestionService(
        providers or Mock(), runs or Mock(), payloads or Mock()
    )


# --- content_hash -----------------------------------------------------------


def test_content_hash_is_deterministic() -> None:
    payload = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}}
    assert content_hash(payload) == content_hash(payload)


def test_content_hash_is_key_order_independent() -> None:
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


def test_content_hash_differs_for_different_payloads() -> None:
    assert content_hash({"a": 1}) != content_hash({"a": 2})


# --- start_run --------------------------------------------------------------


def test_start_run_resolves_provider_and_records_version() -> None:
    providers = Mock()
    providers.get_by_key.return_value = _provider()
    runs = Mock()
    service = _service(providers=providers, runs=runs)

    run = service.start_run("espn", "league_settings")

    assert run.provider_id == PROVIDER_ID
    assert run.kind == "league_settings"
    assert run.normalizer_version == NORMALIZER_VERSION
    runs.add.assert_called_once_with(run)


def test_start_run_unknown_provider_raises() -> None:
    providers = Mock()
    providers.get_by_key.return_value = None
    service = _service(providers=providers)

    with pytest.raises(IngestionError, match="unknown provider key"):
        service.start_run("nonexistent", "league_settings")


# --- record_payload ---------------------------------------------------------


def test_record_payload_hashes_and_attributes_to_run() -> None:
    payloads = Mock()
    service = _service(payloads=payloads)
    run = _run()

    raw = service.record_payload(run, "league", {"name": "Patriot Games"})

    assert raw.ingestion_run_id == RUN_ID
    assert raw.provider_id == PROVIDER_ID
    assert raw.endpoint == "league"
    assert raw.content_hash == content_hash({"name": "Patriot Games"})
    assert raw.payload == {"name": "Patriot Games"}
    payloads.add.assert_called_once_with(raw)


# --- finish_run -------------------------------------------------------------


def test_finish_run_partial_is_first_class() -> None:
    service = _service()
    run = _run()

    service.finish_run(run, "partial", stats={"rows": 3})

    assert run.status == "partial"
    assert run.finished_at is not None
    assert run.stats == {"rows": 3}


def test_finish_run_rejects_invalid_status() -> None:
    service = _service()

    with pytest.raises(ValueError, match="invalid run status"):
        service.finish_run(_run(), "bogus")
