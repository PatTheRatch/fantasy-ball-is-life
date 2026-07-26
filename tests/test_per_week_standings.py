"""Standings as of a requested week.

The stored `standings` phase is rolling latest-state (accumulated through
the CURRENT week), so viewing week 3 in the newsroom rendered the
end-of-season table. Per-week scoreboards (added for the matchup fix) let
the table be recomputed as it stood that week — no extra storage.
"""

from __future__ import annotations

from backend.recaps import assemble as asm
from backend.recaps.store import RecapStore


def _sb(home: str, away: str, home_wins_cats: int) -> list[dict]:
    """A one-matchup scoreboard where `home` wins `home_wins_cats` of 9."""
    cats = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]
    rows = []
    for i, stat in enumerate(cats):
        home_better = i < home_wins_cats
        # TO is inverted: the lower value wins, so flip the numbers for it.
        if stat == "TO":
            hi, lo = (1.0, 2.0) if home_better else (2.0, 1.0)
        else:
            hi, lo = (2.0, 1.0) if home_better else (1.0, 2.0)
        rows.append(
            {
                "stat": stat,
                "home_team": home,
                "away_team": away,
                "current_home_score": hi,
                "current_away_score": lo,
            }
        )
    return rows


class TestStandingsAccumulation:
    def test_sums_category_wins_across_weeks(self):
        """H2H each-category: a 7-2 week adds 7-2, not 1-0."""
        weeks = [
            (1, _sb("Alpha", "Beta", 7)),
            (2, _sb("Alpha", "Beta", 6)),
        ]
        rows = asm.standings_from_week_scoreboards(weeks)
        alpha = next(r for r in rows if r["team_name"] == "Alpha")
        beta = next(r for r in rows if r["team_name"] == "Beta")
        assert alpha["wins"] == 13  # 7 + 6
        assert alpha["losses"] == 5  # 2 + 3
        assert beta["wins"] == 5
        assert beta["losses"] == 13

    def test_standing_ranks_by_win_pct(self):
        rows = asm.standings_from_week_scoreboards([(1, _sb("Alpha", "Beta", 8))])
        assert rows[0]["team_name"] == "Alpha"
        assert rows[0]["standing"] == 1
        assert rows[1]["standing"] == 2

    def test_win_pct_is_0_to_100(self):
        """Matches allplay_win_pct's scale (not a 0-1 ratio)."""
        rows = asm.standings_from_week_scoreboards([(1, _sb("Alpha", "Beta", 9))])
        alpha = next(r for r in rows if r["team_name"] == "Alpha")
        assert alpha["win_pct"] == 100.0

    def test_fewer_weeks_yields_different_table(self):
        """The whole point: week-1-only standings != through-week-2."""
        w1 = asm.standings_from_week_scoreboards([(1, _sb("Alpha", "Beta", 9))])
        w2 = asm.standings_from_week_scoreboards(
            [(1, _sb("Alpha", "Beta", 9)), (2, _sb("Alpha", "Beta", 0))]
        )
        a1 = next(r for r in w1 if r["team_name"] == "Alpha")
        a2 = next(r for r in w2 if r["team_name"] == "Alpha")
        assert a1["wins"] == 9 and a1["losses"] == 0
        assert a2["wins"] == 9 and a2["losses"] == 9  # week 2 swept back
        assert a1["win_pct"] != a2["win_pct"]

    def test_empty_input_is_empty_not_error(self):
        assert asm.standings_from_week_scoreboards([]) == []


class TestStoreQuery:
    def test_list_week_scoreboards_filters_through_week(self, monkeypatch):
        captured = {}

        def fake_request(self, method, path, *, params=None, json=None, prefer=None):
            captured["path"] = path
            captured["params"] = params
            return [{"week": 1, "payload_json": []}]

        monkeypatch.setattr(RecapStore, "_request", fake_request)
        store = RecapStore(url="http://x", service_role_key="k")
        store.list_week_scoreboards(league_id="L1", season=2026, through_week=3)

        assert captured["path"] == "league_week_scoreboards"
        # A week-3 view must not accumulate weeks 4+.
        assert captured["params"]["week"] == "lte.3"
        assert captured["params"]["order"] == "week.asc"


class TestAssembleUsesRequestedWeek:
    def _patch(self, monkeypatch, *, rolling_standings, week_scoreboards):
        monkeypatch.setattr(
            RecapStore,
            "get_all_phases",
            lambda self, *, league_id, season: {
                "standings": {"payload_json": rolling_standings, "fetched_at": "t"},
                "power_rankings": {"payload_json": []},
                "scoreboard": {"payload_json": []},
                "transactions": {"payload_json": []},
                "season_stats": {"payload_json": []},
            },
        )
        monkeypatch.setattr(
            RecapStore, "get_week_scoreboard",
            lambda self, *, league_id, season, week: None,
        )
        monkeypatch.setattr(
            RecapStore, "list_week_scoreboards",
            lambda self, *, league_id, season, through_week: week_scoreboards,
        )

    def test_derives_standings_from_weeks_not_rolling_state(self, monkeypatch):
        # Rolling state claims Alpha is 99-0 (end-of-season); week 1 alone
        # says 7-2. Viewing week 1 must show the week-1 truth.
        self._patch(
            monkeypatch,
            rolling_standings=[
                {"team_name": "Alpha", "wins": 99, "losses": 0, "ties": 0, "win_pct": 100.0},
            ],
            week_scoreboards=[{"week": 1, "payload_json": _sb("Alpha", "Beta", 7)}],
        )
        snap = asm.assemble_weekly_snapshot(
            league={"id": "L1", "slug": "t", "name": "T", "visibility": "public"},
            season=2026, week=1,
            week_start="2026-01-01", week_end="2026-01-07",
        )
        alpha = next(r for r in snap.standings if r["team_name"] == "Alpha")
        assert alpha["wins"] == 7
        assert alpha["losses"] == 2

    def test_falls_back_to_rolling_when_no_week_rows(self, monkeypatch):
        self._patch(
            monkeypatch,
            rolling_standings=[
                {"team_name": "Alpha", "wins": 42, "losses": 3, "ties": 0, "win_pct": 93.3},
            ],
            week_scoreboards=[],  # not backfilled yet
        )
        snap = asm.assemble_weekly_snapshot(
            league={"id": "L1", "slug": "t", "name": "T", "visibility": "public"},
            season=2026, week=5,
            week_start="2026-01-01", week_end="2026-01-07",
        )
        alpha = next(r for r in snap.standings if r["team_name"] == "Alpha")
        assert alpha["wins"] == 42
