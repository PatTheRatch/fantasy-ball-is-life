"""P-3a tests: worker phase isolation, upsert, WORKER_SECRET guard."""

from unittest.mock import Mock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.worker import refresh as wrk
from backend.recaps.store import RecapStore


# ── Helpers ───────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    return TestClient(app)


# ── WORKER_SECRET guard ────────────────────────────────────────────────────────


class TestWorkerSecretGuard:
    def test_missing_secret_rejects(self, client):
        resp = client.post("/admin/refresh/my-league")
        assert resp.status_code in (403, 500)

    def test_wrong_secret_rejects(self, client):
        resp = client.post(
            "/admin/refresh/my-league",
            headers={"X-Worker-Secret": "wrong"},
        )
        assert resp.status_code in (403, 500)

    def test_league_not_found_404s(self, monkeypatch):
        monkeypatch.setenv("WORKER_SECRET", "test-secret")
        client2 = TestClient(app)

        with patch.object(wrk, "refresh_league", return_value={}):
            with patch.object(RecapStore, "_request", return_value=[]):
                resp = client2.post(
                    "/admin/refresh/nonexistent",
                    headers={"X-Worker-Secret": "test-secret"},
                )
                assert resp.status_code == 404


# ── Phase isolation ───────────────────────────────────────────────────────────


class TestPhaseIsolation:
    def test_standings_failure_does_not_block_other_phases(self):
        """One phase failing leaves others intact."""
        store = Mock(spec=RecapStore)
        store.collected = []

        def capture_upsert(*args, **kwargs):
            store.collected.append(kwargs.get("json"))
            return [{}]

        store._request = Mock(side_effect=capture_upsert)

        # Make _load_phase flaky for standings
        original_load = wrk._load_phase
        call_count = 0

        def flaky_load(phase, handles, week):
            nonlocal call_count
            call_count += 1
            if phase == "standings" and call_count == 1:
                raise RuntimeError("ESPN timeout")
            return original_load(phase, handles, week)

        with patch.object(wrk, "_load_phase", side_effect=flaky_load):
            with patch.object(wrk, "RecapStore", return_value=store):
                # Patch League import inside refresh_league()
                with patch("backend.worker.refresh.League") as mock_league_cls:
                    mock_league_cls.return_value.current_week = 12
                    results = wrk.refresh_league(
                        league_id="l1",
                        espn_league_id=1,
                        espn_season=2026,
                        espn_s2="s2",
                        swid="swid",
                    )

        assert results["standings"].startswith("error:")
        assert results["scoreboard"].startswith("ok")
        assert results["transactions"].startswith("ok")

    def test_all_phases_run_even_when_connect_fails(self):
        """connect failure → error dict, not a crash."""
        with patch("backend.worker.refresh.League", side_effect=ConnectionError("unreachable")):
            results = wrk.refresh_league(
                league_id="l1",
                espn_league_id=1,
                espn_season=2026,
                espn_s2="s2",
                swid="swid",
            )
        assert "error:" in results.get("connect", "")


# ── Upsert semantics ──────────────────────────────────────────────────────────


class TestUpsertSemantics:
    def test_second_write_overwrites_first(self):
        """Two refreshes → both payloads written (upsert via merge-duplicates)."""
        store = Mock(spec=RecapStore)
        store.collected = []

        def capture(method, path, *, json=None, **kwargs):
            if json:
                store.collected.append(json)
            return [{}]

        store._request = Mock(side_effect=capture)

        wrk.upsert_phase(
            store=store,
            league_id="l1",
            season=2026,
            week=1,
            phase="standings",
            payload=[{"team": "Alpha"}],
            fetched_at="2026-01-01T00:00:00Z",
        )
        wrk.upsert_phase(
            store=store,
            league_id="l1",
            season=2026,
            week=2,
            phase="standings",
            payload=[{"team": "Beta"}],
            fetched_at="2026-01-02T00:00:00Z",
        )

        payloads = [c["payload_json"] for c in store.collected]
        assert payloads == [[{"team": "Alpha"}], [{"team": "Beta"}]]

    def test_upsert_uses_merge_duplicates(self):
        """upsert_phase passes resolution=merge-duplicates to PostgREST."""
        store = Mock(spec=RecapStore)
        wrk.upsert_phase(
            store=store,
            league_id="l1",
            season=2026,
            week=1,
            phase="standings",
            payload=[],
            fetched_at="2026-01-01T00:00:00Z",
        )
        # _request is called with: (method, path, *, json=..., prefer=...)
        call = store._request.call_args
        assert call is not None
        args, kwargs = call
        assert args[0] == "POST"
        assert args[1] == "league_state_snapshots"
        assert kwargs["prefer"] == "resolution=merge-duplicates"
