"""Route-policy matrix: every route declares a policy, or CI fails.

This is the structural half of charter D26 / non-negotiable #1 — no route
ships without an explicit authorization policy. The negative test proves the
gate actually bites.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.routing import APIRoute

from backend.api.app import create_app
from backend.api.policy import POLICY_ATTR

#: Framework routes FastAPI adds for itself (openapi/docs/redoc). These are not
#: application endpoints and carry no policy.
FRAMEWORK_PATH_PREFIXES = ("/openapi.json", "/docs", "/redoc")


def _is_framework_route(route: object) -> bool:
    path = getattr(route, "path", "") or ""
    return path.startswith(FRAMEWORK_PATH_PREFIXES)


def _iter_api_routes(route: object) -> Iterator[APIRoute]:
    if isinstance(route, APIRoute):
        yield route
        return
    # FastAPI 0.139+ wraps each include_router call in an internal container
    # that holds the original APIRouter; walk into it to reach the APIRoutes.
    original = getattr(route, "original_router", None)
    for child in getattr(original, "routes", None) or []:
        yield from _iter_api_routes(child)


def _undeclared_routes(app: FastAPI) -> list[str]:
    undeclared: list[str] = []
    for route in app.routes:
        if _is_framework_route(route):
            continue
        api_routes = list(_iter_api_routes(route))
        if not api_routes:
            undeclared.append(f"non-API route without policy: {route!r}")
            continue
        for api_route in api_routes:
            if getattr(api_route.endpoint, POLICY_ATTR, None) is None:
                methods = ",".join(sorted(api_route.methods or []))
                undeclared.append(f"{methods} {api_route.path}")
    return undeclared


def test_every_route_declares_a_policy() -> None:
    app = create_app()
    assert _undeclared_routes(app) == []


def test_undeclared_route_is_detected() -> None:
    """Negative meta-test: an endpoint without a policy must be flagged."""
    bad_app = FastAPI()

    @bad_app.get("/unprotected")
    def unprotected() -> dict[str, str]:
        return {"ok": True}

    assert _undeclared_routes(bad_app) == ["GET /unprotected"]
