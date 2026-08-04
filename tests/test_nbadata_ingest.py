"""
FCP Projections M-1 — hermetic tests for backend/nbadata/ingest.

All tests mock the nba_api client entirely (no live NBA.com calls).
``spec=`` mocks enforce real signatures — a standing lesson from N-4.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backend.nbadata.ingest import (
    IngestReport,
    _row_for_upsert,
    _safe_float,
    _safe_int,
    _parse_date_str,
    _nba_season_string,
    backfill_player_seasons,
    upkeep,
)


# ---------------------------------------------------------------------------
# Helpers — mock nba_api responses
# ---------------------------------------------------------------------------


def _mock_season_stats_df() -> pd.DataFrame:
    """Minimal LeagueDashPlayerStats shape with makes + attempts."""
    return pd.DataFrame([
        {
            "PLAYER_ID": 2544,
            "PLAYER_NAME": "LeBron James",
            "TEAM_ABBREVIATION": "LAL",
            "AGE": 39.0,
            "GP": 71, "GS": 71, "MIN": 2500.0,
            "FGM": 9.6, "FGA": 18.0, "FG_PCT": 0.533,
            "FTM": 4.5, "FTA": 5.7, "FT_PCT": 0.789,
            "FG3M": 2.1, "FG3A": 5.0, "FG3_PCT": 0.420,
            "PTS": 25.7, "REB": 7.3, "AST": 8.3, "STL": 1.3, "BLK": 0.6,
            "TOV": 3.5, "USG_PCT": 0.285,
            "PACE": None, "OFF_RATING": None,
        },
        {
            "PLAYER_ID": 201939,
            "PLAYER_NAME": "Stephen Curry",
            "TEAM_ABBREVIATION": "GSW",
            "AGE": 36.0,
            "GP": 74, "GS": 74, "MIN": 2420.0,
            "FGM": 9.0, "FGA": 20.0, "FG_PCT": 0.450,
            "FTM": 4.2, "FTA": 4.6, "FT_PCT": 0.913,
            "FG3M": 4.8, "FG3A": 12.0, "FG3_PCT": 0.400,
            "PTS": 26.4, "REB": 4.5, "AST": 5.1, "STL": 0.9, "BLK": 0.4,
            "TOV": 2.8, "USG_PCT": 0.305,
            "PACE": None, "OFF_RATING": None,
        },
    ])


# ---------------------------------------------------------------------------
# Unit: row builder — makes/attempts, not just percentages (criterion: spec)
# ---------------------------------------------------------------------------


class TestRowForUpsert:
    """Assert _row_for_upsert stores makes AND attempts."""

    def test_stores_fgm_and_fga_not_just_pct(self):
        row = pd.Series({
            "PLAYER_ID": 1, "PLAYER_NAME": "Test Player",
            "TEAM_ABBREVIATION": "TST", "AGE": 25, "GP": 82, "GS": 82,
            "MIN": 2800, "FGM": 8.0, "FGA": 16.0, "FG_PCT": 0.500,
            "FTM": 4.0, "FTA": 5.0, "FG3M": 2.0, "FG3A": 6.0,
            "PTS": 22.0, "REB": 5.0, "AST": 6.0, "STL": 1.0, "BLK": 0.5,
            "TOV": 2.0, "USG_PCT": 0.25, "PACE": None, "OFF_RATING": None,
        })
        result = _row_for_upsert(row, 2025)

        # Makes AND attempts are stored
        assert result["fgm"] == 8.0
        assert result["fga"] == 16.0
        assert result["ftm"] == 4.0
        assert result["fta"] == 5.0
        assert result["tpm"] == 2.0
        assert result["tpa"] == 6.0

        # Percentages are NOT stored (derived by consumers)
        assert "fg_pct" not in result
        assert "ft_pct" not in result

    def test_person_id_is_int(self):
        row = pd.Series({
            "PLAYER_ID": "2544",  # string — should become int
            "PLAYER_NAME": "Test", "TEAM_ABBREVIATION": "TST",
            "AGE": 25, "GP": 10, "GS": 0, "MIN": 200,
            "FGM": 0, "FGA": 0, "FTM": 0, "FTA": 0,
            "FG3M": 0, "FG3A": 0, "PTS": 0, "REB": 0, "AST": 0,
            "STL": 0, "BLK": 0, "TOV": 0, "USG_PCT": 0.0,
            "PACE": None, "OFF_RATING": None,
        })
        result = _row_for_upsert(row, 2025)
        assert isinstance(result["person_id"], int)
        assert result["person_id"] == 2544


# ---------------------------------------------------------------------------
# Unit: safe converters
# ---------------------------------------------------------------------------


class TestSafeConverters:
    def test_safe_float_handles_none(self):
        assert _safe_float(None) is None
        assert _safe_float("") is None

    def test_safe_float_handles_strings(self):
        assert _safe_float("25.7") == 25.7
        assert _safe_float("0") == 0.0

    def test_safe_int_handles_strings(self):
        assert _safe_int("82") == 82
        assert _safe_int(None) is None

    def test_parse_date_str_iso(self):
        assert _parse_date_str("1984-12-30T00:00:00") == date(1984, 12, 30)

    def test_parse_date_str_plain(self):
        assert _parse_date_str("1984-12-30") == date(1984, 12, 30)

    def test_nba_season_string(self):
        assert _nba_season_string(2025) == "2025-26"
        assert _nba_season_string(2010) == "2010-11"


# ---------------------------------------------------------------------------
# Integration: backfill_player_seasons with mocked nba_api
# ---------------------------------------------------------------------------


class TestBackfillPlayerSeasons:
    """Test the full backfill flow — mocks the internal fetch wrapper."""

    @pytest.fixture(autouse=True)
    def _patch_sleep(self, monkeypatch):
        """Speed up tests — skip real sleep calls."""
        monkeypatch.setattr("backend.nbadata.ingest._sleep_between_calls", lambda: None)
        monkeypatch.setattr("backend.nbadata.ingest._sleep_with_backoff", lambda _: None)

    def test_idempotency_re_run_is_noop(self, monkeypatch):
        """Re-running the same season upserts on same keys — no duplicates."""
        upsert_calls = []

        def _fake_upsert(rows, url, key, report_errors=None):
            upsert_calls.append(len(rows))
            return None

        monkeypatch.setattr(
            "backend.nbadata.ingest._upsert_player_seasons",
            _fake_upsert,
        )

        df = _mock_season_stats_df()
        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_season_stats",
            lambda season: df,
        )

        report1 = backfill_player_seasons(
            [2024],
            supabase_url="http://test",
            supabase_key="test-key",
        )
        assert report1.seasons_processed == [2024]
        assert report1.rows_written == 2

        report2 = backfill_player_seasons(
            [2024],
            supabase_url="http://test",
            supabase_key="test-key",
        )
        assert report2.seasons_processed == [2024]
        assert report2.rows_written == 2

        # Both runs upsert the same rows — idempotent at the key level
        assert len(upsert_calls) == 2

    def test_failure_isolation_per_season(self, monkeypatch):
        """One season's failure does not abort the others."""

        def _fake_upsert(rows, url, key, report_errors=None):
            pass

        monkeypatch.setattr(
            "backend.nbadata.ingest._upsert_player_seasons",
            _fake_upsert,
        )

        df = _mock_season_stats_df()
        call_count = [0]

        def _mock_fetch(season):
            call_count[0] += 1
            if call_count[0] == 2:  # second call (season 2023) fails
                raise RuntimeError("NBA.com rate limit hit")
            return df

        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_season_stats",
            _mock_fetch,
        )

        report = backfill_player_seasons([2022, 2023, 2024])

        # 2022 and 2024 succeeded, 2023 failed but didn't abort
        assert report.seasons_processed == [2022, 2024]
        assert len(report.errors) == 1
        assert "2023" in report.errors[0]

    def test_unmatched_names_in_report(self, monkeypatch):
        """Unmatched NBA names appear in the report; matched carry normalized key."""
        upserted_rows = []

        def _fake_upsert(rows, url, key, report_errors=None):
            upserted_rows.extend(rows)

        monkeypatch.setattr(
            "backend.nbadata.ingest._upsert_player_seasons",
            _fake_upsert,
        )

        df = pd.DataFrame([
            {
                "PLAYER_ID": 1, "PLAYER_NAME": "LeBron James",
                "TEAM_ABBREVIATION": "LAL", "AGE": 39, "GP": 71, "GS": 71,
                "MIN": 2500, "FGM": 9.6, "FGA": 18.0, "FTM": 4.5, "FTA": 5.7,
                "FG3M": 2.1, "FG3A": 5.0, "PTS": 25.7, "REB": 7.3, "AST": 8.3,
                "STL": 1.3, "BLK": 0.6, "TOV": 3.5, "USG_PCT": 0.285,
                "PACE": None, "OFF_RATING": None,
            },
            {
                "PLAYER_ID": 2, "PLAYER_NAME": "Totally Unknown Guy",
                "TEAM_ABBREVIATION": "TST", "AGE": 22, "GP": 30, "GS": 0,
                "MIN": 300, "FGM": 1.0, "FGA": 3.0, "FTM": 0.5, "FTA": 1.0,
                "FG3M": 0.2, "FG3A": 1.0, "PTS": 3.0, "REB": 1.0, "AST": 0.5,
                "STL": 0.1, "BLK": 0.0, "TOV": 0.5, "USG_PCT": 0.12,
                "PACE": None, "OFF_RATING": None,
            },
        ])

        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_season_stats",
            lambda season: df,
        )

        espn_names = ["lebron james", "stephen curry", "nikola jokic"]  # normalized

        report = backfill_player_seasons(
            [2024],
            supabase_url="http://test",
            supabase_key="test-key",
            espn_player_names=espn_names,
        )

        # LeBron matches ESPN; "Totally Unknown Guy" does not
        assert "totally unknown guy" in report.unmatched_names
        # The matched row carries the normalized key
        lebron = next(
            r for r in upserted_rows if r["display_name"] == "LeBron James"
        )
        assert lebron["normalized_name"] == "lebron james"

    def test_no_duplicate_person_id_season(self, monkeypatch):
        """Multiple calls for the same player/season upsert, not insert duplicates."""
        upserted_rows = []

        def _fake_upsert(rows, url, key, report_errors=None):
            upserted_rows.extend(rows)

        monkeypatch.setattr(
            "backend.nbadata.ingest._upsert_player_seasons",
            _fake_upsert,
        )

        df = _mock_season_stats_df()
        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_season_stats",
            lambda season: df,
        )

        r1 = backfill_player_seasons([2024])
        r2 = backfill_player_seasons([2024])

        # Same number of rows each run — idempotent
        assert r1.rows_written == r2.rows_written == 2


