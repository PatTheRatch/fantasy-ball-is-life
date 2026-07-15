"""Unit tests for P-2 — BbmAdapter + ProjectionStore.

Covers:
- BbmAdapter detect() / parse() against gold season + weekly fixtures
- ProjectionStore save/load/manifest round-trip
- Registry store-first fallback
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import pytest

from backend.projections.adapter import PlayerProjection, ProjectionAdapter
from backend.projections.bbm_adapter import BbmAdapter, _SEASON_SIGNATURE, _WEEKLY_SIGNATURE
from backend.projections.registry import get_active_projections
from backend.projections.store import ProjectionSet, ProjectionStore


# ---------------------------------------------------------------------------
# Gold fixture: mini BBM season sheet
# ---------------------------------------------------------------------------

def _season_fixture_df() -> pd.DataFrame:
    """Minimal BBM season-export shape (bare columns + LeagV)."""
    return pd.DataFrame({
        "Name": ["LeBron James", "Stephen Curry", "Nikola Jokic"],
        "Team": ["LAL", "GSW", "DEN"],
        "p":   ["25.3", "27.1", "24.5"],
        "3":   ["2.1",  "4.8",  "1.0"],
        "r":   ["7.0",  "4.5",  "11.8"],
        "a":   ["8.1",  "5.2",  "9.0"],
        "s":   ["1.2",  "1.3",  "1.4"],
        "b":   ["0.6",  "0.2",  "0.7"],
        "fga":  ["20.0", "19.0", "16.0"],
        "fta":  ["5.0",  "4.0",  "6.0"],
        "to":   ["3.0",  "2.5",  "3.2"],
        "fg%":  [".500", ".450", ".560"],
        "ft%":  [".750", ".920", ".820"],
        "LeagV": ["1.20", "1.10", "1.50"],
        "Inj":   ["", "", ""],
    })


def _weekly_fixture_df() -> pd.DataFrame:
    """Minimal BBM weekly-export shape (/g-suffixed columns + g)."""
    return pd.DataFrame({
        "Name": ["LeBron James", "Stephen Curry"],
        "Team": ["LAL", "GSW"],
        "p/g":   ["28.0", "30.0"],
        "3/g":   ["2.5",  "5.0"],
        "r/g":   ["8.0",  "5.0"],
        "a/g":   ["9.0",  "6.0"],
        "s/g":   ["1.0",  "1.5"],
        "b/g":   ["0.5",  "0.1"],
        "fga/g": ["22.0", "20.0"],
        "fta/g": ["6.0",  "5.0"],
        "to/g":  ["3.5",  "2.0"],
        "fg%":   [".480", ".440"],
        "ft%":   [".780", ".910"],
        "g":     ["4", "4"],
        "$":     ["28", "32"],
    })


# ---------------------------------------------------------------------------
# BbmAdapter — protocol
# ---------------------------------------------------------------------------

class TestBbmAdapterProtocol:
    def test_is_projectable(self):
        a = BbmAdapter()
        assert isinstance(a, ProjectionAdapter)

    def test_source_id(self):
        assert BbmAdapter.source_id == "bbm"

    def test_supported_horizons(self):
        assert BbmAdapter.supported_horizons == ["season", "week"]


# ---------------------------------------------------------------------------
# BbmAdapter — detect
# ---------------------------------------------------------------------------

class TestBbmAdapterDetect:
    def test_season_fixture_detected(self):
        a = BbmAdapter()
        conf = a.detect(raw_df=_season_fixture_df())
        assert conf == 0.95

    def test_weekly_fixture_detected(self):
        a = BbmAdapter()
        conf = a.detect(raw_df=_weekly_fixture_df())
        assert conf == 0.95

    def test_unknown_format_returns_zero(self):
        a = BbmAdapter()
        df = pd.DataFrame({"foo": [1], "bar": [2]})
        assert a.detect(raw_df=df) == 0.0


# ---------------------------------------------------------------------------
# BbmAdapter — parse (season)
# ---------------------------------------------------------------------------

class TestBbmAdapterParseSeason:
    def test_parse_season_output_shape(self):
        a = BbmAdapter()
        rows = a.parse(raw_df=_season_fixture_df())
        assert len(rows) == 3

    def test_lebron_stats_exact(self):
        a = BbmAdapter()
        rows = a.parse(raw_df=_season_fixture_df())
        lbj = rows[0]
        assert lbj.display_name == "LeBron James"
        assert lbj.pts_pg == 25.3
        assert lbj.tpm_pg == 2.1
        assert lbj.reb_pg == 7.0
        assert lbj.ast_pg == 8.1
        assert lbj.stl_pg == 1.2
        assert lbj.blk_pg == 0.6
        assert lbj.fga_pg == 20.0
        assert lbj.fta_pg == 5.0
        assert lbj.to_pg == 3.0
        assert lbj.value == 1.20
        # FG% / FT% stored as ratios
        assert lbj.fg_pct == 0.50
        assert lbj.ft_pct == 0.75

    def test_season_no_games_column(self):
        """Season fixture has no 'g' column → games is None."""
        a = BbmAdapter()
        rows = a.parse(raw_df=_season_fixture_df())
        assert rows[0].games is None

    def test_player_key_uses_canonical_normalizer(self):
        a = BbmAdapter()
        rows = a.parse(raw_df=_season_fixture_df())
        assert rows[0].player_key == "lebron james"


# ---------------------------------------------------------------------------
# BbmAdapter — parse (weekly)
# ---------------------------------------------------------------------------

class TestBbmAdapterParseWeekly:
    def test_parse_weekly_output_shape(self):
        a = BbmAdapter()
        rows = a.parse(raw_df=_weekly_fixture_df())
        assert len(rows) == 2

    def test_weekly_has_games(self):
        a = BbmAdapter()
        rows = a.parse(raw_df=_weekly_fixture_df())
        assert rows[0].games == 4.0

    def test_weekly_value_from_dollar(self):
        a = BbmAdapter()
        rows = a.parse(raw_df=_weekly_fixture_df())
        assert rows[0].value == 28.0


# ---------------------------------------------------------------------------
# BbmAdapter — empty / missing columns
# ---------------------------------------------------------------------------

class TestBbmAdapterEdgeCases:
    def test_empty_names_skipped(self):
        a = BbmAdapter()
        df = pd.DataFrame({"Name": ["", None, "  "], "p/g": ["10", "20", "30"]})
        rows = a.parse(raw_df=df)
        assert len(rows) == 0

    def test_no_name_column_treats_as_empty(self):
        a = BbmAdapter()
        df = pd.DataFrame({"p/g": ["10"]})
        rows = a.parse(raw_df=df)
        assert len(rows) == 0

    def test_missing_stats_default_to_zero(self):
        a = BbmAdapter()
        df = pd.DataFrame({"Name": ["Test"], "p/g": [""]})
        rows = a.parse(raw_df=df)
        assert rows[0].pts_pg == 0.0


# ---------------------------------------------------------------------------
# ProjectionStore — save/load/manifest
# ---------------------------------------------------------------------------

class TestProjectionStore:
    @pytest.fixture
    def store(self):
        with tempfile.TemporaryDirectory() as td:
            yield ProjectionStore(Path(td))

    @pytest.fixture
    def sample_rows(self):
        return [
            PlayerProjection(
                player_key="lebron james", display_name="LeBron James",
                team="LAL", positions=["SF", "PF"], games=4.0,
                pts_pg=25.0, reb_pg=7.0, ast_pg=8.0, stl_pg=1.2,
                blk_pg=0.6, tpm_pg=2.0, to_pg=3.0,
                fga_pg=20.0, fta_pg=5.0, fg_pct=0.5, ft_pct=0.75,
            )
        ]

    # ---- save / load round-trip ----

    def test_save_and_load_round_trip(self, store, sample_rows):
        pset = store.save_set(sample_rows, source="bbm", horizon="season", uploaded_at="2026-01-01T00:00:00")
        loaded = store.load_set(pset.set_id)
        assert loaded is not None
        assert len(loaded) == 1
        assert loaded[0].player_key == "lebron james"
        assert loaded[0].pts_pg == 25.0
        assert loaded[0].positions == ["SF", "PF"]

    def test_load_nonexistent_set_returns_none(self, store):
        assert store.load_set("nonexistent") is None

    # ---- manifest ----

    def test_save_set_adds_to_manifest(self, store, sample_rows):
        store.save_set(sample_rows, source="bbm", horizon="season", uploaded_at="2026-01-01T00:00:00")
        sets = store.list_sets(source="bbm")
        assert len(sets) == 1
        assert sets[0].source == "bbm"
        assert sets[0].horizon == "season"

    def test_list_sets_filtered(self, store, sample_rows):
        store.save_set(sample_rows, source="bbm", horizon="season", uploaded_at="2026-01-01T00:00:00")
        store.save_set(sample_rows, source="bbm", horizon="week", uploaded_at="2026-01-02T00:00:00")
        assert len(store.list_sets(horizon="season")) == 1
        assert len(store.list_sets(source="bbm")) == 2

    # ---- active ----

    def test_latest_upload_is_active(self, store, sample_rows):
        pset = store.save_set(sample_rows, source="bbm", horizon="season", uploaded_at="2026-01-01T00:00:00")
        active = store.load_active("season")
        assert active is not None
        assert active[0].player_key == sample_rows[0].player_key

    def test_set_active_switches(self, store, sample_rows):
        pset1 = store.save_set(sample_rows, source="bbm", horizon="season", uploaded_at="2026-01-01T00:00:00")
        pset2 = store.save_set(sample_rows, source="bbm", horizon="season", uploaded_at="2026-01-02T00:00:00")
        # pset2 is active (latest). Switch back to pset1.
        assert store.set_active(pset1.set_id)
        # load_active should now return pset1's parquet
        active = store.load_active("season")
        assert active is not None

    def test_set_active_nonexistent_returns_false(self, store):
        assert not store.set_active("nonexistent")

    # ---- atomic write (no partial files) ----

    def test_tmp_file_not_left_behind(self, store, sample_rows):
        store.save_set(sample_rows, source="bbm", horizon="season", uploaded_at="2026-01-01T00:00:00")
        tmps = list(store.dir.glob("*.tmp"))
        assert len(tmps) == 0

    # ---- round-trip with empty positions ----

    def test_empty_positions_round_trip(self, store):
        rows = [
            PlayerProjection(player_key="test", display_name="Test", positions=[])
        ]
        pset = store.save_set(rows, source="bbm", horizon="season", uploaded_at="2026-01-01T00:00:00")
        loaded = store.load_set(pset.set_id)
        assert loaded is not None
        assert loaded[0].positions == []


# ---------------------------------------------------------------------------
# Registry — store first, then fallback
# ---------------------------------------------------------------------------

class TestRegistryP2:
    def test_season_returns_empty_without_upload(self):
        """Without any uploaded BBM, season still returns []."""
        result = get_active_projections("season")
        assert result == []

    def test_bogus_horizon_returns_empty(self):
        assert get_active_projections("bogus") == []
