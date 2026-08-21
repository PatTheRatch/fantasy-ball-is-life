"""ESPN transport gateway: explicit timeouts and typed errors.

Port of V1 ``backend/league/gateway.py`` (PR E1). The ``espn-api`` library
issues raw ``requests.get()`` calls with no timeout, so a stalled ESPN
response hangs the caller indefinitely instead of failing (V1 audit: "No
timeout on any ESPN read"). This module enforces a connect/read timeout on
espn-api's own calls and translates transport failures into typed exceptions
so callers can distinguish "ESPN is slow or unreachable" from a genuine
application bug.

Charter §7 (provider adapters at the boundary, never the domain model) and
Decision 28 (failures are visible — a typed error, never a silent hang).

``install_espn_timeout_patch()`` is exported but deliberately *not* called at
import time here: no caller exists yet. It is wired at S1-07 (the ESPN
adapter), the first code that actually issues ESPN reads.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import requests
from requests.exceptions import RequestException, Timeout

CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 15
ESPN_TIMEOUT: tuple[int, int] = (CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)


class ESPNGatewayError(Exception):
    """Base class for typed ESPN transport failures raised by this gateway."""


class ESPNTimeoutError(ESPNGatewayError):
    """ESPN did not respond within the connect/read timeout."""


class ESPNUnavailableError(ESPNGatewayError):
    """ESPN was unreachable or the request otherwise failed at the transport level."""


def _wrap_transport_errors(url: str, call: Callable[[], requests.Response]) -> requests.Response:
    """Run ``call`` and translate transport failures into typed errors.

    ``requests.exceptions.Timeout`` is a subclass of ``RequestException``, so
    it must be caught first — otherwise a timeout would be reported as generic
    unavailability rather than the more specific timeout.
    """
    try:
        return call()
    except Timeout as e:
        raise ESPNTimeoutError(f"ESPN request to {url} timed out") from e
    except RequestException as e:
        raise ESPNUnavailableError(f"ESPN request to {url} failed: {e}") from e


def espn_get(url: str, **kwargs: Any) -> requests.Response:
    """``requests.get`` for direct ESPN calls, with the gateway policy applied."""
    kwargs.setdefault("timeout", ESPN_TIMEOUT)
    return _wrap_transport_errors(url, lambda: requests.get(url, **kwargs))


class _ScopedRequestsProxy:
    """Stands in for the ``requests`` module inside ``espn_api.requests.espn_requests``.

    ``requests`` is a process-wide singleton module, so mutating ``.get``
    directly on it (``requests.get = wrapped``) would apply the gateway policy
    to every caller in the process — including unrelated callers that already
    set their own timeout and catch ``requests.RequestException`` directly;
    wrapping their errors in our typed exceptions would break that handling.
    Rebinding the *name* ``requests`` inside espn_requests's own module
    namespace keeps the patch scoped to espn-api's calls only.
    """

    def __init__(self, real_requests_module: Any) -> None:
        self._real = real_requests_module

    def get(self, url: str, *args: Any, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", ESPN_TIMEOUT)
        return _wrap_transport_errors(url, lambda: self._real.get(url, *args, **kwargs))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


_PATCHED = False


def install_espn_timeout_patch() -> None:
    """Scope the gateway timeout/error policy to espn-api's internal ``requests.get`` calls.

    Idempotent and safe to call from multiple import sites. ``espn_api`` is
    imported lazily so that importing this module costs nothing and stays
    trivially testable; the SDK loads only when the patch actually runs.
    """
    global _PATCHED
    if _PATCHED:
        return

    from espn_api.requests import espn_requests as _espn_requests_module

    _espn_requests_module.requests = _ScopedRequestsProxy(_espn_requests_module.requests)
    _PATCHED = True


def espn_error_status_code(exc: Exception) -> int:
    """Map a typed gateway/espn-api error to an HTTP status code.

    504 for a timeout (ESPN did not respond in time), 502 for any other
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
    if isinstance(
        exc, (ESPNUnavailableError, ESPNAccessDenied, ESPNInvalidLeague, ESPNUnknownError)
    ):
        return 502
    return 500
