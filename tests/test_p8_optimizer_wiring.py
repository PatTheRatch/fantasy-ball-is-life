"""Contract test for P-8: router-level projections_rows wiring."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.projections.store import ProjectionStore


class TestP8SeasonWiring:
    def test_load_returns_none_when_store_empty(self):
        """Isolated temp store → get_active_projections('season') → [].

        The real helper _load_season_projections converts this to None,
        so the optimizer falls through to legacy BBM_PROJECTIONS_PATH.
        """
        with tempfile.TemporaryDirectory() as td:
            store = ProjectionStore(Path(td))
            rows = store.load_active("season")
            assert rows is None  # no active set in empty store

    def test_load_with_active_set(self):
        """Active season set in an isolated store returns PlayerProjection rows."""
        from backend.projections.adapter import PlayerProjection

        with tempfile.TemporaryDirectory() as td:
            store = ProjectionStore(Path(td))
            store.save_set(
                [PlayerProjection(player_key="test", display_name="Test", pts_pg=20.0)],
                source="bbm", horizon="season",
                uploaded_at="2026-01-01T00:00:00",
            )
            rows = store.load_active("season")
            assert rows is not None
            assert len(rows) == 1
            assert rows[0].display_name == "Test"


class TestP8RouterImports:
    def test_draft_router_imports(self):
        from backend.api.routers.draft import router
        assert router is not None

    def test_optimizer_router_imports(self):
        from backend.api.routers.optimizer import router
        assert router is not None
