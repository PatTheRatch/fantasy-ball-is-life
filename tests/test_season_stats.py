"""season_stats computation.

The worker previously stored an empty list for this phase ("fix properly in
a follow-up"), so every category column on the Standings tab rendered 0 in
all three views (Totals / Per-Week Avg / Ranks) — the tab joins its
`season_stats` rows by team and reads `PTS`/`REB`/... plus `pts_rank`/
`fg_pct_rank`/... , none of which existed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.worker import refresh as wrk


class _FakeBoard:
    def __init__(self, df: pd.DataFrame):
        self._df = df
        self.calls: list[list[int]] = []

    def all_play(self, weeks, **kwargs):
        self.calls.append(list(weeks))
        return self._df


def _frame() -> pd.DataFrame:
    # Alpha leads the counting cats; Beta commits FEWER turnovers.
    return pd.DataFrame(
        {
            "Team": ["Alpha", "Beta"],
            "PTS": [900.0, 800.0],
            "REB": [350.0, 300.0],
            "AST": [200.0, 180.0],
            "STL": [60.0, 55.0],
            "BLK": [40.0, 30.0],
            "3PM": [90.0, 85.0],
            "FG%": [0.480, 0.455],
            "FT%": [0.810, 0.790],
            "TO": [120.0, 95.0],
        }
    )


@pytest.fixture
def board(monkeypatch):
    b = _FakeBoard(_frame())
    monkeypatch.setattr("backend.api.deps._scoreboard", lambda *a, **k: b)
    return b


class TestShape:
    def test_one_row_per_team_with_totals(self, board):
        rows = wrk._build_season_stats([1, 2, 3])
        assert len(rows) == 2
        alpha = next(r for r in rows if r["Team"] == "Alpha")
        assert alpha["PTS"] == 900.0
        assert alpha["REB"] == 350.0
        assert alpha["FG%"] == pytest.approx(0.480)

    def test_emits_team_alias(self, board):
        """StandingsTab joins on `r.Team ?? r.team`."""
        rows = wrk._build_season_stats([1])
        assert all(r["team"] == r["Team"] for r in rows)

    def test_requests_all_weeks_through_current(self, board):
        wrk._build_season_stats([1, 2, 3, 4])
        assert board.calls == [[1, 2, 3, 4]]


class TestRanks:
    def test_rank_keys_match_frontend_catRankKey(self, board):
        """catRankKey(): lowercase, '%' -> '_pct', suffix '_rank'."""
        rows = wrk._build_season_stats([1])
        alpha = rows[0]
        for key in (
            "pts_rank", "reb_rank", "ast_rank", "stl_rank", "blk_rank",
            "3pm_rank", "fg_pct_rank", "ft_pct_rank", "to_rank",
        ):
            assert key in alpha, f"missing {key}"

    def test_counting_stats_rank_highest_first(self, board):
        rows = wrk._build_season_stats([1])
        alpha = next(r for r in rows if r["Team"] == "Alpha")
        beta = next(r for r in rows if r["Team"] == "Beta")
        # Alpha scores more -> rank 1.
        assert alpha["pts_rank"] == 1
        assert beta["pts_rank"] == 2

    def test_turnovers_rank_inverted(self, board):
        """Fewest turnovers is BEST — the one category where less wins."""
        rows = wrk._build_season_stats([1])
        alpha = next(r for r in rows if r["Team"] == "Alpha")  # 120 TO
        beta = next(r for r in rows if r["Team"] == "Beta")    # 95 TO
        assert beta["to_rank"] == 1, "fewer turnovers must rank first"
        assert alpha["to_rank"] == 2


class TestDegradation:
    def test_no_weeks_returns_empty(self, board):
        assert wrk._build_season_stats([]) == []

    def test_empty_frame_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            "backend.api.deps._scoreboard", lambda *a, **k: _FakeBoard(pd.DataFrame())
        )
        assert wrk._build_season_stats([1]) == []

    def test_missing_categories_are_skipped_not_fatal(self, monkeypatch):
        partial = pd.DataFrame({"Team": ["Alpha"], "PTS": [100.0]})
        monkeypatch.setattr(
            "backend.api.deps._scoreboard", lambda *a, **k: _FakeBoard(partial)
        )
        rows = wrk._build_season_stats([1])
        assert rows[0]["PTS"] == 100.0
        assert "reb_rank" not in rows[0]
