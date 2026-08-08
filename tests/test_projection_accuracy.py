"""
FCP Projections M-2 — tests for the projection accuracy scoreboard.

Per the spec's test plan, the backtest harness itself is tested against a
synthetic season with known answers: a perfect projection must score
MAE 0 / rank-corr 1, a constant offset must reproduce exactly as MAE and
bias, and an inverted projection must score rank-corr −1.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.projections.accuracy import (
    CATEGORIES,
    actual_team_totals,
    build_accuracy_scoreboard,
    projected_team_totals,
    roster_map_from_rows,
    score_week,
)
from backend.projections.adapter import PlayerProjection
from backend.projections.store import ESPN_VIRTUAL_SET_ID, ProjectionStore
from backend.recaps.store import RecapStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _player(
    key: str,
    team: str | None,
    *,
    games: float = 3.0,
    pts: float = 20.0,
    reb: float = 5.0,
    ast: float = 4.0,
    fga: float = 15.0,
    fg_pct: float = 0.5,
    fta: float = 4.0,
    ft_pct: float = 0.8,
) -> PlayerProjection:
    return PlayerProjection(
        player_key=key,
        display_name=key.title(),
        roster_team=team,
        games=games,
        pts_pg=pts,
        reb_pg=reb,
        ast_pg=ast,
        stl_pg=1.0,
        blk_pg=0.5,
        tpm_pg=2.0,
        to_pg=2.5,
        fga_pg=fga,
        fg_pct=fg_pct,
        fta_pg=fta,
        ft_pct=ft_pct,
    )


def _scoreboard_payload(
    team_stats: dict[str, dict[str, float]],
    *,
    gp: dict[str, float] | None = None,
) -> list[dict]:
    """Build a stored-scoreboard-shaped payload from team→stat→value.

    Pairs teams into matchups in insertion order (home, away)."""
    teams = list(team_stats)
    rows: list[dict] = []
    for i in range(0, len(teams) - 1, 2):
        home, away = teams[i], teams[i + 1]
        stats = set(team_stats[home]) | set(team_stats[away])
        for stat in sorted(stats):
            rows.append({
                "home_team": home,
                "away_team": away,
                "stat": stat,
                "current_home_score": team_stats[home].get(stat),
                "current_away_score": team_stats[away].get(stat),
                "home_games_played": (gp or {}).get(home),
                "away_games_played": (gp or {}).get(away),
            })
    return rows


# ---------------------------------------------------------------------------
# projected_team_totals
# ---------------------------------------------------------------------------


class TestProjectedTeamTotals:
    def test_rate_times_games(self):
        rows = [
            _player("a", "Team One", games=3, pts=20.0),
            _player("b", "Team One", games=2, pts=10.0),
        ]
        totals, skipped = projected_team_totals(rows)
        assert skipped == 0
        assert totals["Team One"]["PTS"] == pytest.approx(80.0)  # 60 + 20
        assert totals["Team One"]["GP"] == pytest.approx(5.0)

    def test_fg_pct_is_attempt_weighted(self):
        """A high-volume 40% shooter drags the team FG% below the naive
        average of percentages — makes/attempts, never averaged pcts."""
        rows = [
            _player("chucker", "T", games=1, fga=30.0, fg_pct=0.40),
            _player("efficient", "T", games=1, fga=10.0, fg_pct=0.60),
        ]
        totals, _ = projected_team_totals(rows)
        # (30*0.4 + 10*0.6) / 40 = 18/40 = 0.45, not (0.4+0.6)/2 = 0.5
        assert totals["T"]["FG%"] == pytest.approx(0.45)

    def test_roster_map_overrides_and_fills(self):
        """roster_map wins over embedded roster_team; rows without either
        are skipped and counted."""
        rows = [
            _player("mapped", None),
            _player("embedded", "Team B"),
            _player("orphan", None),
        ]
        totals, skipped = projected_team_totals(rows, {"mapped": "Team A"})
        assert "Team A" in totals
        assert "Team B" in totals
        assert skipped == 1

    def test_zero_games_contributes_nothing(self):
        rows = [_player("out", "T", games=0, pts=30.0)]
        totals, _ = projected_team_totals(rows)
        assert totals["T"]["PTS"] == 0.0
        assert "FG%" not in totals["T"]  # no attempts → no derived pct

    def test_roster_map_from_rows(self):
        rows = [_player("a", "Team One"), _player("b", None)]
        assert roster_map_from_rows(rows) == {"a": "Team One"}


# ---------------------------------------------------------------------------
# actual_team_totals
# ---------------------------------------------------------------------------


class TestActualTeamTotals:
    def test_parses_home_and_away(self):
        payload = _scoreboard_payload({
            "Alpha": {"PTS": 500.0, "REB": 200.0},
            "Beta": {"PTS": 480.0, "REB": 210.0},
        })
        totals = actual_team_totals(payload)
        assert totals["Alpha"]["PTS"] == 500.0
        assert totals["Beta"]["REB"] == 210.0

    def test_bye_and_missing_values_skipped(self):
        payload = [
            {
                "home_team": "Alpha",
                "away_team": "Bye",
                "stat": "PTS",
                "current_home_score": 500.0,
                "current_away_score": None,
            }
        ]
        totals = actual_team_totals(payload)
        assert totals["Alpha"]["PTS"] == 500.0
        assert "Bye" not in totals

    def test_gp_captured_once_per_team(self):
        payload = _scoreboard_payload(
            {"Alpha": {"PTS": 500.0}, "Beta": {"PTS": 480.0}},
            gp={"Alpha": 38.0, "Beta": 41.0},
        )
        totals = actual_team_totals(payload)
        assert totals["Alpha"]["GP"] == 38.0
        assert totals["Beta"]["GP"] == 41.0

    def test_stat_names_uppercased(self):
        payload = [
            {
                "home_team": "Alpha",
                "away_team": "Beta",
                "stat": "fg%",
                "current_home_score": 0.48,
                "current_away_score": 0.46,
            }
        ]
        totals = actual_team_totals(payload)
        assert totals["Alpha"]["FG%"] == 0.48


# ---------------------------------------------------------------------------
# score_week — synthetic season with known answers
# ---------------------------------------------------------------------------


def _teams(values: dict[str, float], cat: str = "PTS") -> dict[str, dict[str, float]]:
    return {team: {cat: v} for team, v in values.items()}


class TestScoreWeek:
    def test_perfect_projection(self):
        actual = _teams({"A": 500.0, "B": 480.0, "C": 450.0, "D": 430.0})
        score = score_week(actual, actual)
        pts = score["per_category"]["PTS"]
        assert pts["mae"] == 0.0
        assert pts["bias"] == 0.0
        assert pts["rank_corr"] == 1.0
        assert score["teams_matched"] == 4

    def test_constant_offset_reproduces_as_mae_and_bias(self):
        actual = _teams({"A": 500.0, "B": 480.0, "C": 450.0})
        projected = _teams({"A": 505.0, "B": 485.0, "C": 455.0})
        pts = score_week(projected, actual)["per_category"]["PTS"]
        assert pts["mae"] == 5.0
        assert pts["bias"] == 5.0        # signed: over-projection
        assert pts["rank_corr"] == 1.0   # order preserved

    def test_inverted_projection_rank_corr_minus_one(self):
        actual = _teams({"A": 500.0, "B": 480.0, "C": 450.0, "D": 430.0})
        projected = _teams({"A": 430.0, "B": 450.0, "C": 480.0, "D": 500.0})
        pts = score_week(projected, actual)["per_category"]["PTS"]
        assert pts["rank_corr"] == -1.0

    def test_under_projection_negative_bias(self):
        actual = _teams({"A": 100.0, "B": 200.0, "C": 300.0})
        projected = _teams({"A": 90.0, "B": 190.0, "C": 290.0})
        pts = score_week(projected, actual)["per_category"]["PTS"]
        assert pts["bias"] == -10.0

    def test_mae_pct_relative_to_actual_scale(self):
        actual = _teams({"A": 100.0, "B": 100.0, "C": 100.0})
        projected = _teams({"A": 110.0, "B": 110.0, "C": 110.0})
        pts = score_week(projected, actual)["per_category"]["PTS"]
        assert pts["mae_pct"] == pytest.approx(0.10)

    def test_rank_corr_none_below_three_teams(self):
        actual = _teams({"A": 500.0, "B": 480.0})
        pts = score_week(actual, actual)["per_category"]["PTS"]
        assert pts["rank_corr"] is None
        assert pts["mae"] == 0.0

    def test_partial_team_overlap_shrinks_coverage(self):
        actual = _teams({"A": 500.0, "B": 480.0, "C": 450.0})
        projected = _teams({"A": 500.0, "B": 480.0, "Renamed C": 450.0})
        score = score_week(projected, actual)
        assert score["teams_matched"] == 2
        assert score["teams_total"] == 3

    def test_gp_scored_when_actual_tracks_it(self):
        actual = {"A": {"PTS": 500.0, "GP": 40.0}, "B": {"PTS": 480.0, "GP": 38.0}}
        projected = {"A": {"PTS": 500.0, "GP": 42.0}, "B": {"PTS": 480.0, "GP": 38.0}}
        score = score_week(projected, actual)
        assert score["per_category"]["GP"]["mae"] == 1.0

    def test_gp_absent_when_league_does_not_track_it(self):
        actual = _teams({"A": 500.0, "B": 480.0})
        projected = {"A": {"PTS": 500.0, "GP": 40.0}, "B": {"PTS": 480.0, "GP": 38.0}}
        assert "GP" not in score_week(projected, actual)["per_category"]


# ---------------------------------------------------------------------------
# ProjectionStore — snapshot support (M-2a)
# ---------------------------------------------------------------------------


class TestStoreSnapshotSupport:
    def test_activate_false_leaves_active_untouched(self, tmp_path):
        store = ProjectionStore(tmp_path)
        active = store.save_set([_player("a", "T")], "bbm", "week", week=3)
        store.save_set(
            [_player("b", "T")], "espn", "week",
            week=3, league_slug="fcp", activate=False,
        )
        assert store._manifest.active["week"] == active.set_id

    def test_league_slug_round_trips_through_manifest(self, tmp_path):
        store = ProjectionStore(tmp_path)
        store.save_set(
            [_player("a", "T")], "espn", "week",
            week=3, league_slug="fcp", activate=False,
        )
        reloaded = ProjectionStore(tmp_path)
        snap = [s for s in reloaded.list_sets(horizon="week") if s.week == 3]
        assert snap[0].league_slug == "fcp"

    def test_missing_league_slug_defaults_none(self, tmp_path):
        """Pre-M-2 manifests have no league_slug key — must load as None."""
        store = ProjectionStore(tmp_path)
        store.save_set([_player("a", "T")], "bbm", "week", week=1)
        manifest = (tmp_path / "manifest.json").read_text()
        import json
        data = json.loads(manifest)
        for s in data["sets"]:
            s.pop("league_slug", None)
        (tmp_path / "manifest.json").write_text(json.dumps(data))
        reloaded = ProjectionStore(tmp_path)
        assert reloaded.list_sets(source="bbm")[0].league_slug is None


# ---------------------------------------------------------------------------
# build_accuracy_scoreboard — orchestration on a synthetic league
# ---------------------------------------------------------------------------


def _recap_store_mock(
    actual_weeks: set[int],
    payloads: dict[int, list[dict]],
) -> MagicMock:
    store = MagicMock(spec=RecapStore)
    store.list_week_scoreboard_weeks.return_value = actual_weeks
    store.get_week_scoreboard.side_effect = lambda *, league_id, season, week: (
        {"payload_json": payloads[week]} if week in payloads else None
    )
    return store


class TestBuildAccuracyScoreboard:
    @pytest.fixture()
    def pstore(self, tmp_path):
        return ProjectionStore(tmp_path)

    def _seed_week1(self, pstore: ProjectionStore) -> None:
        """ESPN snapshot (embeds rosters) + BBM upload (global) for week 1."""
        espn_rows = [
            _player("star one", "Alpha", games=3, pts=30.0),
            _player("star two", "Beta", games=3, pts=25.0),
        ]
        pstore.save_set(
            espn_rows, "espn", "week",
            week=1, league_slug="fcp", activate=False,
        )
        bbm_rows = [
            _player("star one", None, games=3, pts=32.0),
            _player("star two", None, games=3, pts=24.0),
        ]
        pstore.save_set(bbm_rows, "bbm", "week", week=1)

    def test_scores_espn_and_bbm_with_borrowed_rosters(self, pstore):
        self._seed_week1(pstore)
        payload = _scoreboard_payload({
            "Alpha": {"PTS": 90.0},
            "Beta": {"PTS": 75.0},
        })
        recap = _recap_store_mock({1}, {1: payload})

        result = build_accuracy_scoreboard(
            recap_store=recap,
            league_id="uuid-1",
            league_slug="fcp",
            season=2025,
            current_week=2,
            projection_store=pstore,
        )

        by_source = {w["source"]: w for w in result["weeks"]}
        # ESPN: 3×30=90 vs 90, 3×25=75 vs 75 → perfect
        assert by_source["espn"]["per_category"]["PTS"]["mae"] == 0.0
        # BBM (rosters borrowed from the ESPN snapshot): 96 vs 90, 72 vs 75
        assert by_source["bbm"]["per_category"]["PTS"]["mae"] == pytest.approx(4.5)
        assert by_source["bbm"]["players_unassigned"] == 0
        sources = {s["source"] for s in result["sources"]}
        assert sources == {"bbm", "espn"}

    def test_current_week_excluded(self, pstore):
        self._seed_week1(pstore)
        payload = _scoreboard_payload({"Alpha": {"PTS": 90.0}, "Beta": {"PTS": 75.0}})
        recap = _recap_store_mock({1}, {1: payload})

        result = build_accuracy_scoreboard(
            recap_store=recap,
            league_id="uuid-1",
            league_slug="fcp",
            season=2025,
            current_week=1,     # week 1 still in progress
            projection_store=pstore,
        )

        assert result["weeks"] == []
        reasons = {(u["source"], u["reason"]) for u in result["unscoreable"]}
        assert reasons == {("espn", "week_in_progress"), ("bbm", "week_in_progress")}

    def test_no_actuals_reported_not_guessed(self, pstore):
        self._seed_week1(pstore)
        recap = _recap_store_mock(set(), {})

        result = build_accuracy_scoreboard(
            recap_store=recap,
            league_id="uuid-1",
            league_slug="fcp",
            season=2025,
            current_week=5,
            projection_store=pstore,
        )

        assert result["weeks"] == []
        assert all(u["reason"] == "no_actuals_for_week" for u in result["unscoreable"])

    def test_bbm_without_any_roster_source_unscoreable(self, pstore):
        """A global set with no same-week ESPN snapshot can't map players
        to fantasy teams — reported, never guessed."""
        pstore.save_set(
            [_player("star one", None, games=3, pts=32.0)],
            "bbm", "week", week=1,
        )
        payload = _scoreboard_payload({"Alpha": {"PTS": 90.0}, "Beta": {"PTS": 75.0}})
        recap = _recap_store_mock({1}, {1: payload})

        result = build_accuracy_scoreboard(
            recap_store=recap,
            league_id="uuid-1",
            league_slug="fcp",
            season=2025,
            current_week=2,
            projection_store=pstore,
        )

        assert result["weeks"] == []
        assert result["unscoreable"] == [
            {"source": "bbm", "week": 1, "reason": "no_roster_mapping"}
        ]

    def test_other_leagues_snapshots_ignored(self, pstore):
        pstore.save_set(
            [_player("star one", "Alpha", games=3, pts=30.0)],
            "espn", "week", week=1, league_slug="other-league", activate=False,
        )
        payload = _scoreboard_payload({"Alpha": {"PTS": 90.0}, "Beta": {"PTS": 75.0}})
        recap = _recap_store_mock({1}, {1: payload})

        result = build_accuracy_scoreboard(
            recap_store=recap,
            league_id="uuid-1",
            league_slug="fcp",
            season=2025,
            current_week=2,
            projection_store=pstore,
        )

        assert result["weeks"] == []
        assert result["unscoreable"] == []

    def test_newest_set_wins_per_source_week(self, pstore):
        """Re-uploading a source's week set scores the newest upload only."""
        pstore.save_set(
            [_player("star one", "Alpha", games=3, pts=10.0)],
            "espn", "week", week=1, league_slug="fcp", activate=False,
        )
        newest = pstore.save_set(
            [_player("star one", "Alpha", games=3, pts=30.0)],
            "espn", "week", week=1, league_slug="fcp", activate=False,
        )
        payload = _scoreboard_payload({"Alpha": {"PTS": 90.0}, "Beta": {"PTS": 75.0}})
        recap = _recap_store_mock({1}, {1: payload})

        result = build_accuracy_scoreboard(
            recap_store=recap,
            league_id="uuid-1",
            league_slug="fcp",
            season=2025,
            current_week=2,
            projection_store=pstore,
        )

        (week_entry,) = result["weeks"]
        assert week_entry["set_id"] == newest.set_id
        assert week_entry["per_category"]["PTS"]["mae"] == 0.0

    def test_source_aggregation_across_weeks(self, pstore):
        for week, pts in ((1, 30.0), (2, 40.0)):
            pstore.save_set(
                [
                    _player("star one", "Alpha", games=3, pts=pts),
                    _player("star two", "Beta", games=3, pts=pts - 5),
                ],
                "espn", "week", week=week, league_slug="fcp", activate=False,
            )
        payloads = {
            1: _scoreboard_payload({"Alpha": {"PTS": 90.0}, "Beta": {"PTS": 75.0}}),
            2: _scoreboard_payload({"Alpha": {"PTS": 100.0}, "Beta": {"PTS": 95.0}}),
        }
        recap = _recap_store_mock({1, 2}, payloads)

        result = build_accuracy_scoreboard(
            recap_store=recap,
            league_id="uuid-1",
            league_slug="fcp",
            season=2025,
            current_week=3,
            projection_store=pstore,
        )

        (espn,) = result["sources"]
        assert espn["weeks_scored"] == 2
        # week 1: perfect (mae 0); week 2: |120-100|=20, |105-95|=10 → mae 15
        assert espn["per_category"]["PTS"]["mae"] == pytest.approx(7.5)


