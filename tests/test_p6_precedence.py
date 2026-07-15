"""Tests for P-6: week-scoping, virtual ESPN, explicit-request precedence."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.projections.adapter import PlayerProjection
from backend.projections.store import (
    ESPN_VIRTUAL_SET_ID,
    ProjectionSet,
    ProjectionStore,
)


def _sample_rows(name: str = "Test Player") -> list[PlayerProjection]:
    return [
        PlayerProjection(
            player_key="test player", display_name=name,
            pts_pg=20.0, reb_pg=10.0, ast_pg=5.0,
        )
    ]


# ---------------------------------------------------------------------------
# Week-scoping
# ---------------------------------------------------------------------------

class TestWeekScoping:
    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as td:
            yield ProjectionStore(Path(td))

    def test_active_set_honored_when_week_matches(self, store):
        store.save_set(_sample_rows(), source="bbm", horizon="week", week=5,
                       uploaded_at="2026-01-01T00:00:00")
        rows = store.load_active("week", current_week=5)
        assert rows is not None
        assert rows[0].display_name == "Test Player"

    def test_active_set_ignored_when_week_mismatches(self, store):
        store.save_set(_sample_rows(), source="bbm", horizon="week", week=5,
                       uploaded_at="2026-01-01T00:00:00")
        # Week 5 set, but caller asks for week 6 → should fall through
        rows = store.load_active("week", current_week=6)
        assert rows is None

    def test_active_set_requires_current_week(self, store):
        store.save_set(_sample_rows(), source="bbm", horizon="week", week=5,
                       uploaded_at="2026-01-01T00:00:00")
        # No current_week provided → skipped, falls through to ESPN
        rows = store.load_active("week")
        assert rows is None

    def test_week_defaults_to_none_in_save(self, store):
        pset = store.save_set(_sample_rows(), source="bbm", horizon="season",
                              uploaded_at="2026-01-01T00:00:00")
        assert pset.week is None

    def test_week_field_round_trips(self, store):
        store.save_set(_sample_rows(), source="bbm", horizon="week", week=3,
                       uploaded_at="2026-01-01T00:00:00")
        sets = store.list_sets(source="bbm", horizon="week")
        assert len(sets) == 1
        assert sets[0].week == 3


# ---------------------------------------------------------------------------
# Virtual ESPN
# ---------------------------------------------------------------------------

class TestVirtualEspn:
    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as td:
            yield ProjectionStore(Path(td))

    def test_espn_set_id_is_sentinel(self):
        assert ESPN_VIRTUAL_SET_ID == "espn-live"

    def test_load_espn_set_returns_none(self, store):
        """Registry handles None by calling EspnAdapter live."""
        assert store.load_set(ESPN_VIRTUAL_SET_ID) is None
        assert store.load_active("week", current_week=5) is None  # no active yet

    def test_activate_espn_virtual_set(self, store):
        assert store.set_active(ESPN_VIRTUAL_SET_ID)
        # load_active with ESPN sentinel returns None (registry calls EspnAdapter)
        rows = store.load_active("week")
        assert rows is None

    def test_espn_in_list_sets(self, store):
        sets = store.list_sets()
        espn_sets = [s for s in sets if s.set_id == ESPN_VIRTUAL_SET_ID]
        assert len(espn_sets) >= 1
        assert espn_sets[0].source == "espn"

    def test_espn_filtered_by_horizon(self, store):
        sets = store.list_sets(horizon="week")
        espn_sets = [s for s in sets if s.set_id == ESPN_VIRTUAL_SET_ID]
        assert len(espn_sets) >= 1

    def test_espn_not_in_season_sets(self, store):
        sets = store.list_sets(horizon="season")
        espn_sets = [s for s in sets if s.set_id == ESPN_VIRTUAL_SET_ID]
        assert len(espn_sets) == 0


# ---------------------------------------------------------------------------
# Clear affordance
# ---------------------------------------------------------------------------

class TestClearHorizon:
    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as td:
            yield ProjectionStore(Path(td))

    def test_clear_week_sets_to_espn(self, store):
        # Upload a BBM set for week 5
        store.save_set(_sample_rows(), source="bbm", horizon="week", week=5,
                       uploaded_at="2026-01-01T00:00:00")
        # It's active (week matches)
        rows = store.load_active("week", current_week=5)
        assert rows is not None

        # Clear → reverts to ESPN
        store.clear_horizon("week")
        rows = store.load_active("week", current_week=5)
        assert rows is None  # None → registry calls EspnAdapter

    def test_clear_season_removes_active(self, store):
        store.save_set(_sample_rows(), source="bbm", horizon="season",
                       uploaded_at="2026-01-01T00:00:00")
        assert store.load_active("season") is not None
        store.clear_horizon("season")
        assert store.load_active("season") is None


# ---------------------------------------------------------------------------
# Week-scoped set_active + fallthrough
# ---------------------------------------------------------------------------

class TestActiveSwitch:
    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as td:
            yield ProjectionStore(Path(td))

    def test_switch_between_weeks(self, store):
        # Upload week 5 set
        pset5 = store.save_set(_sample_rows("Week5"), source="bbm", horizon="week",
                               week=5, uploaded_at="2026-01-01T00:00:00")
        # Switch to ESPN
        assert store.set_active(ESPN_VIRTUAL_SET_ID)
        rows = store.load_active("week", current_week=5)
        assert rows is None  # ESPN → None

        # Switch back to week 5 set
        assert store.set_active(pset5.set_id)
        rows = store.load_active("week", current_week=5)
        assert rows is not None
        assert rows[0].display_name == "Week5"


# ---------------------------------------------------------------------------
# Regression: existing store tests still work with new week field
# ---------------------------------------------------------------------------

class TestP6StoreRegression:
    """Existing P-2 store tests adapted for P-6 fields."""

    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as td:
            yield ProjectionStore(Path(td))

    def test_save_and_load_round_trip(self, store):
        pset = store.save_set(_sample_rows(), source="bbm", horizon="season",
                              uploaded_at="2026-01-01T00:00:00")
        loaded = store.load_set(pset.set_id)
        assert loaded is not None
        assert loaded[0].display_name == "Test Player"

    def test_list_sets_filtered(self, store):
        store.save_set(_sample_rows(), source="bbm", horizon="season",
                       uploaded_at="2026-01-01T00:00:00")
        store.save_set(_sample_rows(), source="bbm", horizon="week", week=4,
                       uploaded_at="2026-01-02T00:00:00")
        assert len(store.list_sets(horizon="season")) == 1
        # P-6: week list should include the virtual ESPN + the uploaded set
        week_sets = store.list_sets(horizon="week")
        assert len(week_sets) == 2  # virtual ESPN + uploaded

    def test_latest_upload_is_active(self, store):
        pset = store.save_set(_sample_rows(), source="bbm", horizon="season",
                              uploaded_at="2026-01-01T00:00:00")
        active = store.load_active("season")
        assert active is not None
