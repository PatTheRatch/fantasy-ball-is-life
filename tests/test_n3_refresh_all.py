"""N-3: refresh-all — worker loop, failure isolation, admin endpoint.

Hermetic: RecapStore._request and refresh_league are monkeypatched; no
Supabase or ESPN access.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.recaps.store import RecapStore
from backend.worker import refresh as refresh_mod


class TestListLeagueSlugs:
    def test_returns_all_slugs(self, monkeypatch):
        captured = {}

        def fake_request(self, method, path, *, params=None, json=None, prefer=None):
            captured["method"] = method
            captured["path"] = path
            captured["params"] = params
            return [{"slug": "alpha"}, {"slug": "beta"}, {"slug": None}]

        monkeypatch.setattr(RecapStore, "_request", fake_request)
        store = RecapStore(url="http://x", service_role_key="k")
        assert store.list_league_slugs() == ["alpha", "beta"]
        assert captured["method"] == "GET"
        assert captured["path"] == "leagues"
        assert captured["params"]["select"] == "slug"

    def test_empty_table_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(RecapStore, "_request", lambda *a, **k: [])
        store = RecapStore(url="http://x", service_role_key="k")
        assert store.list_league_slugs() == []


class TestRefreshAllLeagues:
    def test_processes_every_league(self, monkeypatch):
        monkeypatch.setattr(
            RecapStore, "list_league_slugs", lambda self: ["a", "b", "c"]
        )
        calls = []

        def fake_refresh(*, slug):
            calls.append(slug)
            return {"settings": "ok"}

        monkeypatch.setattr(refresh_mod, "refresh_league", fake_refresh)
        results = refresh_mod.refresh_all_leagues()
        assert calls == ["a", "b", "c"]
        assert results == {
            "a": {"settings": "ok"},
            "b": {"settings": "ok"},
            "c": {"settings": "ok"},
        }

    def test_one_failure_does_not_block_subsequent_leagues(self, monkeypatch):
        monkeypatch.setattr(
            RecapStore, "list_league_slugs", lambda self: ["a", "bad", "c"]
        )

        def fake_refresh(*, slug):
            if slug == "bad":
                raise RuntimeError("credential resolution failed")
            return {"settings": "ok"}

        monkeypatch.setattr(refresh_mod, "refresh_league", fake_refresh)
        results = refresh_mod.refresh_all_leagues()
        assert set(results) == {"a", "bad", "c"}
        assert results["a"] == {"settings": "ok"}
        assert results["c"] == {"settings": "ok"}
        assert isinstance(results["bad"], str)
        assert results["bad"].startswith("error:")
        assert "credential resolution failed" in results["bad"]

    def test_result_mapping_distinguishes_success_and_failure(self, monkeypatch):
        monkeypatch.setattr(
            RecapStore, "list_league_slugs", lambda self: ["ok-league", "down"]
        )

        def fake_refresh(*, slug):
            if slug == "down":
                raise ConnectionError("ESPN unreachable")
            return {"standings": "ok", "scoreboard": "error: espn 500"}

        monkeypatch.setattr(refresh_mod, "refresh_league", fake_refresh)
        results = refresh_mod.refresh_all_leagues()
        # Success → per-phase dict (even if phases had errors); failure → string.
        assert isinstance(results["ok-league"], dict)
        assert isinstance(results["down"], str)


class TestRefreshAllEndpoint:
    @pytest.fixture
    def secret(self, monkeypatch):
        monkeypatch.setenv("WORKER_SECRET", "s3cret")
        return "s3cret"

    def test_requires_worker_secret(self, secret):
        client = TestClient(app)
        assert client.post("/admin/refresh-all").status_code == 403
        assert (
            client.post(
                "/admin/refresh-all", headers={"X-Worker-Secret": "wrong"}
            ).status_code
            == 403
        )

    def test_unconfigured_secret_is_500(self, monkeypatch):
        monkeypatch.delenv("WORKER_SECRET", raising=False)
        client = TestClient(app)
        assert client.post("/admin/refresh-all").status_code == 500

    def test_returns_per_league_mapping(self, secret, monkeypatch):
        monkeypatch.setattr(
            refresh_mod,
            "refresh_all_leagues",
            lambda: {"a": {"settings": "ok"}, "b": "error: boom"},
        )
        client = TestClient(app)
        resp = client.post(
            "/admin/refresh-all", headers={"X-Worker-Secret": "s3cret"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"a": {"settings": "ok"}, "b": "error: boom"}

    def test_not_swallowed_by_single_league_route(self, secret, monkeypatch):
        """POST /admin/refresh-all must hit refresh_all_leagues, never
        refresh_league(slug='refresh-all')."""
        all_calls, single_calls = [], []
        monkeypatch.setattr(
            refresh_mod,
            "refresh_all_leagues",
            lambda: all_calls.append(True) or {},
        )
        monkeypatch.setattr(
            refresh_mod,
            "refresh_league",
            lambda *, slug: single_calls.append(slug) or {},
        )
        client = TestClient(app)
        resp = client.post(
            "/admin/refresh-all", headers={"X-Worker-Secret": "s3cret"}
        )
        assert resp.status_code == 200
        assert all_calls == [True]
        assert single_calls == []

    def test_single_league_endpoint_still_works(self, secret, monkeypatch):
        monkeypatch.setattr(
            refresh_mod,
            "refresh_league",
            lambda *, slug: {"slug": slug, "settings": "ok"},
        )
        client = TestClient(app)
        resp = client.post(
            "/admin/refresh/patriot-games", headers={"X-Worker-Secret": "s3cret"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"slug": "patriot-games", "settings": "ok"}
