"""
FCP Projections M-1 — hermetic tests for backend/nbadata/ingest.

All tests mock the nba_api client entirely (no live NBA.com calls).
``spec=`` mocks enforce real signatures — a standing lesson from N-4.

The mock Base frame deliberately carries ONLY columns the real Base measure
type returns (per-game MIN, no USG_PCT/PACE/OFF_RATING) — those come from
the Advanced frame, and fabricating them onto the Base mock is exactly what
let the missing Advanced merge ship green the first time.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from backend.nbadata.ingest import (
    IngestReport,
    _current_season,
    _ingest_bios,
    _row_for_upsert,
    _safe_float,
    _safe_int,
    _parse_date_str,
    _nba_season_string,
    backfill_player_seasons,
    upkeep,
)
from backend.recaps.store import RecapStore, RecapStoreError


# ---------------------------------------------------------------------------
# Helpers — mock nba_api responses
# ---------------------------------------------------------------------------


def _mock_season_stats_df() -> pd.DataFrame:
    """Minimal LeagueDashPlayerStats Base shape — per-game averages only."""
    return pd.DataFrame([
        {
            "PLAYER_ID": 2544,
            "PLAYER_NAME": "LeBron James",
            "TEAM_ABBREVIATION": "LAL",
            "AGE": 39.0,
            "GP": 71, "GS": 71, "MIN": 35.2,
            "FGM": 9.6, "FGA": 18.0, "FG_PCT": 0.533,
            "FTM": 4.5, "FTA": 5.7, "FT_PCT": 0.789,
            "FG3M": 2.1, "FG3A": 5.0, "FG3_PCT": 0.420,
            "PTS": 25.7, "REB": 7.3, "AST": 8.3, "STL": 1.3, "BLK": 0.6,
            "TOV": 3.5,
        },
        {
            "PLAYER_ID": 201939,
            "PLAYER_NAME": "Stephen Curry",
            "TEAM_ABBREVIATION": "GSW",
            "AGE": 36.0,
            "GP": 74, "GS": 74, "MIN": 32.7,
            "FGM": 9.0, "FGA": 20.0, "FG_PCT": 0.450,
            "FTM": 4.2, "FTA": 4.6, "FT_PCT": 0.913,
            "FG3M": 4.8, "FG3A": 12.0, "FG3_PCT": 0.400,
            "PTS": 26.4, "REB": 4.5, "AST": 5.1, "STL": 0.9, "BLK": 0.4,
            "TOV": 2.8,
        },
    ])


def _mock_advanced_stats_df() -> pd.DataFrame:
    """Minimal LeagueDashPlayerStats Advanced shape — where USG%/pace live."""
    return pd.DataFrame([
        {"PLAYER_ID": 2544, "PLAYER_NAME": "LeBron James",
         "USG_PCT": 0.285, "PACE": 101.2, "OFF_RATING": 116.3},
        {"PLAYER_ID": 201939, "PLAYER_NAME": "Stephen Curry",
         "USG_PCT": 0.305, "PACE": 99.8, "OFF_RATING": 118.1},
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
            "MIN": 34.1, "FGM": 8.0, "FGA": 16.0, "FG_PCT": 0.500,
            "FTM": 4.0, "FTA": 5.0, "FG3M": 2.0, "FG3A": 6.0,
            "PTS": 22.0, "REB": 5.0, "AST": 6.0, "STL": 1.0, "BLK": 0.5,
            "TOV": 2.0, "USG_PCT": 0.25, "PACE": 100.0, "OFF_RATING": 112.0,
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

    def test_minutes_total_mpg_per_game(self):
        """MIN is a per-game figure; minutes is the derived season total."""
        row = pd.Series({
            "PLAYER_ID": 1, "PLAYER_NAME": "Test Player",
            "TEAM_ABBREVIATION": "TST", "AGE": 25, "GP": 70, "GS": 70,
            "MIN": 35.0, "FGM": 8.0, "FGA": 16.0, "FTM": 4.0, "FTA": 5.0,
            "FG3M": 2.0, "FG3A": 6.0, "PTS": 22.0, "REB": 5.0, "AST": 6.0,
            "STL": 1.0, "BLK": 0.5, "TOV": 2.0,
        })
        result = _row_for_upsert(row, 2025)
        assert result["mpg"] == 35.0
        assert result["minutes"] == 2450.0

    def test_base_only_row_leaves_advanced_null(self):
        """Regression: the Base frame has no USG_PCT/PACE/OFF_RATING.

        Without the Advanced merge these must come out None, not crash —
        and the merge is what fills them (TestAdvancedMerge)."""
        row = pd.Series({
            "PLAYER_ID": 1, "PLAYER_NAME": "Test Player",
            "TEAM_ABBREVIATION": "TST", "AGE": 25, "GP": 82, "GS": 82,
            "MIN": 34.1, "FGM": 8.0, "FGA": 16.0, "FTM": 4.0, "FTA": 5.0,
            "FG3M": 2.0, "FG3A": 6.0, "PTS": 22.0, "REB": 5.0, "AST": 6.0,
            "STL": 1.0, "BLK": 0.5, "TOV": 2.0,
        })
        result = _row_for_upsert(row, 2025)
        assert result["usg_pct"] is None
        assert result["team_pace"] is None
        assert result["team_ortg"] is None

    def test_person_id_is_int(self):
        row = pd.Series({
            "PLAYER_ID": "2544",  # string — should become int
            "PLAYER_NAME": "Test", "TEAM_ABBREVIATION": "TST",
            "AGE": 25, "GP": 10, "GS": 0, "MIN": 20.0,
            "FGM": 0, "FGA": 0, "FTM": 0, "FTA": 0,
            "FG3M": 0, "FG3A": 0, "PTS": 0, "REB": 0, "AST": 0,
            "STL": 0, "BLK": 0, "TOV": 0,
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
    """Test the full backfill flow — mocks the internal fetch wrappers."""

    @pytest.fixture(autouse=True)
    def _hermetic(self, monkeypatch):
        """No sleeps, no live Advanced fetch, no skip-check or bio HTTP."""
        monkeypatch.setattr("backend.nbadata.ingest._sleep_between_calls", lambda: None)
        monkeypatch.setattr("backend.nbadata.ingest._sleep_with_backoff", lambda _: None)
        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_advanced_stats",
            lambda season: _mock_advanced_stats_df(),
        )
        monkeypatch.setattr(
            "backend.nbadata.ingest._season_already_stored",
            lambda store, season: False,
        )
        monkeypatch.setattr(
            "backend.nbadata.ingest._ingest_bios",
            lambda persons, store, report: None,
        )

    def test_idempotency_re_run_is_noop(self, monkeypatch):
        """Re-running the same season upserts on same keys — no duplicates."""
        upsert_calls = []

        def _fake_upsert(rows, store, report_errors=None):
            upsert_calls.append(len(rows))
            return len(rows)

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

        def _fake_upsert(rows, store, report_errors=None):
            return len(rows)

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
        """Unmatched NBA names appear in the report; matched carry normalized key.

        ESPN names are passed RAW (un-normalized) — the ingest must normalize
        the target side itself before fuzzy matching."""
        upserted_rows = []

        def _fake_upsert(rows, store, report_errors=None):
            upserted_rows.extend(rows)
            return len(rows)

        monkeypatch.setattr(
            "backend.nbadata.ingest._upsert_player_seasons",
            _fake_upsert,
        )

        df = pd.DataFrame([
            {
                "PLAYER_ID": 1, "PLAYER_NAME": "LeBron James",
                "TEAM_ABBREVIATION": "LAL", "AGE": 39, "GP": 71, "GS": 71,
                "MIN": 35.2, "FGM": 9.6, "FGA": 18.0, "FTM": 4.5, "FTA": 5.7,
                "FG3M": 2.1, "FG3A": 5.0, "PTS": 25.7, "REB": 7.3, "AST": 8.3,
                "STL": 1.3, "BLK": 0.6, "TOV": 3.5,
            },
            {
                "PLAYER_ID": 2, "PLAYER_NAME": "Totally Unknown Guy",
                "TEAM_ABBREVIATION": "TST", "AGE": 22, "GP": 30, "GS": 0,
                "MIN": 10.0, "FGM": 1.0, "FGA": 3.0, "FTM": 0.5, "FTA": 1.0,
                "FG3M": 0.2, "FG3A": 1.0, "PTS": 3.0, "REB": 1.0, "AST": 0.5,
                "STL": 0.1, "BLK": 0.0, "TOV": 0.5,
            },
        ])

        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_season_stats",
            lambda season: df,
        )

        # Raw ESPN display names — NOT pre-normalized
        espn_names = ["LeBron James", "Stephen Curry", "Nikola Jokić"]

        report = backfill_player_seasons(
            [2024],
            supabase_url="http://test",
            supabase_key="test-key",
            espn_player_names=espn_names,
        )

        # LeBron matches ESPN; "Totally Unknown Guy" does not
        assert "totally unknown guy" in report.unmatched_names
        assert "lebron james" not in report.unmatched_names
        # The matched row carries the normalized key
        lebron = next(
            r for r in upserted_rows if r["display_name"] == "LeBron James"
        )
        assert lebron["normalized_name"] == "lebron james"

    def test_no_duplicate_person_id_season(self, monkeypatch):
        """Dry run (no store) reports rows built, identically across runs."""
        df = _mock_season_stats_df()
        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_season_stats",
            lambda season: df,
        )

        r1 = backfill_player_seasons([2024])
        r2 = backfill_player_seasons([2024])

        # Same number of rows each run — idempotent
        assert r1.rows_written == r2.rows_written == 2

    def test_rows_written_zero_on_upsert_failure(self, monkeypatch):
        """A failed upsert reports 0 rows written — never built-but-not-stored."""

        def _failing_upsert(rows, store, report_errors=None):
            if report_errors is not None:
                report_errors.append("upsert failed after retries")
            return 0

        monkeypatch.setattr(
            "backend.nbadata.ingest._upsert_player_seasons",
            _failing_upsert,
        )
        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_season_stats",
            lambda season: _mock_season_stats_df(),
        )

        report = backfill_player_seasons(
            [2024],
            supabase_url="http://test",
            supabase_key="test-key",
        )
        assert report.rows_written == 0
        assert report.players_seen == 2
        assert report.errors


# ---------------------------------------------------------------------------
# Integration: Advanced merge — where USG%/pace/ORtg actually come from
# ---------------------------------------------------------------------------


class TestAdvancedMerge:
    @pytest.fixture(autouse=True)
    def _hermetic(self, monkeypatch):
        monkeypatch.setattr("backend.nbadata.ingest._sleep_between_calls", lambda: None)
        monkeypatch.setattr("backend.nbadata.ingest._sleep_with_backoff", lambda _: None)
        monkeypatch.setattr(
            "backend.nbadata.ingest._season_already_stored",
            lambda store, season: False,
        )
        monkeypatch.setattr(
            "backend.nbadata.ingest._ingest_bios",
            lambda persons, store, report: None,
        )
        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_season_stats",
            lambda season: _mock_season_stats_df(),
        )
        self.upserted = []

        def _fake_upsert(rows, store, report_errors=None):
            self.upserted.extend(rows)
            return len(rows)

        monkeypatch.setattr(
            "backend.nbadata.ingest._upsert_player_seasons",
            _fake_upsert,
        )

    def test_advanced_stats_merged_into_rows(self, monkeypatch):
        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_advanced_stats",
            lambda season: _mock_advanced_stats_df(),
        )

        backfill_player_seasons(
            [2024], supabase_url="http://test", supabase_key="test-key"
        )

        lebron = next(r for r in self.upserted if r["person_id"] == 2544)
        assert lebron["usg_pct"] == 0.285
        assert lebron["team_pace"] == 101.2
        assert lebron["team_ortg"] == 116.3

    def test_advanced_fetch_failure_still_ingests(self, monkeypatch):
        """Advanced endpoint down → season ingests anyway, columns null,
        failure lands in the report instead of aborting."""

        def _boom(season):
            raise RuntimeError("Advanced endpoint timed out")

        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_advanced_stats", _boom
        )

        report = backfill_player_seasons(
            [2024], supabase_url="http://test", supabase_key="test-key"
        )

        assert report.rows_written == 2
        assert any("advanced" in e.lower() for e in report.errors)
        lebron = next(r for r in self.upserted if r["person_id"] == 2544)
        assert lebron["usg_pct"] is None
        assert lebron["team_pace"] is None


# ---------------------------------------------------------------------------
# Integration: resumable skip — past stored seasons are not refetched
# ---------------------------------------------------------------------------


class TestResumableSkip:
    @pytest.fixture(autouse=True)
    def _hermetic(self, monkeypatch):
        monkeypatch.setattr("backend.nbadata.ingest._sleep_between_calls", lambda: None)
        monkeypatch.setattr("backend.nbadata.ingest._sleep_with_backoff", lambda _: None)
        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_advanced_stats",
            lambda season: _mock_advanced_stats_df(),
        )
        monkeypatch.setattr(
            "backend.nbadata.ingest._ingest_bios",
            lambda persons, store, report: None,
        )
        monkeypatch.setattr(
            "backend.nbadata.ingest._upsert_player_seasons",
            lambda rows, store, report_errors=None: len(rows),
        )
        self.fetched_seasons = []

        def _recording_fetch(season):
            self.fetched_seasons.append(season)
            return _mock_season_stats_df()

        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_season_stats", _recording_fetch
        )

    def test_past_stored_season_skipped(self, monkeypatch):
        monkeypatch.setattr(
            "backend.nbadata.ingest._season_already_stored",
            lambda store, season: True,
        )

        report = backfill_player_seasons(
            [2018, 2019],
            supabase_url="http://test",
            supabase_key="test-key",
        )

        assert report.seasons_skipped == [2018, 2019]
        assert report.seasons_processed == []
        assert self.fetched_seasons == []

    def test_current_season_never_skipped(self, monkeypatch):
        """Even when stored, the in-progress season is refetched."""
        monkeypatch.setattr(
            "backend.nbadata.ingest._season_already_stored",
            lambda store, season: True,
        )
        current = _current_season()

        report = backfill_player_seasons(
            [current],
            supabase_url="http://test",
            supabase_key="test-key",
        )

        assert report.seasons_processed == [current]
        assert report.seasons_skipped == []
        assert self.fetched_seasons == [current]

    def test_skip_existing_false_forces_refetch(self, monkeypatch):
        monkeypatch.setattr(
            "backend.nbadata.ingest._season_already_stored",
            lambda store, season: True,
        )

        report = backfill_player_seasons(
            [2018],
            supabase_url="http://test",
            supabase_key="test-key",
            skip_existing=False,
        )

        assert report.seasons_processed == [2018]
        assert self.fetched_seasons == [2018]

    def test_dry_run_never_checks_store(self, monkeypatch):
        """Without credentials there is no store to check — no skip logic."""

        def _boom(store, season):
            raise AssertionError("skip-check must not run in dry mode")

        monkeypatch.setattr(
            "backend.nbadata.ingest._season_already_stored", _boom
        )

        report = backfill_player_seasons([2018])
        assert report.seasons_processed == [2018]


# ---------------------------------------------------------------------------
# Unit: bio ingest — resumable, missing-only, failure-tolerant
# ---------------------------------------------------------------------------


class TestBioIngest:
    @pytest.fixture(autouse=True)
    def _no_sleep(self, monkeypatch):
        monkeypatch.setattr("backend.nbadata.ingest._sleep_between_calls", lambda: None)
        monkeypatch.setattr("backend.nbadata.ingest._sleep_with_backoff", lambda _: None)

    def _report(self):
        return IngestReport(seasons_processed=[2024])

    def test_only_missing_bios_fetched(self, monkeypatch):
        """Players with a stored bio are never refetched (resumable)."""
        store = MagicMock(spec=RecapStore)
        store.list_nba_bio_person_ids.return_value = {2544}

        fetched = []

        def _fake_fetch(person_id):
            fetched.append(person_id)
            return {
                "person_id": person_id,
                "display_name": "Stephen Curry",
                "dob": "1988-03-14",
                "height": "6-2",
                "weight": 185,
                "position": "Guard",
                "draft_year": 2009,
                "draft_round": 1,
                "draft_pick": 7,
                "experience": 15,
            }

        monkeypatch.setattr("backend.nbadata.ingest._fetch_bio", _fake_fetch)

        report = self._report()
        _ingest_bios(
            {2544: "LeBron James", 201939: "Stephen Curry"}, store, report
        )

        # Only the missing player is fetched
        assert fetched == [201939]
        assert report.bios_written == 1
        # The upserted row carries the normalized name key
        (rows,) = store.upsert_nba_player_bios.call_args.args
        assert rows[0]["person_id"] == 201939
        assert rows[0]["normalized_name"] == "stephen curry"

    def test_failed_bio_fetch_reported_and_skipped(self, monkeypatch):
        store = MagicMock(spec=RecapStore)
        store.list_nba_bio_person_ids.return_value = set()

        monkeypatch.setattr(
            "backend.nbadata.ingest._fetch_bio", lambda person_id: {}
        )

        report = self._report()
        _ingest_bios({201939: "Stephen Curry"}, store, report)

        assert report.bios_written == 0
        assert any("201939" in e for e in report.errors)
        store.upsert_nba_player_bios.assert_not_called()

    def test_stored_id_list_failure_skips_pass(self, monkeypatch):
        """If we can't see what's stored, skip the pass rather than hammer
        CommonPlayerInfo for every player on every run."""
        store = MagicMock(spec=RecapStore)
        store.list_nba_bio_person_ids.side_effect = RecapStoreError("boom")

        def _must_not_fetch(person_id):
            raise AssertionError("bio fetch must not run when listing fails")

        monkeypatch.setattr("backend.nbadata.ingest._fetch_bio", _must_not_fetch)

        report = self._report()
        _ingest_bios({2544: "LeBron James"}, store, report)

        assert report.bios_written == 0
        assert any("Bio pass skipped" in e for e in report.errors)


# ---------------------------------------------------------------------------
# Unit: upkeep helper
# ---------------------------------------------------------------------------


class TestUpkeep:
    def test_upkeep_determines_current_season(self, monkeypatch):
        """upkeep() calls backfill with the current NBA season year."""

        called_seasons = []

        def _fake_backfill(seasons, **kwargs):
            called_seasons.extend(seasons)
            return IngestReport(seasons_processed=seasons)

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
            return IngestReport(seasons_processed=seasons)

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
        """_CALL_GAP sleep fires after each nba_api call (Base + Advanced)."""
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
            "backend.nbadata.ingest._season_already_stored",
            lambda store, season: False,
        )
        monkeypatch.setattr(
            "backend.nbadata.ingest._ingest_bios",
            lambda persons, store, report: None,
        )
        monkeypatch.setattr(
            "backend.nbadata.ingest._upsert_player_seasons",
            lambda rows, store, **kw: len(rows),
        )

        # Mock the nba_api import inside the fetch wrappers so the
        # sleep calls inside the real fetch functions fire.
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

        # One sleep per nba_api call: Base fetch + Advanced fetch
        assert len(sleep_calls) >= 2


# ---------------------------------------------------------------------------
# IngestReport — repr and properties
# ---------------------------------------------------------------------------


class TestIngestReport:
    def test_matched_count(self):
        report = IngestReport(
            seasons_processed=[2024],
            rows_written=500,
            players_seen=500,
            unmatched_names=["player x", "player y"],
        )
        assert report.matched_count == 498

    def test_matched_count_never_negative(self):
        """Upsert failure zeroes rows_written but matching still happened —
        the count keys off players seen, not rows stored."""
        report = IngestReport(
            seasons_processed=[2024],
            rows_written=0,
            players_seen=0,
            unmatched_names=["player x"],
        )
        assert report.matched_count == 0

    def test_repr(self):
        report = IngestReport(seasons_processed=[2024], rows_written=500)
        assert "2024" in repr(report)
        assert "500" in repr(report)
