"""Per-week matchup snapshots: store methods, assemble read-path, worker backfill.

Fixes the bug where any unpublished week's matchup view rendered the single
rolling `scoreboard` phase (latest week only) — so past weeks showed the
current scoreboard, identically. Now each week has its own immutable row.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.recaps import assemble as asm
from backend.recaps.store import RecapStore
from backend.worker import refresh as wrk


# ── Store methods ─────────────────────────────────────────────────────────────


class TestStoreMethods:
    def test_get_week_scoreboard_queries_by_week(self, monkeypatch):
        captured = {}

        def fake_request(self, method, path, *, params=None, json=None, prefer=None):
            captured["path"] = path
            captured["params"] = params
            return [{"payload_json": [{"home_team": "A"}], "fetched_at": "t", "week": 19}]

        monkeypatch.setattr(RecapStore, "_request", fake_request)
        store = RecapStore(url="http://x", service_role_key="k")
        row = store.get_week_scoreboard(league_id="L1", season=2026, week=19)

        assert captured["path"] == "league_week_scoreboards"
        assert captured["params"]["week"] == "eq.19"
        assert captured["params"]["league_id"] == "eq.L1"
        assert row["payload_json"] == [{"home_team": "A"}]

    def test_get_week_scoreboard_returns_none_when_absent(self, monkeypatch):
        monkeypatch.setattr(RecapStore, "_request", lambda *a, **k: [])
        store = RecapStore(url="http://x", service_role_key="k")
        assert store.get_week_scoreboard(league_id="L1", season=2026, week=5) is None

    def test_list_week_scoreboard_weeks_returns_int_set(self, monkeypatch):
        monkeypatch.setattr(
            RecapStore,
            "_request",
            lambda *a, **k: [{"week": 1}, {"week": 2}, {"week": None}, {"week": 3}],
        )
        store = RecapStore(url="http://x", service_role_key="k")
        assert store.list_week_scoreboard_weeks(league_id="L1", season=2026) == {1, 2, 3}


# ── Worker: per-week upsert + backfill ────────────────────────────────────────


class TestWorkerHelpers:
    def test_upsert_week_scoreboard_targets_week_conflict(self):
        store = MagicMock()
        wrk._upsert_week_scoreboard(store, "L1", 2026, 7, [{"home_team": "A"}])
        args, kwargs = store._request.call_args
        assert args[:2] == ("POST", "league_week_scoreboards")
        assert kwargs["params"]["on_conflict"] == "league_id,season,week"
        assert kwargs["json"]["week"] == 7
        assert kwargs["json"]["payload_json"] == [{"home_team": "A"}]

    def test_backfill_fetches_missing_weeks_only(self, monkeypatch):
        store = MagicMock()
        store.list_week_scoreboard_weeks.return_value = {1, 2}  # already stored

        fetched: list[int] = []

        def fake_scoreboard(handles, scoring_period=None):
            fetched.append(scoring_period)
            import pandas as pd
            return pd.DataFrame([{"stat": "PTS", "home_team": f"H{scoring_period}"}])

        monkeypatch.setattr(
            "backend.league.data_feed.get_current_scoreboard", fake_scoreboard
        )

        # current week = 5 → weeks 1..4 considered; 1,2 skipped → fetch 3,4.
        summary = wrk._backfill_week_scoreboards(store, object(), "L1", 2026, 5)

        assert sorted(fetched) == [3, 4]
        assert store._request.call_count == 2  # one upsert per filled week
        assert "filled 2" in summary and "skipped 2" in summary

    def test_backfill_isolates_a_failing_week(self, monkeypatch):
        store = MagicMock()
        store.list_week_scoreboard_weeks.return_value = set()

        def fake_scoreboard(handles, scoring_period=None):
            if scoring_period == 2:
                raise RuntimeError("ESPN hiccup on week 2")
            import pandas as pd
            return pd.DataFrame([{"stat": "PTS", "home_team": "H"}])

        monkeypatch.setattr(
            "backend.league.data_feed.get_current_scoreboard", fake_scoreboard
        )

        # current week = 4 → weeks 1,2,3; week 2 fails, 1 and 3 still fill.
        summary = wrk._backfill_week_scoreboards(store, object(), "L1", 2026, 4)
        assert "filled 2" in summary and "failed 1" in summary


# ── Assemble read-path prefers the per-week scoreboard ────────────────────────


def _league() -> dict:
    return {"id": "L1", "slug": "test", "name": "Test", "visibility": "public"}


class TestAssembleReadPath:
    def _patch_phases(self, monkeypatch, latest_scoreboard):
        """Stored-read path: get_all_phases returns the rolling latest state."""
        monkeypatch.setattr(
            RecapStore,
            "get_all_phases",
            lambda self, *, league_id, season: {
                "standings": {"payload_json": []},
                "power_rankings": {"payload_json": []},
                "scoreboard": {"payload_json": latest_scoreboard, "fetched_at": "t"},
                "transactions": {"payload_json": []},
                "season_stats": {"payload_json": []},
            },
        )

    def test_prefers_per_week_scoreboard_for_requested_week(self, monkeypatch):
        # Latest (current-week) scoreboard names one matchup...
        self._patch_phases(
            monkeypatch,
            [{"stat": "PTS", "home_team": "Latest Home", "away_team": "Latest Away",
              "current_home_score": 5, "current_away_score": 4}],
        )
        # ...but the requested week's stored scoreboard names a different one.
        seen = {}

        def fake_week_sb(self, *, league_id, season, week):
            seen["week"] = week
            return {"payload_json": [
                {"stat": "PTS", "home_team": "Week19 Home", "away_team": "Week19 Away",
                 "current_home_score": 9, "current_away_score": 0},
            ]}

        monkeypatch.setattr(RecapStore, "get_week_scoreboard", fake_week_sb)

        snap = asm.assemble_weekly_snapshot(
            league=_league(), season=2026, week=19,
            week_start="2026-02-01", week_end="2026-02-07",
        )

        assert seen["week"] == 19  # read for the REQUESTED week
        teams = {m["home_team"] for m in snap.matchups}
        assert "Week19 Home" in teams
        assert "Latest Home" not in teams

    def test_falls_back_to_latest_when_week_not_backfilled(self, monkeypatch):
        self._patch_phases(
            monkeypatch,
            [{"stat": "PTS", "home_team": "Latest Home", "away_team": "Latest Away",
              "current_home_score": 5, "current_away_score": 4}],
        )
        monkeypatch.setattr(
            RecapStore, "get_week_scoreboard",
            lambda self, *, league_id, season, week: None,  # not backfilled
        )

        snap = asm.assemble_weekly_snapshot(
            league=_league(), season=2026, week=3,
            week_start="2026-01-01", week_end="2026-01-07",
        )
        teams = {m["home_team"] for m in snap.matchups}
        assert "Latest Home" in teams
