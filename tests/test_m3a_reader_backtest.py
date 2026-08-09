"""
FCP Projections M-3a — hermetic tests for reader + backtest harness.

All tests mock RecapStore with ``spec=RecapStore`` (real signatures).
No live Supabase, no nba_api.  Synthetic two-season fixture with known
answers.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import numpy as np
import pytest

from backend.nbadata.reader import read_player_seasons, read_player_bios
from backend.projections.backtest import (
    BacktestResult,
    CATEGORIES,
    evaluate,
    naive_baseline,
    _safe_pct,
)
from backend.recaps.store import RecapStore


# ── synthetic fixture: two seasons of known stats ─────────────────────────────


def _make_seasons_df(
    person_ids: list[int],
    names: list[str],
    season_n1: int,
    season_n: int,
    stats_n1: dict[str, list[float]],
    stats_n: dict[str, list[float]],
    gp_n1: list[int] | None = None,
    gp_n: list[int] | None = None,
) -> pd.DataFrame:
    """Build a two-season DataFrame with columns matching the M-1 schema.

    Returns one DataFrame with rows for BOTH seasons (2 × len(person_ids) rows).
    """
    n = len(person_ids)

    def _build_rows(season, gp, age, stats):
        return {
            "person_id": person_ids,
            "normalized_name": [name.lower() for name in names],
            "display_name": names,
            "season": [season] * n,
            "gp": gp or [82] * n,
            "gs": [82] * n,
            "age": [float(age)] * n,
            "team": ["TST"] * n,
            "position": ["F"] * n,
            "minutes": [2400.0] * n,
            "mpg": [30.0] * n,
            "fgm": stats.get("fgm", [8.0] * n),
            "fga": stats.get("fga", [16.0] * n),
            "ftm": stats.get("ftm", [4.0] * n),
            "fta": stats.get("fta", [5.0] * n),
            "tpm": stats.get("tpm", [2.0] * n),
            "tpa": stats.get("tpa", [5.0] * n),
            "tov": stats.get("tov", [2.5] * n),
            "usg_pct": [0.25] * n,
            "pts": stats.get("pts", [20.0] * n),
            "reb": stats.get("reb", [5.0] * n),
            "ast": stats.get("ast", [5.0] * n),
            "stl": stats.get("stl", [1.0] * n),
            "blk": stats.get("blk", [0.5] * n),
            "team_pace": [None] * n,
            "team_ortg": [None] * n,
            "fetched_at": ["2026-01-01"] * n,
        }

    df_n1 = pd.DataFrame(_build_rows(season_n1, gp_n1, 28.0, stats_n1))
    df_n = pd.DataFrame(_build_rows(season_n, gp_n, 29.0, stats_n))
    return pd.concat([df_n1, df_n], ignore_index=True)


def _mock_store_for_seasons(df: pd.DataFrame) -> MagicMock:
    """Return a spec=RecapStore mock whose list_nba_player_seasons returns df rows."""
    store = MagicMock(spec=RecapStore)
    store.list_nba_player_seasons.return_value = df.to_dict("records")
    return store


# ── reader tests ──────────────────────────────────────────────────────────────


class TestReader:
    def test_read_empty_table(self):
        """Empty table → empty DataFrame with correct columns, no crash."""
        store = MagicMock(spec=RecapStore)
        store.list_nba_player_seasons.return_value = []

        df = read_player_seasons(store)
        assert df.empty
        assert "person_id" in df.columns
        assert "pts" in df.columns
        assert "fgm" in df.columns

    def test_read_player_bios_empty(self):
        store = MagicMock(spec=RecapStore)
        store.list_nba_player_bios.return_value = []

        df = read_player_bios(store)
        assert df.empty
        assert "person_id" in df.columns
        assert "dob" in df.columns

    def test_read_season_filter(self):
        """Season filter is passed through to store."""
        df = _make_seasons_df(
            person_ids=[1, 2],
            names=["Player A", "Player B"],
            season_n1=2023,
            season_n=2024,
            stats_n1={}, stats_n={},
        )
        store = MagicMock(spec=RecapStore)
        store.list_nba_player_seasons.return_value = df.to_dict("records")

        read_player_seasons(store, season=2024)
        store.list_nba_player_seasons.assert_called_once_with(season=2024)


# ── backtest: evaluate() ──────────────────────────────────────────────────────


class TestEvaluate:
    """Unit tests for evaluate() — the core comparison function."""

    def test_identical_seasons_mae_zero(self):
        """Two identical seasons → MAE 0 across all categories."""
        pred = pd.DataFrame({
            "person_id": [1, 2],
            "pts": [25.0, 20.0], "reb": [7.0, 4.0], "ast": [6.0, 3.0],
            "stl": [1.2, 0.8], "blk": [0.6, 0.4], "tpm": [2.0, 1.5],
            "tov": [3.0, 2.0],
            "fgm": [9.0, 7.0], "fga": [18.0, 14.0],
            "ftm": [5.0, 4.0], "fta": [6.0, 5.0],
        })
        actual = pd.DataFrame({
            "person_id": [1, 2],
            "season": [2024, 2024],
            "gp": [75, 80],
            "pts": [25.0, 20.0], "reb": [7.0, 4.0], "ast": [6.0, 3.0],
            "stl": [1.2, 0.8], "blk": [0.6, 0.4], "tpm": [2.0, 1.5],
            "tov": [3.0, 2.0],
            "fgm": [9.0, 7.0], "fga": [18.0, 14.0],
            "ftm": [5.0, 4.0], "fta": [6.0, 5.0],
        })

        result = evaluate(pred, actual)
        assert result.players_evaluated == 2
        assert result.excluded_low_gp == 0
        assert result.excluded_no_prediction == 0
        for cat in CATEGORIES:
            assert result.mae[cat] == pytest.approx(0.0, abs=1e-9), f"{cat} MAE not zero"

    def test_player_jumps_five_pts(self):
        """Player A jumps +5 PTS → PTS MAE contribution is exactly 5 for them."""
        pred = pd.DataFrame({
            "person_id": [1, 2],
            "pts": [25.0, 20.0], "reb": [7.0, 4.0], "ast": [6.0, 3.0],
            "stl": [1.2, 0.8], "blk": [0.6, 0.4], "tpm": [2.0, 1.5],
            "tov": [3.0, 2.0],
            "fgm": [9.0, 7.0], "fga": [18.0, 14.0],
            "ftm": [5.0, 4.0], "fta": [6.0, 5.0],
        })
        actual = pd.DataFrame({
            "person_id": [1, 2],
            "season": [2024, 2024],
            "gp": [75, 80],
            # Player 1: jumped +5 PTS; Player 2: unchanged
            "pts": [30.0, 20.0], "reb": [7.0, 4.0], "ast": [6.0, 3.0],
            "stl": [1.2, 0.8], "blk": [0.6, 0.4], "tpm": [2.0, 1.5],
            "tov": [3.0, 2.0],
            "fgm": [9.0, 7.0], "fga": [18.0, 14.0],
            "ftm": [5.0, 4.0], "fta": [6.0, 5.0],
        })

        result = evaluate(pred, actual)
        # PTS MAE = (|25-30| + |20-20|) / 2 = 2.5
        assert result.mae["pts"] == pytest.approx(2.5)
        # Other categories unchanged → MAE 0
        for cat in ["reb", "ast", "stl", "blk", "tpm", "tov"]:
            assert result.mae[cat] == pytest.approx(0.0, abs=1e-9)

    def test_fg_pct_attempt_weighted(self):
        """FG% MAE is attempt-weighted, not a simple mean of percentage errors.

        Player A: 9/18 (.500) → 10/20 (.500) — 0 error, 20 FGA weight
        Player B: 7/14 (.500) → 8/14 (.571) — .071 error, 14 FGA weight
        Weighted MAE = (0×20 + .071×14) / 34 ≈ 0.0294

        Simple mean would be (0 + .071)/2 = .0357 — different!
        """
        pred = pd.DataFrame({
            "person_id": [1, 2],
            "pts": [25.0, 20.0], "reb": [7.0, 4.0], "ast": [6.0, 3.0],
            "stl": [1.2, 0.8], "blk": [0.6, 0.4], "tpm": [2.0, 1.5],
            "tov": [3.0, 2.0],
            "fgm": [9.0, 7.0], "fga": [18.0, 14.0],
            "ftm": [5.0, 4.0], "fta": [6.0, 5.0],
        })
        actual = pd.DataFrame({
            "person_id": [1, 2],
            "season": [2024, 2024],
            "gp": [75, 80],
            "pts": [25.0, 20.0], "reb": [7.0, 4.0], "ast": [6.0, 3.0],
            "stl": [1.2, 0.8], "blk": [0.6, 0.4], "tpm": [2.0, 1.5],
            "tov": [3.0, 2.0],
            # Player A: 10/20 (.500), Player B: 8/14 (.571)
            "fgm": [10.0, 8.0],
            "fga": [20.0, 14.0],
            "ftm": [5.0, 4.0], "fta": [6.0, 5.0],
        })

        result = evaluate(pred, actual)

        # Attempt-weighted: (|.500-.500|×20 + |.500-.571|×14) / 34 ≈ 0.0294
        expected = (0.0 * 20 + abs(0.500 - 8.0 / 14.0) * 14) / 34.0
        assert result.mae["fg_pct"] == pytest.approx(expected, abs=1e-4)

        # NOT the simple mean: (0 + .0714)/2 = .0357
        simple_mean = (abs(0.500 - 0.500) + abs(0.500 - 8.0 / 14.0)) / 2.0
        assert result.mae["fg_pct"] != pytest.approx(simple_mean, abs=1e-6)

    def test_min_gp_filter(self):
        """Players below min_gp are excluded from evaluation."""
        pred = pd.DataFrame({
            "person_id": [1, 2, 3],
            "pts": [25.0, 20.0, 15.0], "reb": [7.0, 4.0, 3.0],
            "ast": [6.0, 3.0, 2.0], "stl": [1.0, 1.0, 1.0],
            "blk": [0.5, 0.5, 0.5], "tpm": [2.0, 1.5, 1.0],
            "tov": [3.0, 2.0, 1.0],
            "fgm": [9.0, 7.0, 5.0], "fga": [18.0, 14.0, 10.0],
            "ftm": [5.0, 4.0, 3.0], "fta": [6.0, 5.0, 4.0],
        })
        actual = pd.DataFrame({
            "person_id": [1, 2, 3],
            "season": [2024, 2024, 2024],
            "gp": [75, 80, 10],  # Player 3: only 10 GP
            "pts": [25.0, 20.0, 15.0], "reb": [7.0, 4.0, 3.0],
            "ast": [6.0, 3.0, 2.0], "stl": [1.0, 1.0, 1.0],
            "blk": [0.5, 0.5, 0.5], "tpm": [2.0, 1.5, 1.0],
            "tov": [3.0, 2.0, 1.0],
            "fgm": [9.0, 7.0, 5.0], "fga": [18.0, 14.0, 10.0],
            "ftm": [5.0, 4.0, 3.0], "fta": [6.0, 5.0, 4.0],
        })

        result = evaluate(pred, actual, min_gp=20)
        assert result.players_evaluated == 2  # player 3 excluded by GP
        assert result.excluded_low_gp == 1
        assert result.excluded_no_prediction == 0

    def test_rookie_excluded_count(self):
        """A qualified player with no prediction row is counted, not vanished."""
        pred = pd.DataFrame({
            "person_id": [1],
            "pts": [25.0], "reb": [7.0], "ast": [6.0],
            "stl": [1.0], "blk": [0.5], "tpm": [2.0], "tov": [3.0],
            "fgm": [9.0], "fga": [18.0], "ftm": [5.0], "fta": [6.0],
        })
        actual = pd.DataFrame({
            "person_id": [1, 2],  # Player 2 has no prediction (rookie)
            "season": [2024, 2024],
            "gp": [75, 65],
            "pts": [25.0, 15.0], "reb": [7.0, 3.0], "ast": [6.0, 2.0],
            "stl": [1.0, 1.0], "blk": [0.5, 0.5], "tpm": [2.0, 1.0],
            "tov": [3.0, 1.0],
            "fgm": [9.0, 5.0], "fga": [18.0, 10.0],
            "ftm": [5.0, 3.0], "fta": [6.0, 4.0],
        })

        result = evaluate(pred, actual)
        assert result.players_evaluated == 1
        assert result.excluded_no_prediction == 1
        assert result.excluded_low_gp == 0

    def test_pct_nan_error_drops_weight_from_denominator(self):
        """A player whose predicted percentage is undefined (0 attempts)
        contributes neither error nor weight — their actual attempts must
        not dilute the weighted MAE."""
        pred = pd.DataFrame({
            "person_id": [1, 2],
            "pts": [25.0, 20.0], "reb": [7.0, 4.0], "ast": [6.0, 3.0],
            "stl": [1.0, 1.0], "blk": [0.5, 0.5], "tpm": [2.0, 1.5],
            "tov": [3.0, 2.0],
            # Player 1: no predicted FT attempts → FT% undefined
            "fgm": [9.0, 7.0], "fga": [18.0, 14.0],
            "ftm": [0.0, 4.0], "fta": [0.0, 5.0],
        })
        actual = pd.DataFrame({
            "person_id": [1, 2],
            "season": [2024, 2024],
            "gp": [75, 80],
            "pts": [25.0, 20.0], "reb": [7.0, 4.0], "ast": [6.0, 3.0],
            "stl": [1.0, 1.0], "blk": [0.5, 0.5], "tpm": [2.0, 1.5],
            "tov": [3.0, 2.0],
            "fgm": [9.0, 7.0], "fga": [18.0, 14.0],
            # Player 1 really took 6.0 FTA/game; player 2's FT% missed by 0.10
            "ftm": [4.0, 3.5], "fta": [6.0, 5.0],
        })

        result = evaluate(pred, actual)
        # Only player 2 has a defined FT% error: |0.8 - 0.7| = 0.10.
        # If player 1's 6.0 actual FTA leaked into the denominator the MAE
        # would read 0.045 — the bug this guards against.
        assert result.mae["ft_pct"] == pytest.approx(0.10, abs=1e-6)


# ── backtest: naive baseline (via mocked store) ───────────────────────────────


class TestNaiveBaseline:
    """Integration tests for naive_baseline() with mocked RecapStore."""

    def test_identical_seasons_mae_zero(self):
        """Naive baseline with identical N-1 and N → MAE 0."""
        df = _make_seasons_df(
            person_ids=[1, 2],
            names=["LeBron James", "Stephen Curry"],
            season_n1=2023,
            season_n=2024,
            stats_n1={"pts": [25.7, 26.4], "fgm": [9.6, 9.0], "fga": [18.0, 20.0]},
            stats_n={"pts": [25.7, 26.4], "fgm": [9.6, 9.0], "fga": [18.0, 20.0]},
        )
        store = _mock_store_for_seasons(df)

        result = naive_baseline(store, target_season=2024, min_gp=20)
        assert result.players_evaluated == 2
        assert result.excluded_low_gp == 0
        assert result.excluded_no_prediction == 0
        for cat in CATEGORIES:
            assert result.mae[cat] == pytest.approx(0.0, abs=1e-9), f"{cat} MAE not zero"

    def test_rookie_excluded_in_naive_baseline(self):
        """Player in N but not in N-1 → excluded, count reported."""
        # Player 1: has both seasons. Player 2: only in season N (rookie).
        rows = []
        # Season N-1: only player 1
        rows.append({
            "person_id": 1, "normalized_name": "lebron james",
            "display_name": "LeBron James", "season": 2023,
            "gp": 75, "gs": 75, "age": 38.0, "team": "LAL", "position": "F",
            "minutes": 2400.0, "mpg": 32.0,
            "fgm": 9.0, "fga": 18.0, "ftm": 5.0, "fta": 6.0,
            "tpm": 2.0, "tpa": 5.0, "tov": 3.0, "usg_pct": 0.30,
            "pts": 25.0, "reb": 7.0, "ast": 6.0, "stl": 1.2, "blk": 0.6,
            "team_pace": None, "team_ortg": None, "fetched_at": "2026-01-01",
        })
        # Season N: both players
        for pid, name, pts in [(1, "LeBron James", 25.0), (2, "Rookie Player", 12.0)]:
            rows.append({
                "person_id": pid, "normalized_name": name.lower(),
                "display_name": name, "season": 2024,
                "gp": 75, "gs": 75, "age": 39.0 if pid == 1 else 20.0,
                "team": "TST", "position": "F",
                "minutes": 2400.0, "mpg": 32.0,
                "fgm": 9.0, "fga": 18.0, "ftm": 5.0, "fta": 6.0,
                "tpm": 2.0, "tpa": 5.0, "tov": 3.0, "usg_pct": 0.30,
                "pts": pts, "reb": 7.0, "ast": 6.0, "stl": 1.2, "blk": 0.6,
                "team_pace": None, "team_ortg": None, "fetched_at": "2026-01-01",
            })

        store = MagicMock(spec=RecapStore)
        store.list_nba_player_seasons.return_value = rows

        result = naive_baseline(store, target_season=2024, min_gp=20)

        # Only player 1 evaluated (has N-1). Player 2 is a rookie — no
        # prior season, so no prediction — and is REPORTED, never vanished.
        assert result.players_evaluated == 1
        assert result.excluded_no_prediction == 1
        assert result.excluded_low_gp == 0

    def test_backtest_result_repr_and_table(self):
        result = BacktestResult(
            season=2024,
            players_evaluated=200,
            excluded_low_gp=15,
            excluded_no_prediction=40,
            mae={
                "pts": 3.21, "reb": 1.87, "ast": 1.54,
                "stl": 0.33, "blk": 0.28, "tpm": 0.62,
                "tov": 0.71, "fg_pct": 0.018, "ft_pct": 0.025,
            },
        )
        table = result.mae_table()
        assert "2024" in repr(result)
        assert "200" in repr(result)
        assert "pts" in table
        assert "3.21" in table
        # Both exclusion counts surface in the human-readable table
        assert "15" in table
        assert "40" in table

    def test_empty_store_graceful(self):
        """Empty store → no crash, sensible result."""
        store = MagicMock(spec=RecapStore)
        store.list_nba_player_seasons.return_value = []

        result = naive_baseline(store, target_season=2024)
        assert result.players_evaluated == 0
        assert result.excluded_low_gp == 0
        assert result.excluded_no_prediction == 0
        assert all(np.isnan(v) for v in result.mae.values())


# ── helpers ───────────────────────────────────────────────────────────────────


class TestSafePct:
    def test_zero_attempts_returns_nan(self):
        s = _safe_pct(pd.Series([5.0, 0.0]), pd.Series([10.0, 0.0]))
        assert s.iloc[0] == 0.5
        assert pd.isna(s.iloc[1])

    def test_clips_to_range(self):
        s = _safe_pct(pd.Series([12.0]), pd.Series([10.0]))
        assert s.iloc[0] == 1.0


# ── RecapStore pagination ────────────────────────────────────────────────────


class TestRecapStoreReadMethods:
    """Verify the new reader methods handle pagination correctly."""

    def test_list_nba_player_seasons_paginates(self, monkeypatch):
        """A full 1000-row page triggers a second request at offset 1000."""
        store = RecapStore(url="http://test", service_role_key="test-key")

        page1 = [{"person_id": i, "season": 2024} for i in range(1000)]
        page2 = [{"person_id": 1000 + i, "season": 2024} for i in range(371)]
        calls: list[dict] = []

        def _fake_request(method, path, *, params=None, json=None, prefer=None):
            calls.append(params)
            return page1 if params["offset"] == "0" else page2

        monkeypatch.setattr(store, "_request", _fake_request)

        rows = store.list_nba_player_seasons(season=2024)
        assert len(rows) == 1371
        assert [c["offset"] for c in calls] == ["0", "1000"]
        assert all(c["season"] == "eq.2024" for c in calls)

    def test_list_nba_player_seasons_short_page_stops(self, monkeypatch):
        """A short page (< 1000 rows) ends pagination after one request."""
        store = RecapStore(url="http://test", service_role_key="test-key")
        calls: list[dict] = []

        def _fake_request(method, path, *, params=None, json=None, prefer=None):
            calls.append(params)
            return [{"person_id": 1, "season": 2024}]

        monkeypatch.setattr(store, "_request", _fake_request)

        rows = store.list_nba_player_seasons()
        assert len(rows) == 1
        assert len(calls) == 1
        assert "season" not in calls[0]  # no filter when season is omitted

    def test_list_nba_player_bios_includes_position(self, monkeypatch):
        """The bio select carries position — M-3b's regression-to-position-
        means needs it."""
        store = RecapStore(url="http://test", service_role_key="test-key")
        seen: list[dict] = []

        def _fake_request(method, path, *, params=None, json=None, prefer=None):
            seen.append(params)
            return []

        monkeypatch.setattr(store, "_request", _fake_request)

        store.list_nba_player_bios()
        assert "position" in seen[0]["select"]
