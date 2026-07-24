"""_live_power_rankings must emit the field names its consumers actually
read (StandingsTab, PowerRankingsTab) — verified against a real bug: the
function previously emitted only `Team`/`Rank`/`PTS_rank` (capitalized,
un-normalized), while the frontend reads `team`/`rank`/`pts_rank` and
`pr['Win % Ratio']`/`allplay_win_pct`, none of which existed on the entry
dict. StandingsTab's team-name join (`rankMap` keyed on `r.team`) silently
matched nothing, so Luck/PR/±/All-Play% all rendered as 0/blank for every
team; PowerRankingsTab's category-rank pills read `pts_rank` etc. and got
nothing for the same reason.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.recaps import assemble as asm


class _FakeTeam:
    def __init__(self, team_name, wins, losses, ties=0):
        self.team_name = team_name
        self.wins = wins
        self.losses = losses
        self.ties = ties


class _FakeLeague:
    def __init__(self, teams):
        self.teams = teams


class _FakeBoard:
    """Stands in for WeeklyScoreboard.all_play()."""

    def __init__(self, full_df: pd.DataFrame, recent_df: pd.DataFrame | None = None):
        self._full = full_df
        self._recent = recent_df if recent_df is not None else full_df

    def all_play(self, weeks, **kwargs):
        # Distinguish the "recent" call (a narrower weeks slice) from "full".
        return self._recent if len(weeks) < 3 else self._full


def _sample_full_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Team": ["Alpha", "Beta"],
            "Total Win %": [70.0, 30.0],   # all-play (schedule-adjusted)
            "Actual Win %": [90.0, 10.0],  # real head-to-head record
            "PTS": [110.0, 90.0],
            "REB": [45.0, 40.0],
            "AST": [25.0, 20.0],
            "STL": [8.0, 6.0],
            "BLK": [5.0, 3.0],
            "3PM": [12.0, 10.0],
            "FG%": [0.48, 0.44],
            "FT%": [0.82, 0.78],
            "TO": [13.0, 15.0],
        }
    )


@pytest.fixture(autouse=True)
def _patch_league_and_board(monkeypatch):
    teams = [
        _FakeTeam("Alpha", wins=9, losses=1),
        _FakeTeam("Beta", wins=1, losses=9),
    ]
    board = _FakeBoard(_sample_full_df())
    monkeypatch.setattr("backend.api.deps._my_league", lambda *a, **k: _FakeLeague(teams))
    monkeypatch.setattr("backend.api.deps._scoreboard", lambda *a, **k: board)


class TestFieldShape:
    def test_emits_lowercase_team_and_rank(self):
        """Fixes the StandingsTab rankMap join, which keyed on `r.team`."""
        result = asm._live_power_rankings("1", recent_weeks=1)
        assert len(result) == 2
        for entry in result:
            assert isinstance(entry["team"], str) and entry["team"]
            assert entry["rank"] == entry["Rank"]  # lowercase alias, same value

    def test_emits_allplay_and_actual_win_pct(self):
        result = asm._live_power_rankings("1", recent_weeks=1)
        alpha = next(e for e in result if e["team"] == "Alpha")
        assert alpha["allplay_win_pct"] == 70.0
        assert alpha["actual_win_pct"] == 90.0

    def test_lowercase_category_rank_keys_present(self):
        """PowerRankingsTab reads pts_rank/fg_pct_rank/to_rank (lowercase),
        not the legacy PTS_rank/FG%_rank the function used to emit only."""
        result = asm._live_power_rankings("1", recent_weeks=1)
        alpha = next(e for e in result if e["team"] == "Alpha")
        for key in ("pts_rank", "reb_rank", "fg_pct_rank", "ft_pct_rank", "to_rank"):
            assert key in alpha, f"missing {key}"
        # Legacy uppercase keys still present too (back-compat).
        assert "PTS_rank" in alpha


class TestLuckRatio:
    def test_win_pct_ratio_is_actual_over_allplay(self):
        result = asm._live_power_rankings("1", recent_weeks=1)
        alpha = next(e for e in result if e["team"] == "Alpha")
        beta = next(e for e in result if e["team"] == "Beta")
        # Alpha: 90/70 > 1 -> overperforming (lucky).
        assert alpha["Win % Ratio"] == pytest.approx(90.0 / 70.0, abs=1e-3)
        # Beta: 10/30 < 1 -> underperforming (unlucky).
        assert beta["Win % Ratio"] == pytest.approx(10.0 / 30.0, abs=1e-3)
        assert alpha["Win % Ratio"] > 1.0
        assert beta["Win % Ratio"] < 1.0

    def test_zero_allplay_defaults_to_neutral_ratio(self, monkeypatch):
        df = _sample_full_df()
        df["Total Win %"] = [0.0, 0.0]
        board = _FakeBoard(df)
        monkeypatch.setattr("backend.api.deps._scoreboard", lambda *a, **k: board)
        result = asm._live_power_rankings("1", recent_weeks=1)
        assert all(e["Win % Ratio"] == 1.0 for e in result)


class TestRankChangeDefault:
    def test_single_week_defaults_rank_change_to_zero(self):
        """<2 weeks: no prior-week comparison is possible; must not be
        undefined (StandingsTab renders `Number(pr.rank_change ?? 0)`)."""
        result = asm._live_power_rankings("1", recent_weeks=1)
        assert all(e["rank_change"] == 0 for e in result)

    def test_multi_week_sets_rank_change_from_movement(self, monkeypatch):
        # Two full-weeks calls: "full" (>=3 weeks slice check uses len<3, so
        # pass 2 elements for "recent" and rely on the >=2-week prior-rank path
        # triggering off the requested week list length, not the mock).
        result = asm._live_power_rankings("1,2", recent_weeks=1)
        for entry in result:
            assert entry["rank_change"] == entry["Movement"]
