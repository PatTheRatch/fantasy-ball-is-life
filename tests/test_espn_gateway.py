"""PR E1 — ESPN gateway timeout + typed-error policy.

The installed `espn-api` library calls `requests.get()` with no timeout, so a
stalled ESPN response hangs the request indefinitely (audit: "No timeout on
any ESPN read"). `backend.league.gateway` patches that call in place to
enforce a connect/read timeout and translates transport failures into typed
exceptions the API layer maps to 502/504 instead of a generic 500.
"""
import pytest
import requests
from fastapi import HTTPException

from backend.api.deps import _espn_http_exception
from backend.league import gateway
from backend.league.gateway import (
    ESPN_TIMEOUT,
    ESPNTimeoutError,
    ESPNUnavailableError,
    espn_error_status_code,
    espn_get,
    install_espn_timeout_patch,
)


# --- install_espn_timeout_patch --------------------------------------------

def test_patch_applies_default_timeout_to_espn_api_requests_get(monkeypatch):
    from espn_api.requests import espn_requests as espn_requests_module

    captured = {}

    def _spy(url, *args, **kwargs):
        captured.update(kwargs)
        return "ok"

    # Patch is idempotent (guarded by a module-level flag); force a fresh
    # install against a spy so this test doesn't depend on import order.
    monkeypatch.setattr(gateway, "_PATCHED", False)
    monkeypatch.setattr(
        espn_requests_module, "requests", type("_R", (), {"get": staticmethod(_spy)})()
    )
    install_espn_timeout_patch()

    espn_requests_module.requests.get("https://example.invalid")
    assert captured["timeout"] == ESPN_TIMEOUT


def test_patch_is_idempotent(monkeypatch):
    from espn_api.requests import espn_requests as espn_requests_module

    monkeypatch.setattr(gateway, "_PATCHED", False)
    install_espn_timeout_patch()
    proxy_once = espn_requests_module.requests
    install_espn_timeout_patch()
    assert espn_requests_module.requests is proxy_once


def test_patch_does_not_mutate_the_shared_requests_module(monkeypatch):
    """Guards against re-wrapping the global `requests.get` (see
    `_ScopedRequestsProxy`'s docstring): that would also wrap unrelated
    callers like the Supabase auth check in `backend/recaps/auth.py`."""
    import requests as requests_module

    original_get = requests_module.get
    monkeypatch.setattr(gateway, "_PATCHED", False)
    install_espn_timeout_patch()
    assert requests_module.get is original_get


def test_patch_translates_timeout_to_typed_error(monkeypatch):
    from espn_api.requests import espn_requests as espn_requests_module

    def _raises_timeout(url, *args, **kwargs):
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(gateway, "_PATCHED", False)
    monkeypatch.setattr(
        espn_requests_module,
        "requests",
        type("_R", (), {"get": staticmethod(_raises_timeout)})(),
    )
    install_espn_timeout_patch()

    with pytest.raises(ESPNTimeoutError):
        espn_requests_module.requests.get("https://example.invalid")


def test_patch_translates_connection_error_to_typed_error(monkeypatch):
    from espn_api.requests import espn_requests as espn_requests_module

    def _raises_connection_error(url, *args, **kwargs):
        raise requests.exceptions.ConnectionError("unreachable")

    monkeypatch.setattr(gateway, "_PATCHED", False)
    monkeypatch.setattr(
        espn_requests_module,
        "requests",
        type("_R", (), {"get": staticmethod(_raises_connection_error)})(),
    )
    install_espn_timeout_patch()

    with pytest.raises(ESPNUnavailableError):
        espn_requests_module.requests.get("https://example.invalid")


# --- espn_get (direct calls, e.g. safe_recent_activity) --------------------

def test_espn_get_sets_default_timeout(monkeypatch):
    captured = {}

    def _spy(url, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(gateway.requests, "get", _spy)
    espn_get("https://example.invalid", cookies={"a": "b"})
    assert captured["timeout"] == ESPN_TIMEOUT
    assert captured["cookies"] == {"a": "b"}


def test_espn_get_respects_caller_supplied_timeout(monkeypatch):
    captured = {}

    def _spy(url, **kwargs):
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(gateway.requests, "get", _spy)
    espn_get("https://example.invalid", timeout=(1, 1))
    assert captured["timeout"] == (1, 1)


def test_espn_get_translates_timeout(monkeypatch):
    def _raises(url, **kwargs):
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(gateway.requests, "get", _raises)
    with pytest.raises(ESPNTimeoutError):
        espn_get("https://example.invalid")


# --- espn_error_status_code -------------------------------------------------

def test_status_code_timeout_is_504():
    assert espn_error_status_code(ESPNTimeoutError("x")) == 504


def test_status_code_unavailable_is_502():
    assert espn_error_status_code(ESPNUnavailableError("x")) == 502


def test_status_code_espn_api_typed_errors_are_502():
    from espn_api.requests.espn_requests import (
        ESPNAccessDenied,
        ESPNInvalidLeague,
        ESPNUnknownError,
    )

    assert espn_error_status_code(ESPNAccessDenied("x")) == 502
    assert espn_error_status_code(ESPNInvalidLeague("x")) == 502
    assert espn_error_status_code(ESPNUnknownError("x")) == 502


def test_status_code_unknown_error_falls_back_to_500():
    assert espn_error_status_code(ValueError("boom")) == 500


# --- deps._espn_http_exception ----------------------------------------------

def test_espn_http_exception_maps_timeout_to_504():
    exc = _espn_http_exception(ESPNTimeoutError("slow"))
    assert isinstance(exc, HTTPException)
    assert exc.status_code == 504


def test_espn_http_exception_maps_unknown_error_to_500():
    exc = _espn_http_exception(ValueError("boom"))
    assert exc.status_code == 500


# --- router integration: previously-unguarded endpoints --------------------

def test_league_meta_returns_504_on_espn_timeout(monkeypatch):
    from fastapi.testclient import TestClient

    import backend.api.main as api
    from backend.api.routers import league as league_router

    def _raise_timeout():
        raise ESPNTimeoutError("ESPN did not respond")

    monkeypatch.setattr(league_router, "_handles", _raise_timeout)
    client = TestClient(api.app)
    resp = client.get("/league/meta")
    assert resp.status_code == 504


def test_league_teams_returns_502_on_espn_unavailable(monkeypatch):
    from fastapi.testclient import TestClient

    import backend.api.main as api
    from backend.api.routers import league as league_router

    def _raise_unavailable():
        raise ESPNUnavailableError("ESPN unreachable")

    monkeypatch.setattr(league_router, "_handles", _raise_unavailable)
    client = TestClient(api.app)
    resp = client.get("/league/teams")
    assert resp.status_code == 502


def test_league_standings_returns_500_on_unexpected_error(monkeypatch):
    from fastapi.testclient import TestClient

    import backend.api.main as api
    from backend.api.routers import league as league_router

    def _raise_generic():
        raise ValueError("unexpected bug")

    monkeypatch.setattr(league_router, "_handles", _raise_generic)
    client = TestClient(api.app)
    resp = client.get("/league/standings")
    assert resp.status_code == 500
