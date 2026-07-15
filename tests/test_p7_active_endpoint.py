"""Tests for GET /projections/active endpoint (P-7)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.projections.adapter import PlayerProjection
from backend.projections.store import ESPN_VIRTUAL_SET_ID, ProjectionStore


def _sample_rows() -> list[PlayerProjection]:
    return [PlayerProjection(player_key="test", display_name="Test", pts_pg=20.0)]


class TestActiveEndpoint:
    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as td:
            yield ProjectionStore(Path(td))

    def test_returns_active_uploaded_set(self, store):
        pset = store.save_set(_sample_rows(), source="bbm", horizon="season",
                              uploaded_at="2026-01-01T00:00:00")
        active_id = store._manifest.active.get("season")
        assert active_id == pset.set_id

        # Verify it's findable
        found = None
        for s in store.list_sets():
            if s.set_id == active_id:
                found = s
                break
        assert found is not None
        assert found.source == "bbm"

    def test_returns_virtual_espn_when_active(self, store):
        store.set_active(ESPN_VIRTUAL_SET_ID)
        active_id = store._manifest.active.get("week")
        assert active_id == ESPN_VIRTUAL_SET_ID

    def test_returns_none_when_no_active(self, store):
        active_id = store._manifest.active.get("season")
        assert active_id is None

    def test_active_after_clear_is_espn(self, store):
        store.save_set(_sample_rows(), source="bbm", horizon="week", week=5,
                       uploaded_at="2026-01-01T00:00:00")
        store.clear_horizon("week")
        active_id = store._manifest.active.get("week")
        assert active_id == ESPN_VIRTUAL_SET_ID

    def test_activate_A_after_B(self, store):
        """Upload A, upload B, activate A → active is A, not B."""
        pset_a = store.save_set(_sample_rows(), source="bbm", horizon="season",
                                uploaded_at="2026-01-01T00:00:00")
        store.save_set(_sample_rows(), source="bbm", horizon="season",
                       uploaded_at="2026-01-02T00:00:00")
        store.set_active(pset_a.set_id)
        active_id = store._manifest.active.get("season")
        assert active_id == pset_a.set_id
