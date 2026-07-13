"""ESPN HTTP gateway: explicit timeouts and typed errors for every ESPN read.

The installed `espn-api` library issues raw `requests.get()` calls with no
timeout (`espn_api.requests.espn_requests.EspnFantasyRequests.league_get` /
`.get` / `.news_get`), so a stalled ESPN response hangs the request
indefinitely instead of failing. This module patches those calls in place to
enforce a connect/read timeout, and translates transport failures into typed
exceptions so callers (and eventually routers) can distinguish "ESPN is slow
or unreachable" from a genuine application bug.

`install_espn_timeout_patch()` must run before any ESPN call is made; it is
called at import time by `backend.league.data_feed`, which every ESPN entry
point (`connect()`, `MyLeague`) already imports.
"""
from __future__ import annotations

import requests
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import RequestException, Timeout

CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 15
ESPN_TIMEOUT = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)


class ESPNGatewayError(Exception):
    """Base class for typed ESPN transport failures raised by this gateway."""


class ESPNTimeoutError(ESPNGatewayError):
    """ESPN did not respond within the connect/read timeout."""


class ESPNUnavailableError(ESPNGatewayError):
    """ESPN was unreachable or the request otherwise failed at the transport level."""


def _wrap_transport_errors(url, call):
    try:
        return call()
    except Timeout as e:
        raise ESPNTimeoutError(f"ESPN request to {url} timed out") from e
    except (RequestsConnectionError, RequestException) as e:
        raise ESPNUnavailableError(f"ESPN request to {url} failed: {e}") from e


def espn_get(url: str, **kwargs):
    """`requests.get` for our own direct ESPN calls, with the gateway policy applied."""
    kwargs.setdefault("timeout", ESPN_TIMEOUT)
    return _wrap_transport_errors(url, lambda: requests.get(url, **kwargs))


class _ScopedRequestsProxy:
    """Stands in for the `requests` module inside `espn_api.requests.espn_requests`.

    `requests` is a process-wide singleton module, so mutating `.get` directly
    on it (``requests.get = wrapped``) would apply the gateway policy to every
    caller in the process -- including `backend/recaps/auth.py`'s Supabase
    call, which already sets its own timeout and catches
    `requests.RequestException` directly; wrapping its errors in our typed
    exceptions would break that handling. Rebinding the *name* `requests`
    inside espn_requests's own module namespace instead keeps the patch
    scoped to espn-api's own calls only.
    """

    def __init__(self, real_requests_module):
        self._real = real_requests_module

    def get(self, url, *args, **kwargs):
        kwargs.setdefault("timeout", ESPN_TIMEOUT)
        return _wrap_transport_errors(url, lambda: self._real.get(url, *args, **kwargs))

    def __getattr__(self, name):
        return getattr(self._real, name)


_PATCHED = False


def install_espn_timeout_patch() -> None:
    """Scope the gateway timeout/error policy to espn-api's internal `requests.get` calls.

    Idempotent and safe to call from multiple import sites.
    """
    global _PATCHED
    if _PATCHED:
        return

    from espn_api.requests import espn_requests as _espn_requests_module

    _espn_requests_module.requests = _ScopedRequestsProxy(_espn_requests_module.requests)
    _PATCHED = True


def espn_error_status_code(exc: Exception) -> int:
    """Map a typed gateway/espn-api error to an HTTP status code.

    504 for a timeout (ESPN didn't respond in time), 502 for any other
    upstream/transport failure (unreachable, non-200, access denied), 500 for
    anything not recognized as an ESPN-origin failure.
    """
    from espn_api.requests.espn_requests import (
        ESPNAccessDenied,
        ESPNInvalidLeague,
        ESPNUnknownError,
    )

    if isinstance(exc, ESPNTimeoutError):
        return 504
    if isinstance(exc, (ESPNUnavailableError, ESPNAccessDenied, ESPNInvalidLeague, ESPNUnknownError)):
        return 502
    return 500
