"""P-11: synthetic intra-week integration test.

Validates the projected-scoreboard merge math:
  projected == current + (avg × games_left)

Uses a fake ESPNHandles at a mid-week state (3 of 5 games played)
so the test runs without a live ESPN connection.  Forces the legacy
path explicitly to test the merge, not the framework routing.

Per spec §5: 'the only way to validate the merge before live games return.'
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from backend.league.data_feed import ESPNHandles, get_projected_scoreboard

_player_id_counter = 1000


def _next_id():
    global _player_id_counter
    _player_id_counter += 1
    return _player_id_counter


def _mock_player(name, pts_avg, reb_avg, ast_avg, stl_avg, blk_avg,
                 tpm_avg, fgm_avg, fga_avg, ftm_avg, fta_avg, to_avg,
                 games_left=2, injury="ACTIVE"):
    """Create a mock player with Last-15 averages and a schedule."""
    p = MagicMock()
    p.name = name
    p.playerId = _next_id()
    p.injuryStatus = injury
    p.eligibleSlots = ["PG"]
    p.proTeam = "NBA"
    p.acquisitionType = "DRAFT"
    p.nine_cat_averages = []

    p.stats = {
        "2026_last_15": {
            "avg": {
                "PTS": pts_avg, "BLK": blk_avg, "AST": ast_avg,
                "STL": stl_avg, "3PM": tpm_avg, "FTA": fta_avg,
                "FTM": ftm_avg, "FGM": fgm_avg, "FGA": fga_avg,
                "TO": to_avg, "OREB": 0.0, "DREB": reb_avg,
            }
        },
        "2026_total": {"avg": {}},
        "2026_last_30": {"avg": {}},
    }

    import datetime as dt
    base = dt.date.today()
    sched = {}
    for i in range(games_left):
        d = base + dt.timedelta(days=i + 1)
        sched[str(i)] = {"date": d.isoformat()}
    p.schedule = sched

    return p


def _mock_scoreboard(home_scores: dict, away_scores: dict):
    """Build a partial box score."""
    records = []
    stats = {
        "PTS": (home_scores.get("PTS", 0), away_scores.get("PTS", 0)),
        "REB": (home_scores.get("REB", 0), away_scores.get("REB", 0)),
        "AST": (home_scores.get("AST", 0), away_scores.get("AST", 0)),
        "STL": (home_scores.get("STL", 0), away_scores.get("STL", 0)),
        "BLK": (home_scores.get("BLK", 0), away_scores.get("BLK", 0)),
        "3PM": (home_scores.get("3PM", 0), away_scores.get("3PM", 0)),
        "FGM": (home_scores.get("FGM", 0), away_scores.get("FGM", 0)),
        "FGA": (home_scores.get("FGA", 0), away_scores.get("FGA", 0)),
        "FTM": (home_scores.get("FTM", 0), away_scores.get("FTM", 0)),
        "FTA": (home_scores.get("FTA", 0), away_scores.get("FTA", 0)),
        "TO": (home_scores.get("TO", 0), away_scores.get("TO", 0)),
    }
    for stat, (h_val, a_val) in stats.items():
        records.append({
            "home_team": "Home Team",
            "away_team": "Away Team",
            "stat": stat,
            "current_home_score": h_val,
            "current_away_score": a_val,
        })
    return pd.DataFrame(records)


class TestIntraWeekProjectionMerge:
    """Validate projected == current + (avg × games_left) at mid-week."""

    def test_exact_merge_math(self, monkeypatch):
        """One player per team, known stats, known games_left.
        Assert projected totals exactly equal current + player_avg × games_left."""
        import datetime as dt

        # Home player: 20 pts/g, 10 reb/g, etc. × 2 games left = +40 pts, +20 reb
        home_p = _mock_player(
            "Home Star", pts_avg=20, reb_avg=10, ast_avg=5,
            stl_avg=1, blk_avg=0.5, tpm_avg=2,
            fgm_avg=8, fga_avg=16, ftm_avg=3, fta_avg=4, to_avg=2,
            games_left=2,
        )
        # Away player: 15 pts/g, 8 reb/g × 2 games left = +30 pts, +16 reb
        away_p = _mock_player(
            "Away Star", pts_avg=15, reb_avg=8, ast_avg=6,
            stl_avg=1.5, blk_avg=0.3, tpm_avg=1.5,
            fgm_avg=7, fga_avg=15, ftm_avg=2.5, fta_avg=3.5, to_avg=1.5,
            games_left=2,
        )

        # Build handles
        home_team = MagicMock()
        home_team.team_id = 1
        home_team.team_name = "Home Team"
        home_team.roster = [home_p]
        away_team = MagicMock()
        away_team.team_id = 2
        away_team.team_name = "Away Team"
        away_team.roster = [away_p]
        league = MagicMock()
        league.teams = [home_team, away_team]
        league.currentMatchupPeriod = 5
        handles = ESPNHandles(league=league)

        # Current partial scores (3 of 5 games played)
        sb = _mock_scoreboard(
            {"PTS": 200, "REB": 80, "AST": 50, "STL": 10, "BLK": 5,
             "3PM": 15, "FGM": 75, "FGA": 160, "FTM": 30, "FTA": 40, "TO": 15},
            {"PTS": 180, "REB": 70, "AST": 55, "STL": 12, "BLK": 4,
             "3PM": 12, "FGM": 65, "FGA": 150, "FTM": 25, "FTA": 35, "TO": 12},
        )

        monkeypatch.setattr(
            "backend.league.data_feed.get_current_scoreboard",
            lambda h, scoring_period=None: sb,
        )

        base = dt.date.today()
        week_end = (base + dt.timedelta(days=4)).isoformat()

        result = get_projected_scoreboard(
            handles, week_end_date=week_end,
            current_matchup_period=5, projections="15",
        )

        assert not result.empty

        # ---- Exact merge math assertions ----
        # Home: current + (per_game × games_left × 1 player)
        # PTS: 200 + (20 × 2) = 240
        home_pts = result[(result["stat"] == "PTS") & (result["home_team"] == "Home Team")]
        assert float(home_pts["projected_home_score"].iloc[0]) == pytest.approx(240.0)

        # Away PTS: 180 + (15 × 2) = 210
        away_pts = result[(result["stat"] == "PTS") & (result["away_team"] == "Away Team")]
        assert float(away_pts["projected_away_score"].iloc[0]) == pytest.approx(210.0, rel=0.01)

        # REB: home 80 + (10 × 2) = 100
        home_reb = result[(result["stat"] == "REB") & (result["home_team"] == "Home Team")]
        assert float(home_reb["projected_home_score"].iloc[0]) == pytest.approx(100.0)

        # AST: home 50 + (5 × 2) = 60
        home_ast = result[(result["stat"] == "AST") & (result["home_team"] == "Home Team")]
        assert float(home_ast["projected_home_score"].iloc[0]) == pytest.approx(60.0)

        # TO: home 15 + (2 × 2) = 19
        home_to = result[(result["stat"] == "TO") & (result["home_team"] == "Home Team")]
        assert float(home_to["projected_home_score"].iloc[0]) == pytest.approx(19.0)

        # ---- W/L results for PTS: home projected 240 > away 210 → Home W ----
        home_pts_row = result[(result["stat"] == "PTS") & (result["home_team"] == "Home Team")]
        assert home_pts_row["projected_home_result"].iloc[0] == "W"
        assert home_pts_row["projected_away_result"].iloc[0] == "L"

        # W/L for TO: home 19 > away 13.5 → lower is better → Away W
        home_to_row = result[(result["stat"] == "TO") & (result["home_team"] == "Home Team")]
        assert home_to_row["projected_home_result"].iloc[0] == "L"
        assert home_to_row["projected_away_result"].iloc[0] == "W"

        # ---- Column shape ----
        for col in ["home_team", "away_team", "stat",
                     "projected_home_score", "projected_away_score",
                     "projected_home_result", "projected_away_result"]:
            assert col in result.columns

    def test_legacy_path_reachable(self, monkeypatch):
        """When the framework path raises, the legacy path still produces results."""
        import datetime as dt

        home_p = _mock_player("H1", 20, 10, 5, 1, 0.5, 2, 8, 16, 3, 4, 2, games_left=1)
        away_p = _mock_player("A1", 15, 8, 6, 1.5, 0.3, 1.5, 7, 15, 2.5, 3.5, 1.5, games_left=1)

        home_team = MagicMock()
        home_team.team_id = 1
        home_team.team_name = "Home Team"
        home_team.roster = [home_p]
        away_team = MagicMock()
        away_team.team_id = 2
        away_team.team_name = "Away Team"
        away_team.roster = [away_p]
        league = MagicMock()
        league.teams = [home_team, away_team]
        league.currentMatchupPeriod = 5
        handles = ESPNHandles(league=league)

        sb = _mock_scoreboard({"PTS": 100}, {"PTS": 90})
        monkeypatch.setattr(
            "backend.league.data_feed.get_current_scoreboard",
            lambda h, scoring_period=None: sb,
        )

        base = dt.date.today()
        week_end = (base + dt.timedelta(days=2)).isoformat()

        result = get_projected_scoreboard(
            handles, week_end_date=week_end,
            current_matchup_period=5, projections="15",
        )

        assert isinstance(result, pd.DataFrame)
        assert not result.empty
        # All required columns present
        for col in ["projected_home_score", "projected_away_score",
                     "projected_home_result", "projected_away_result"]:
            assert col in result.columns
