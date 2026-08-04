"""Playoff-weeks schedule planner (W-1): derivation, counting, endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.league.playoff_schedule import (
    build_playoff_schedule,
    count_games_by_team,
    derive_playoff_weeks,
    playoff_rounds,
)

# A 23-week calendar: reg season 1-19, playoffs 20-23.
CAL = {w: {"start": f"2026-{3 if w > 17 else 2:02d}-{(w % 27) + 1:02d}",
           "end": f"2026-{3 if w > 17 else 2:02d}-{(w % 27) + 2:02d}"}
       for w in range(1, 24)}


class TestDerivation:
    def test_standard_4_team_2_week_rounds(self):
        # 4 teams -> 2 rounds; 2-week rounds -> weeks 20..23.
        weeks = derive_playoff_weeks(
            reg_season_count=19, playoff_team_count=4,
            playoff_matchup_period_length=2, calendar_weeks=CAL,
        )
        assert weeks == [20, 21, 22, 23]

    def test_six_teams_gets_three_rounds(self):
        # 6 teams -> ceil(log2(6)) = 3 rounds (byes); 1-week rounds -> 20..22.
        assert playoff_rounds(6) == 3
        weeks = derive_playoff_weeks(
            reg_season_count=19, playoff_team_count=6,
            playoff_matchup_period_length=1, calendar_weeks=CAL,
        )
        assert weeks == [20, 21, 22]

    def test_oversized_settings_clamped_to_calendar(self):
        # 8 teams x 3-week rounds would claim weeks 20..28 — calendar ends at 23.
        weeks = derive_playoff_weeks(
            reg_season_count=19, playoff_team_count=8,
            playoff_matchup_period_length=3, calendar_weeks=CAL,
        )
        assert weeks == [20, 21, 22, 23]

    def test_unknown_playoff_shape_falls_back_to_post_reg_weeks(self):
        weeks = derive_playoff_weeks(
            reg_season_count=19, playoff_team_count=None,
            playoff_matchup_period_length=None, calendar_weeks=CAL,
        )
        assert weeks == [20, 21, 22, 23]

    def test_missing_reg_season_is_empty_not_a_guess(self):
        assert derive_playoff_weeks(
            reg_season_count=None, playoff_team_count=4,
            playoff_matchup_period_length=2, calendar_weeks=CAL,
        ) == []


def _epoch_ms(iso: str) -> int:
    import datetime as dt
    d = dt.datetime.fromisoformat(iso + "T18:00:00+00:00")
    return int(d.timestamp() * 1000)


def _pro_team(abbrev: str, game_dates: list[str], *, dupe_across_periods: bool = False):
    games = [{"id": f"{abbrev}-{d}", "date": _epoch_ms(d)} for d in game_dates]
    by_period = {str(i + 1): [g] for i, g in enumerate(games)}
    if dupe_across_periods and games:
        by_period[str(len(games) + 1)] = [games[0]]  # same game, second bucket
    return {"abbrev": abbrev, "proGamesByScoringPeriod": by_period}


WINDOWS = {
    20: {"start": "2026-03-01", "end": "2026-03-07"},
    21: {"start": "2026-03-08", "end": "2026-03-14"},
}


class TestCounting:
    def test_counts_games_inside_windows_only(self):
        teams = count_games_by_team(
            [_pro_team("DEN", ["2026-03-02", "2026-03-04", "2026-03-09", "2026-02-20"])],
            WINDOWS,
        )
        den = teams[0]
        assert den["pro_team"] == "DEN"
        assert den["games_by_week"] == {"20": 2, "21": 1}
        assert den["total"] == 3  # the February game is outside the windows

    def test_dedupes_same_game_across_scoring_period_buckets(self):
        teams = count_games_by_team(
            [_pro_team("BOS", ["2026-03-02"], dupe_across_periods=True)], WINDOWS
        )
        assert teams[0]["total"] == 1

    def test_sorted_most_games_first(self):
        teams = count_games_by_team(
            [
                _pro_team("MIN", ["2026-03-02"]),
                _pro_team("OKC", ["2026-03-02", "2026-03-03", "2026-03-09"]),
            ],
            WINDOWS,
        )
        assert [t["pro_team"] for t in teams] == ["OKC", "MIN"]


class TestBuild:
    def test_missing_settings_is_honest_empty(self):
        out = build_playoff_schedule(
            settings=None, calendar_weeks=CAL, pro_schedule={"settings": {"proTeams": []}}
        )
        assert out == {"playoff_weeks": [], "teams": [], "reason": "settings_unavailable"}

    def test_missing_schedule_is_honest_empty_with_weeks(self):
        out = build_playoff_schedule(
            settings={"reg_season_count": 19, "playoff_team_count": 4,
                      "playoff_matchup_period_length": 2},
            calendar_weeks=CAL,
            pro_schedule=None,
        )
        assert out["playoff_weeks"] == [20, 21, 22, 23]
        assert out["teams"] == []
        assert out["reason"] == "schedule_unavailable"


class TestEndpoint:
    def test_endpoint_returns_payload(self, monkeypatch):
        monkeypatch.setattr(
            "backend.api.routers.league._snapshot_read",
            lambda phase, **k: (
                {"reg_season_count": 19, "playoff_team_count": 4,
                 "playoff_matchup_period_length": 2},
                "2026-07-26T00:00:00Z",
            ),
        )

        class _Req:
            def get_pro_schedule(self):
                return {"settings": {"proTeams": [
                    _pro_team("DEN", ["2026-03-02", "2026-03-04"]),
                ]}}

        class _League:
            espn_request = _Req()

        class _Handles:
            league = _League()

        monkeypatch.setattr("backend.api.routers.league._handles", lambda: _Handles())
        monkeypatch.setattr(
            "backend.league.data_feed.get_matchup_weeks",
            lambda season_year=None: {
                19: {"start": "2026-02-20", "end": "2026-02-26"},
                20: {"start": "2026-03-01", "end": "2026-03-07"},
                21: {"start": "2026-03-08", "end": "2026-03-14"},
                22: {"start": "2026-03-15", "end": "2026-03-21"},
                23: {"start": "2026-03-22", "end": "2026-03-28"},
            },
        )

        client = TestClient(app)
        resp = client.get("/leagues/test-league/playoff-schedule")
        assert resp.status_code == 200
        body = resp.json()
        assert body["playoff_weeks"] == [20, 21, 22, 23]
        assert body["teams"][0]["pro_team"] == "DEN"
        assert body["teams"][0]["total"] == 2

    def test_espn_outage_degrades_not_500(self, monkeypatch):
        monkeypatch.setattr(
            "backend.api.routers.league._snapshot_read",
            lambda phase, **k: (
                {"reg_season_count": 19, "playoff_team_count": 4,
                 "playoff_matchup_period_length": 2},
                None,
            ),
        )

        def _boom():
            raise RuntimeError("ESPN down")

        monkeypatch.setattr("backend.api.routers.league._handles", _boom)
        client = TestClient(app)
        resp = client.get("/leagues/test-league/playoff-schedule")
        assert resp.status_code == 200
        assert resp.json()["reason"] == "schedule_unavailable"
