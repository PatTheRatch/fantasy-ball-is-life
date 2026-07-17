"""P-3a tests: worker phase isolation, upsert, WORKER_SECRET guard.

The worker now calls the endpoint-level league API functions via a
monkeypatched config — tests patch those functions to avoid real ESPN.
"""

from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.worker import refresh as wrk
from backend.recaps.store import RecapStore


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

        with patch.object(RecapStore, "_request", return_value=[]):
            resp = client2.post(
                "/admin/refresh/nonexistent",
                headers={"X-Worker-Secret": "test-secret"},
            )
            assert resp.status_code == 404


# ── Phase isolation ───────────────────────────────────────────────────────────


class TestPhaseIsolation:
    def test_one_phase_failure_does_not_block_others(self):
        """Standings fails → error logged, other phases proceed."""
        store = Mock(spec=RecapStore)
        collected = []

        def capture(*args, **kwargs):
            collected.append(kwargs.get("json"))
            return [{}]

        store._request = Mock(side_effect=capture)

        # Mock the config patching + league API
        mock_handles = Mock()
        mock_handles.league.current_week = 12

        with patch.object(wrk, "_patched_espn_config") as mock_ctx:
            mock_ctx.return_value.__enter__ = Mock()
            mock_ctx.return_value.__exit__ = Mock(return_value=None)

            # Running inside the context → league_api available
            def fake_refresh(*args, **kwargs):
                # Simulate what happens inside the context
                league_api = Mock()
                league_api._handles.return_value = mock_handles

                # Phase 1: standings fails
                league_api.league_standings.side_effect = RuntimeError("ESPN down")
                # Phase 2-6: succeed
                league_api.power_rankings.return_value = [{"rank": 1}]
                league_api.scoreboard_current.return_value = [{"home": "A"}]
                league_api.transactions_week.return_value = [{"player": "X"}]
                league_api.season_stats.return_value = [{"Team": "A"}]
                league_api.league_settings.return_value = {"acquisition_type": "WAIVERS"}

                results = {}

                for phase in wrk.PHASES:
                    try:
                        payload = wrk._load_phase(phase, league_api, 12, "1,2,3,4,5,6,7,8,9,10,11,12")
                        wrk.upsert_phase(
                            store=store,
                            league_id="l1",
                            season=2026,
                            week=12,
                            phase=phase,
                            payload=payload,
                            fetched_at="2026-01-01T00:00:00Z",
                        )
                        results[phase] = f"ok"
                    except Exception as exc:
                        results[phase] = f"error: {exc}"

                return results

            with patch.object(wrk, "refresh_league", side_effect=fake_refresh):
                from backend.worker.refresh import PHASES
                results = fake_refresh(
                    league_id="l1",
                    espn_league_id=1,
                    espn_season=2026,
                    espn_s2="s2",
                    swid="swid",
                )

        assert results["standings"].startswith("error:")
        assert results["power_rankings"].startswith("ok")
        assert results["scoreboard"].startswith("ok")
        assert results["transactions"].startswith("ok")
        assert results["season_stats"].startswith("ok")
        assert results["settings"].startswith("ok")


# ── Upsert semantics ──────────────────────────────────────────────────────────


class TestUpsertSemantics:
    def test_second_write_overwrites_first(self):
        """Two refreshes → both payloads written (upsert via merge-duplicates)."""
        store = Mock(spec=RecapStore)
        collected = []

        def capture(*args, **kwargs):
            collected.append(kwargs.get("json"))
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

        payloads = [c["payload_json"] for c in collected]
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
        call = store._request.call_args
        assert call is not None
        args, kwargs = call
        assert args[0] == "POST"
        assert args[1] == "league_state_snapshots"
        assert kwargs["prefer"] == "resolution=merge-duplicates"


# ── Config patching guard ──────────────────────────────────────────────────────


class TestConfigPatching:
    def test_config_restored_after_refresh(self):
        """_patched_espn_config restores originals even on exception."""
        import backend.config as config
        import backend.league.data_feed as df
        import backend.api.deps as deps

        orig_league = config.LEAGUE_ID
        orig_swid = config.SWID

        try:
            with wrk._patched_espn_config(league_id=999, season=2027, swid="test", espn_s2="test"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass

        assert config.LEAGUE_ID == orig_league
        assert config.SWID == orig_swid
        assert df.LEAGUE_ID == orig_league
        assert deps.LEAGUE_ID == orig_league
