"""ESPN transport gateway.

Invariant register: docs/v2/V1_CLASSIFICATION.md §7 "Transport policy".
Ported from V1 tests/test_espn_gateway.py (PR E1).

These encode the audit finding "no timeout on any ESPN read": a stalled ESPN
response used to hang the request indefinitely, and transport failures were
surfaced as generic 500s instead of a distinct timeout/unavailable signal.
"""

from __future__ import annotations

import pytest
import requests
from espn_api.requests import espn_requests as espn_requests_module

from backend.providers.espn import client
from backend.providers.espn.client import (
    ESPN_TIMEOUT,
    ESPNTimeoutError,
    ESPNUnavailableError,
    espn_error_status_code,
    espn_get,
    install_espn_timeout_patch,
)

# --- install_espn_timeout_patch --------------------------------------------

# V1: test_patch_applies_default_timeout_to_espn_api_requests_get
def test_patch_applies_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _spy(url: str, *args: object, **kwargs: object) -> str:
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(client, "_PATCHED", False)
    monkeypatch.setattr(
        espn_requests_module, "requests",
        type("_Spy", (), {"get": staticmethod(_spy)})(),
    )
    install_espn_timeout_patch()

    espn_requests_module.requests.get("https://example.invalid")
    assert captured["timeout"] == ESPN_TIMEOUT


# V1: test_patch_is_idempotent
def test_patch_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client, "_PATCHED", False)
    install_espn_timeout_patch()
    proxy_once = espn_requests_module.requests
    install_espn_timeout_patch()
    assert espn_requests_module.requests is proxy_once


# V1: test_patch_does_not_mutate_the_shared_requests_module
def test_patch_does_not_mutate_shared_requests_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The patch must not re-wrap the global ``requests.get`` — that would also
    wrap unrelated callers that set their own timeout and catch
    ``requests.RequestException`` directly."""
    import requests as requests_module

    original_get = requests_module.get
    monkeypatch.setattr(client, "_PATCHED", False)
    install_espn_timeout_patch()
    assert requests_module.get is original_get


# V1: test_patch_translates_timeout_to_typed_error
def test_patch_translates_timeout_to_typed_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raises_timeout(url: str, *args: object, **kwargs: object) -> None:
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(client, "_PATCHED", False)
    monkeypatch.setattr(
        espn_requests_module, "requests",
        type("_RaisesTimeout", (), {"get": staticmethod(_raises_timeout)})(),
    )
    install_espn_timeout_patch()

    with pytest.raises(ESPNTimeoutError):
        espn_requests_module.requests.get("https://example.invalid")


# V1: test_patch_translates_connection_error_to_typed_error
def test_patch_translates_connection_error_to_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raises_connection_error(url: str, *args: object, **kwargs: object) -> None:
        raise requests.exceptions.ConnectionError("unreachable")

    monkeypatch.setattr(client, "_PATCHED", False)
    monkeypatch.setattr(
        espn_requests_module, "requests",
        type("_RaisesConn", (), {"get": staticmethod(_raises_connection_error)})(),
    )
    install_espn_timeout_patch()

    with pytest.raises(ESPNUnavailableError):
        espn_requests_module.requests.get("https://example.invalid")


# --- espn_get (direct calls) ------------------------------------------------

# V1: test_espn_get_sets_default_timeout
def test_espn_get_sets_default_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _spy(url: str, **kwargs: object) -> str:
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(client.requests, "get", _spy)
    espn_get("https://example.invalid", cookies={"a": "b"})
    assert captured["timeout"] == ESPN_TIMEOUT
    assert captured["cookies"] == {"a": "b"}


# V1: test_espn_get_respects_caller_supplied_timeout
def test_espn_get_respects_caller_supplied_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def _spy(url: str, **kwargs: object) -> str:
        captured.update(kwargs)
        return "ok"

    monkeypatch.setattr(client.requests, "get", _spy)
    espn_get("https://example.invalid", timeout=(1, 1))
    assert captured["timeout"] == (1, 1)


# V1: test_espn_get_translates_timeout
def test_espn_get_translates_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raises(url: str, **kwargs: object) -> None:
        raise requests.exceptions.Timeout("slow")

    monkeypatch.setattr(client.requests, "get", _raises)
    with pytest.raises(ESPNTimeoutError):
        espn_get("https://example.invalid")


# --- espn_error_status_code -------------------------------------------------

# V1: test_status_code_timeout_is_504
def test_status_code_timeout_is_504() -> None:
    assert espn_error_status_code(ESPNTimeoutError("x")) == 504


# V1: test_status_code_unavailable_is_502
def test_status_code_unavailable_is_502() -> None:
    assert espn_error_status_code(ESPNUnavailableError("x")) == 502


# V1: test_status_code_espn_api_typed_errors_are_502
def test_status_code_espn_api_typed_errors_are_502() -> None:
    from espn_api.requests.espn_requests import (
        ESPNAccessDenied,
        ESPNInvalidLeague,
        ESPNUnknownError,
    )

    assert espn_error_status_code(ESPNAccessDenied("x")) == 502
    assert espn_error_status_code(ESPNInvalidLeague("x")) == 502
    assert espn_error_status_code(ESPNUnknownError("x")) == 502


# V1: test_status_code_unknown_error_falls_back_to_500
def test_status_code_unknown_error_falls_back_to_500() -> None:
    assert espn_error_status_code(ValueError("boom")) == 500