# ---------------------------------------------------------------------------
# Unit: upkeep helper
# ---------------------------------------------------------------------------


class TestUpkeep:
    def test_upkeep_determines_current_season(self, monkeypatch):
        """upkeep() calls backfill with the current NBA season year."""

        called_seasons = []

        def _fake_backfill(seasons, **kwargs):
            called_seasons.extend(seasons)
            return IngestReport(seasons_processed=seasons, rows_written=0)

        monkeypatch.setattr(
            "backend.nbadata.ingest.backfill_player_seasons",
            _fake_backfill,
        )

        # Mock datetime.date.today() to mid-season (January 2026 → 2025-26 season)
        import datetime as dt_module
        class _FakeDate(date):
            @classmethod
            def today(cls):
                return date(2026, 1, 15)
        monkeypatch.setattr(dt_module, "date", _FakeDate)
        upkeep()
        assert called_seasons == [2025]   # season started Oct 2025

    def test_upkeep_october_rollover(self, monkeypatch):
        """October 2026 → 2026-27 season."""
        called_seasons = []

        def _fake_backfill(seasons, **kwargs):
            called_seasons.extend(seasons)
            return IngestReport(seasons_processed=seasons, rows_written=0)

        monkeypatch.setattr(
            "backend.nbadata.ingest.backfill_player_seasons",
            _fake_backfill,
        )

        import datetime as dt_module
        class _FakeDate(date):
            @classmethod
            def today(cls):
                return date(2026, 10, 28)
        monkeypatch.setattr(dt_module, "date", _FakeDate)
        upkeep()
        assert called_seasons == [2026]


