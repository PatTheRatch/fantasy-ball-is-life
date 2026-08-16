"""
FCP Projections M-1b — tests for the Kaggle-CSV historical backfill.

Synthetic CSVs exercise every source-convention translation: end-year →
start-year seasons, USG% percentage → ratio, combined-row preference for
traded players, team pace/ORtg joins, and the synthetic negative id space.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from backend.nbadata import csv_backfill as cb
from backend.nbadata.csv_backfill import (
    backfill_from_csv,
    build_bio_rows,
    build_season_rows,
    synthetic_person_id,
    _parse_seasons,
)


# ---------------------------------------------------------------------------
# Fixture CSVs (dataset column names, end-year season convention)
# ---------------------------------------------------------------------------


def _per_game_df() -> pd.DataFrame:
    base = {
        "seas_id": 1, "lg": "NBA", "pos": "SF", "age": 39.0,
        "experience": 21, "g": 70, "gs": 70, "mp_per_game": 35.2,
        "fg_per_game": 9.6, "fga_per_game": 18.0,
        "x3p_per_game": 2.1, "x3pa_per_game": 5.0,
        "ft_per_game": 4.5, "fta_per_game": 5.7,
        "trb_per_game": 7.3, "ast_per_game": 8.3,
        "stl_per_game": 1.3, "blk_per_game": 0.6,
        "tov_per_game": 3.5, "pts_per_game": 25.7,
    }
    rows = [
        # LeBron, csv-season 2024 (= our 2023), single team
        {**base, "season": 2024, "player_id": "jamesle01",
         "player": "LeBron James", "tm": "LAL"},
        # Traded player, csv-season 2024: combined row + two stints
        {**base, "season": 2024, "player_id": "tradedg01",
         "player": "Traded Guy", "tm": "2TM", "g": 60, "pts_per_game": 20.0},
        {**base, "season": 2024, "player_id": "tradedg01",
         "player": "Traded Guy", "tm": "BOS", "g": 35, "pts_per_game": 22.0},
        {**base, "season": 2024, "player_id": "tradedg01",
         "player": "Traded Guy", "tm": "DAL", "g": 25, "pts_per_game": 17.0},
        # LeBron, csv-season 2023 (= our 2022) — for bio experience count
        {**base, "season": 2023, "player_id": "jamesle01",
         "player": "LeBron James", "tm": "LAL", "pos": "PF"},
        # Non-NBA league row must be filtered out
        {**base, "season": 2024, "player_id": "abaguy01",
         "player": "ABA Guy", "tm": "XXX", "lg": "ABA"},
    ]
    return pd.DataFrame(rows)


def _advanced_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"season": 2024, "player_id": "jamesle01", "player": "LeBron James",
         "tm": "LAL", "usg_percent": 28.5},
        # Traded guy: stint rows + combined — combined must win
        {"season": 2024, "player_id": "tradedg01", "player": "Traded Guy",
         "tm": "BOS", "usg_percent": 30.0},
        {"season": 2024, "player_id": "tradedg01", "player": "Traded Guy",
         "tm": "2TM", "usg_percent": 24.0},
        {"season": 2023, "player_id": "jamesle01", "player": "LeBron James",
         "tm": "LAL", "usg_percent": 31.0},
    ])


def _team_summaries_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"season": 2024, "abbreviation": "LAL", "pace": 101.2, "o_rtg": 116.3},
        {"season": 2024, "abbreviation": "BOS", "pace": 98.0, "o_rtg": 122.0},
        {"season": 2023, "abbreviation": "LAL", "pace": 102.0, "o_rtg": 113.0},
    ])


def _write_dataset(tmp_path) -> str:
    _per_game_df().to_csv(tmp_path / cb.PER_GAME_FILE, index=False)
    _advanced_df().to_csv(tmp_path / cb.ADVANCED_FILE, index=False)
    _team_summaries_df().to_csv(tmp_path / cb.TEAM_SUMMARIES_FILE, index=False)
    return str(tmp_path)


# ---------------------------------------------------------------------------
# build_season_rows
# ---------------------------------------------------------------------------


class TestBuildSeasonRows:
    def _rows(self, seasons=(2023,)):
        rows, errors = build_season_rows(
            _per_game_df(), _advanced_df(), _team_summaries_df(), list(seasons)
        )
        return rows, errors

    def test_end_year_converted_to_start_year(self):
        """CSV season 2024 (the 2023-24 season) lands as our season 2023."""
        rows, _ = self._rows(seasons=(2023,))
        assert rows
        assert all(r["season"] == 2023 for r in rows)
        lebron = next(r for r in rows if r["display_name"] == "LeBron James")
        assert lebron["pts"] == 25.7

    def test_usg_pct_scaled_to_ratio(self):
        """28.5 in the CSV → 0.285 stored (nba_api convention)."""
        rows, _ = self._rows()
        lebron = next(r for r in rows if r["display_name"] == "LeBron James")
        assert lebron["usg_pct"] == pytest.approx(0.285)

    def test_combined_row_wins_for_traded_player(self):
        """One row per (player, season); the 2TM combined row is kept."""
        rows, _ = self._rows()
        traded = [r for r in rows if r["display_name"] == "Traded Guy"]
        assert len(traded) == 1
        assert traded[0]["team"] == "2TM"
        assert traded[0]["gp"] == 60
        assert traded[0]["pts"] == 20.0
        # Advanced combined row (24.0) wins over the BOS stint (30.0)
        assert traded[0]["usg_pct"] == pytest.approx(0.24)

    def test_team_pace_ortg_joined(self):
        rows, _ = self._rows()
        lebron = next(r for r in rows if r["display_name"] == "LeBron James")
        assert lebron["team_pace"] == 101.2
        assert lebron["team_ortg"] == 116.3
        # Combined-team rows have no team to join — honest nulls
        traded = next(r for r in rows if r["display_name"] == "Traded Guy")
        assert traded["team_pace"] is None
        assert traded["team_ortg"] is None

    def test_non_nba_league_rows_filtered(self):
        rows, _ = self._rows()
        assert not any(r["display_name"] == "ABA Guy" for r in rows)

    def test_minutes_is_total_mpg_per_game(self):
        rows, _ = self._rows()
        lebron = next(r for r in rows if r["display_name"] == "LeBron James")
        assert lebron["mpg"] == 35.2
        assert lebron["minutes"] == pytest.approx(35.2 * 70, abs=0.1)

    def test_normalized_name_present(self):
        rows, _ = self._rows()
        lebron = next(r for r in rows if r["display_name"] == "LeBron James")
        assert lebron["normalized_name"] == "lebron james"

    def test_missing_columns_raise_with_clear_message(self):
        broken = _per_game_df().drop(columns=["pts_per_game"])
        with pytest.raises(cb.CsvSchemaError, match="pts_pg"):
            build_season_rows(broken, pd.DataFrame(), pd.DataFrame(), [2023])


# ---------------------------------------------------------------------------
# Synthetic id space
# ---------------------------------------------------------------------------


class TestSyntheticIds:
    def test_negative_and_deterministic(self):
        a = synthetic_person_id("jamesle01")
        assert a < 0
        assert a == synthetic_person_id("jamesle01")
        assert a != synthetic_person_id("curryst01")

    def test_fits_32_bit_int_column(self):
        assert -(2**31) <= synthetic_person_id("jamesle01") < 0

    def test_collision_raises_instead_of_merging(self, monkeypatch):
        monkeypatch.setattr(cb, "synthetic_person_id", lambda _: -42)
        with pytest.raises(RuntimeError, match="collision"):
            build_season_rows(
                _per_game_df(), pd.DataFrame(), pd.DataFrame(), [2023]
            )


# ---------------------------------------------------------------------------
# Bios
# ---------------------------------------------------------------------------


class TestBuildBioRows:
    def test_one_row_per_person_latest_position_and_experience(self):
        rows, _ = build_season_rows(
            _per_game_df(), _advanced_df(), _team_summaries_df(), [2022, 2023]
        )
        bios = build_bio_rows(rows)
        lebron = next(b for b in bios if b["display_name"] == "LeBron James")
        # Two seasons in range → experience 2; latest season's position (SF)
        assert lebron["experience"] == 2
        assert lebron["position"] == "SF"
        assert lebron["person_id"] == synthetic_person_id("jamesle01")


# ---------------------------------------------------------------------------
# backfill_from_csv orchestration
# ---------------------------------------------------------------------------


class TestBackfillFromCsv:
    def test_dry_run_builds_but_writes_nothing(self, tmp_path, monkeypatch):
        def _boom(*a, **k):
            raise AssertionError("dry run must not touch the store")

        monkeypatch.setattr(cb, "_upsert_player_seasons", _boom)
        monkeypatch.setattr(cb, "_upsert_player_bios", _boom)

        report = backfill_from_csv(_write_dataset(tmp_path), [2023])
        assert report.players_seen == 2  # LeBron + Traded Guy
        assert report.rows_written == 2
        assert report.seasons_processed == [2023]

    def test_upserts_in_chunks_when_configured(self, tmp_path, monkeypatch):
        season_batches: list[int] = []
        bio_batches: list[int] = []
        monkeypatch.setattr(
            cb, "_upsert_player_seasons",
            lambda rows, store, report_errors=None: season_batches.append(len(rows)) or len(rows),
        )
        monkeypatch.setattr(
            cb, "_upsert_player_bios",
            lambda rows, store, report_errors=None: bio_batches.append(len(rows)) or len(rows),
        )

        report = backfill_from_csv(
            _write_dataset(tmp_path), [2022, 2023],
            supabase_url="http://test", supabase_key="key",
        )
        assert sum(season_batches) == 3   # 2 players in 2023 + LeBron 2022
        assert sum(bio_batches) == 2      # 2 distinct players
        assert report.rows_written == 3
        assert report.bios_written == 2

    def test_missing_requested_seasons_reported(self, tmp_path):
        report = backfill_from_csv(_write_dataset(tmp_path), [1999, 2023])
        assert any("1999" in e for e in report.errors)

    def test_missing_per_game_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Kaggle"):
            backfill_from_csv(str(tmp_path), [2023])

    def test_missing_optional_files_reported_not_fatal(self, tmp_path):
        _per_game_df().to_csv(tmp_path / cb.PER_GAME_FILE, index=False)
        report = backfill_from_csv(str(tmp_path), [2023])
        assert report.players_seen == 2
        assert any(cb.ADVANCED_FILE in e for e in report.errors)
        assert any(cb.TEAM_SUMMARIES_FILE in e for e in report.errors)


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


class TestParseSeasons:
    def test_range(self):
        assert _parse_seasons("2010-2013") == [2010, 2011, 2012, 2013]

    def test_single_and_list(self):
        assert _parse_seasons("2024") == [2024]
        assert _parse_seasons("2020, 2022") == [2020, 2022]