# ---------------------------------------------------------------------------
# Worker snapshot hook (M-2c)
# ---------------------------------------------------------------------------


class TestSnapshotWeekProjections:
    def _parse_stub(self, rows):
        def _parse(self, file=None, **kwargs):
            return rows
        return _parse

    def test_snapshot_saved_once_per_week(self, tmp_path, monkeypatch):
        from backend.worker.refresh import _snapshot_week_projections

        rows = [_player("star one", "Alpha")]
        monkeypatch.setattr(
            "backend.projections.adapter.EspnAdapter.parse",
            self._parse_stub(rows),
        )
        pstore = ProjectionStore(tmp_path)

        first = _snapshot_week_projections("fcp", object(), 4, pstore=pstore)
        assert first.startswith("ok (snapshot")
        second = _snapshot_week_projections("fcp", object(), 4, pstore=pstore)
        assert second == "ok (week 4 already snapshotted)"

        sets = [
            s for s in pstore.list_sets(source="espn", horizon="week")
            if s.set_id != ESPN_VIRTUAL_SET_ID
        ]
        assert len(sets) == 1
        assert sets[0].week == 4
        assert sets[0].league_slug == "fcp"

    def test_snapshot_never_activates(self, tmp_path, monkeypatch):
        from backend.worker.refresh import _snapshot_week_projections

        monkeypatch.setattr(
            "backend.projections.adapter.EspnAdapter.parse",
            self._parse_stub([_player("star one", "Alpha")]),
        )
        pstore = ProjectionStore(tmp_path)
        active = pstore.save_set([_player("b", "T")], "bbm", "week", week=4)

        _snapshot_week_projections("fcp", object(), 4, pstore=pstore)
        assert pstore._manifest.active["week"] == active.set_id

    def test_empty_rosters_skipped(self, tmp_path, monkeypatch):
        from backend.worker.refresh import _snapshot_week_projections

        monkeypatch.setattr(
            "backend.projections.adapter.EspnAdapter.parse",
            self._parse_stub([]),
        )
        pstore = ProjectionStore(tmp_path)
        result = _snapshot_week_projections("fcp", object(), 4, pstore=pstore)
        assert result == "skipped (no rostered players)"
        assert pstore.list_sets(source="espn", horizon="week")[0].set_id == ESPN_VIRTUAL_SET_ID
