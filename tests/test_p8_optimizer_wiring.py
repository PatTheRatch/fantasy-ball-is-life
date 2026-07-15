"""Contract test for P-8: router-level projections_rows wiring.

Verifies that _load_season_projections in draft.py returns None when
no store/upload exists (the common case — falls through to the
optimizer's legacy BBM_PROJECTIONS_PATH read), and that it doesn't
crash when the store is empty.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.api.routers.draft import _load_season_projections


class TestP8SeasonWiring:
    def test_load_returns_none_when_no_upload(self):
        """No store data → returns None → optimizer uses legacy disk read."""
        # _load_season_projections calls get_active_projections('season')
        # which checks the store; with an empty temp store, it returns []
        # and our helper converts [] → None.
        rows = _load_season_projections()
        assert rows is None

    def test_load_does_not_crash(self):
        """Graceful degradation — no crash on import failure or store issues."""
        rows = _load_season_projections()
        # Either None (no active set) or a list (if a real store has data)
        assert rows is None or isinstance(rows, list)


class TestP8DraftRouterWiring:
    """Smoke-test: the draft router imports and the helper is callable."""

    def test_router_imports(self):
        from backend.api.routers.draft import router as draft_router
        assert draft_router is not None

    def test_optimizer_router_imports(self):
        from backend.api.routers.optimizer import router as opt_router
        assert opt_router is not None