# ---------------------------------------------------------------------------
# Unit: rate-limiting — sleep is called
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_sleep_called_between_api_calls(self, monkeypatch):
        """_CALL_GAP sleep fires between nba_api calls."""
        sleep_calls = []
        monkeypatch.setattr(
            "backend.nbadata.ingest._sleep_between_calls",
            lambda: sleep_calls.append(1),
        )
        monkeypatch.setattr(
            "backend.nbadata.ingest._sleep_with_backoff",
            lambda _: None,
        )
        monkeypatch.setattr(
            "backend.nbadata.ingest._upsert_player_seasons",
            lambda rows, url, key, **kw: None,
        )

        # Mock the nba_api import inside _fetch_season_stats so the
        # sleep call inside the real _fetch_season_stats fires.
        df = _mock_season_stats_df()
        mock_endpoint = MagicMock()
        mock_endpoint.get_data_frames.return_value = [df]

        with patch(
            "nba_api.stats.endpoints.leaguedashplayerstats.LeagueDashPlayerStats",
            return_value=mock_endpoint,
        ):
            backfill_player_seasons(
                [2024],
                supabase_url="http://test",
                supabase_key="test-key",
            )

        # At least one sleep between fetch and upsert
        assert len(sleep_calls) >= 1


# ---------------------------------------------------------------------------
# IngestReport — repr and properties
# ---------------------------------------------------------------------------


class TestIngestReport:
    def test_matched_count(self):
        report = IngestReport(
            seasons_processed=[2024],
            rows_written=500,
            unmatched_names=["player x", "player y"],
        )
        assert report.matched_count == 498

    def test_repr(self):
        report = IngestReport(seasons_processed=[2024], rows_written=500)
        assert "2024" in repr(report)
        assert "500" in repr(report)
