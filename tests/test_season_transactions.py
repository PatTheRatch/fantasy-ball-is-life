"""Per-week + season-cumulative transactions.

Three live bugs shared one root cause: the `transactions` phase in
league_state_snapshots is rolling latest-state (current week only).

  * Standings "Moves" counted a single week (~7 adds), not the season.
  * Standings "Trades" was ~always 0 — a trade only counted if it happened
    during the current week.
  * The newsroom transactions feed showed the CURRENT week's rows no matter
    which week you were viewing, so a trade in week 3 was invisible from
    week 3 and every other week.

Fix: store transactions per week (immutable, backfilled once) and expose
both a week-scoped `transactions` (newsroom feed) and a cumulative
`season_transactions` (season totals).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.recaps import assemble as asm
from backend.recaps.store import RecapStore
from backend.worker import refresh as wrk


# ── Store methods ─────────────────────────────────────────────────────────────


class TestStoreMethods:
    def test_get_week_transactions_queries_by_week(self, monkeypatch):
        captured = {}

        def fake_request(self, method, path, *, params=None, json=None, prefer=None):
            captured["path"] = path
            captured["params"] = params
            return [{"payload_json": [{"action_type": "ADD"}], "week": 3}]

        monkeypatch.setattr(RecapStore, "_request", fake_request)
        store = RecapStore(url="http://x", service_role_key="k")
        row = store.get_week_transactions(league_id="L1", season=2026, week=3)

        assert captured["path"] == "league_week_transactions"
        assert captured["params"]["week"] == "eq.3"
        assert row["payload_json"] == [{"action_type": "ADD"}]

    def test_list_all_week_transactions_flattens_across_weeks(self, monkeypatch):
        monkeypatch.setattr(
            RecapStore,
            "_request",
            lambda *a, **k: [
                {"week": 1, "payload_json": [{"action_type": "ADD"}, {"action_type": "DROP"}]},
                {"week": 2, "payload_json": [{"action_type": "TRADE"}]},
            ],
        )
        store = RecapStore(url="http://x", service_role_key="k")
        rows = store.list_all_week_transactions(league_id="L1", season=2026)
        assert len(rows) == 3
        assert [r["action_type"] for r in rows] == ["ADD", "DROP", "TRADE"]

    def test_through_week_filters_to_that_week(self, monkeypatch):
        captured = {}

        def fake_request(self, method, path, *, params=None, json=None, prefer=None):
            captured["params"] = params
            return []

        monkeypatch.setattr(RecapStore, "_request", fake_request)
        store = RecapStore(url="http://x", service_role_key="k")
        store.list_all_week_transactions(league_id="L1", season=2026, through_week=5)
        # A week-5 view must not include week 6+ activity.
        assert captured["params"]["week"] == "lte.5"


# ── Worker: per-week upsert + backfill ────────────────────────────────────────


class TestWorkerHelpers:
    def test_upsert_week_transactions_targets_week_conflict(self):
        store = MagicMock()
        wrk._upsert_week_transactions(store, "L1", 2026, 4, [{"action_type": "ADD"}])
        args, kwargs = store._request.call_args
        assert args[:2] == ("POST", "league_week_transactions")
        assert kwargs["params"]["on_conflict"] == "league_id,season,week"
        assert kwargs["json"]["week"] == 4

    def test_backfill_fetches_only_missing_weeks(self, monkeypatch):
        store = MagicMock()
        store.list_week_transaction_weeks.return_value = {1, 2}
        fetched: list[int] = []

        def fake_week_txns(handles, week=None):
            fetched.append(week)
            return [{"action_type": "ADD", "team_name": "Alpha"}]

        monkeypatch.setattr(
            "backend.league.data_feed.week_transactions_for_week", fake_week_txns
        )
        summary = wrk._backfill_week_transactions(store, object(), "L1", 2026, 5)

        assert sorted(fetched) == [3, 4]
        assert "filled 2" in summary and "skipped 2" in summary

    def test_backfill_isolates_failing_week(self, monkeypatch):
        store = MagicMock()
        store.list_week_transaction_weeks.return_value = set()

        def fake_week_txns(handles, week=None):
            if week == 2:
                raise RuntimeError("ESPN hiccup")
            return []

        monkeypatch.setattr(
            "backend.league.data_feed.week_transactions_for_week", fake_week_txns
        )
        summary = wrk._backfill_week_transactions(store, object(), "L1", 2026, 4)
        assert "filled 2" in summary and "failed 1" in summary


# ── Assemble: week-scoped feed + cumulative season totals ─────────────────────


def _league() -> dict:
    return {"id": "L1", "slug": "test", "name": "Test", "visibility": "public"}


class TestAssembleTransactions:
    def _patch(self, monkeypatch, *, latest_txns, week_txns, season_txns):
        monkeypatch.setattr(
            RecapStore,
            "get_all_phases",
            lambda self, *, league_id, season: {
                "standings": {"payload_json": []},
                "power_rankings": {"payload_json": []},
                "scoreboard": {"payload_json": []},
                "transactions": {"payload_json": latest_txns, "fetched_at": "t"},
                "season_stats": {"payload_json": []},
            },
        )
        monkeypatch.setattr(
            RecapStore, "get_week_scoreboard",
            lambda self, *, league_id, season, week: None,
        )
        monkeypatch.setattr(
            RecapStore, "get_week_transactions",
            lambda self, *, league_id, season, week: (
                {"payload_json": week_txns} if week_txns is not None else None
            ),
        )
        monkeypatch.setattr(
            RecapStore, "list_all_week_transactions",
            lambda self, *, league_id, season, through_week=None: season_txns,
        )

    def test_week_feed_uses_that_weeks_rows_not_latest(self, monkeypatch):
        """The newsroom feed must show the requested week — a trade in week 3
        has to be visible when viewing week 3."""
        self._patch(
            monkeypatch,
            latest_txns=[{"action_type": "ADD", "team_name": "Current Week Add",
                          "activity_id": "cur-1"}],
            week_txns=[{"action_type": "TRADE", "team_name": "Alpha",
                        "activity_id": "w3-trade"}],
            season_txns=[],
        )
        snap = asm.assemble_weekly_snapshot(
            league=_league(), season=2026, week=3,
            week_start="2026-01-01", week_end="2026-01-07",
        )
        ids = {t["activity_id"] for t in snap.transactions}
        assert "w3-trade" in ids
        assert "cur-1" not in ids

    def test_season_transactions_are_cumulative(self, monkeypatch):
        self._patch(
            monkeypatch,
            latest_txns=[],
            week_txns=[{"action_type": "ADD", "team_name": "Alpha", "activity_id": "w3-a"}],
            season_txns=[
                {"action_type": "ADD", "team_name": "Alpha", "activity_id": "w1-a"},
                {"action_type": "TRADE", "team_name": "Alpha", "activity_id": "w2-t"},
                {"action_type": "ADD", "team_name": "Alpha", "activity_id": "w3-a"},
            ],
        )
        snap = asm.assemble_weekly_snapshot(
            league=_league(), season=2026, week=3,
            week_start="2026-01-01", week_end="2026-01-07",
        )
        # Week feed stays week-scoped; season totals span the season.
        assert len(snap.transactions) == 1
        assert len(snap.season_transactions) == 3
        kinds = [t["action_type"] for t in snap.season_transactions]
        assert kinds.count("ADD") == 2
        assert kinds.count("TRADE") == 1

    def test_season_falls_back_to_week_when_store_empty(self, monkeypatch):
        """Before the backfill runs, season totals degrade to the week's rows
        rather than rendering an empty Moves/Trades column."""
        self._patch(
            monkeypatch,
            latest_txns=[],
            week_txns=[{"action_type": "ADD", "team_name": "Alpha", "activity_id": "w3-a"}],
            season_txns=[],
        )
        snap = asm.assemble_weekly_snapshot(
            league=_league(), season=2026, week=3,
            week_start="2026-01-01", week_end="2026-01-07",
        )
        assert len(snap.season_transactions) == 1
