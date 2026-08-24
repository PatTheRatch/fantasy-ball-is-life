"""Route-policy matrix: every route declares a policy and honours it, or CI fails.

This is the structural half of charter D26 / non-negotiable #1 — no route
ships without an explicit authorization policy, and a declared policy is
*enforced*, not just labelled: the policy's required dependency must be present
in the route's *transitive* dependency graph. Negative tests prove both gates
bite.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from backend.api.app import create_app
from backend.api.deps import (
    get_current_user,
    get_db,
    get_standings_service,
    require_league_member,
)
from backend.api.policy import POLICY_ATTR, RoutePolicy, declare_policy
from backend.services.standings_read import StandingsReadService

#: Framework routes FastAPI adds for itself (openapi/docs/redoc). These are not
#: application endpoints and carry no policy.
FRAMEWORK_PATH_PREFIXES = ("/openapi.json", "/docs", "/redoc")

#: Sentinel marking a ``RoutePolicy`` that exists but has no enforcement rule
#: yet (``MANAGER_PRIVATE``). A route declaring it is flagged — a policy the
#: harness cannot enforce must not be declarable.
_NO_ENFORCEMENT = object()

#: The dependency that must appear in a route's transitive dependency graph for
#: its policy to be satisfied. ``None`` means "nothing required" (PUBLIC). The
#: map is *total* over ``RoutePolicy`` (``MANAGER_PRIVATE`` included) — a member
#: with no entry is a hole, caught by ``_unmapped_policies``.
POLICY_REQUIRED_DEPENDENCY: dict[RoutePolicy, Any] = {
    RoutePolicy.PUBLIC: None,
    RoutePolicy.AUTHENTICATED: get_current_user,
    RoutePolicy.LEAGUE_SCOPED: require_league_member,
    RoutePolicy.MANAGER_PRIVATE: _NO_ENFORCEMENT,
}


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


def _dependency_calls(dependant: Any) -> set[Any]:
    """Every callable reachable from a route's ``Dependant``, transitively.

    Recurse through ``.dependencies`` and collect each ``.call`` into a set.
    Transitive (a dependency's own dependencies count, so ``require_league_member``
    satisfies ``AUTHENTICATED`` through ``get_current_user``) and deduplicated
    (``require_league_member`` appears both directly and via
    ``get_standings_service``). A ``seen`` set on ``id()`` guards the walk
    against a pathological cycle.
    """
    seen: set[int] = set()
    calls: set[Any] = set()

    def walk(node: Any) -> None:
        if id(node) in seen:
            return
        seen.add(id(node))
        calls.add(node.call)
        for child in node.dependencies:
            walk(child)

    walk(dependant)
    return calls


def _unmet_routes(app: FastAPI) -> list[str]:
    """Routes whose declared policy is not satisfied by their dependency graph."""
    unmet: list[str] = []
    for route in app.routes:
        if _is_framework_route(route):
            continue
        for api_route in _iter_api_routes(route):
            policy = getattr(api_route.endpoint, POLICY_ATTR, None)
            if policy is None:
                continue  # undeclared is _undeclared_routes' job
            methods = ",".join(sorted(api_route.methods or []))
            required = POLICY_REQUIRED_DEPENDENCY.get(policy, _NO_ENFORCEMENT)
            if required is _NO_ENFORCEMENT:
                unmet.append(
                    f"{methods} {api_route.path}: {policy.value} has no enforcement rule"
                )
                continue
            if required is None:
                continue  # PUBLIC — nothing required
            if required not in _dependency_calls(api_route.dependant):
                unmet.append(
                    f"{methods} {api_route.path}: missing {required.__name__}"
                )
    return unmet


def _unmapped_policies(policy_map: dict[RoutePolicy, Any]) -> list[RoutePolicy]:
    """``RoutePolicy`` members with no enforcement entry, driven from the enum.

    A new member added to the enum without a rule lands here and fails CI — this
    is why the map must be total rather than a hand-picked subset.
    """
    return [policy for policy in RoutePolicy if policy not in policy_map]


# --- positive -----------------------------------------------------------------


def test_every_route_declares_a_policy() -> None:
    app = create_app(load_from_env=False)
    assert _undeclared_routes(app) == []


def test_every_route_satisfies_its_policy() -> None:
    app = create_app(load_from_env=False)
    assert _unmet_routes(app) == []


def test_every_policy_has_an_enforcement_entry() -> None:
    assert _unmapped_policies(POLICY_REQUIRED_DEPENDENCY) == []


# --- negative -----------------------------------------------------------------


def test_undeclared_route_is_detected() -> None:
    """Negative meta-test: an endpoint without a policy must be flagged."""
    bad_app = FastAPI()

    @bad_app.get("/unprotected")
    def unprotected() -> dict[str, str]:
        return {"ok": True}

    assert _undeclared_routes(bad_app) == ["GET /unprotected"]


def test_league_scoped_without_membership_is_detected() -> None:
    """A LEAGUE_SCOPED route with no require_league_member anywhere is flagged."""
    bad_app = FastAPI()

    @bad_app.get("/leagues/{league_season_id}/secrets")
    @declare_policy(RoutePolicy.LEAGUE_SCOPED)
    def secrets(
        league_season_id: uuid.UUID, session: Session = Depends(get_db)  # noqa: B008
    ):
        return {"ok": True}

    assert _unmet_routes(bad_app) == [
        "GET /leagues/{league_season_id}/secrets: missing require_league_member"
    ]


def test_authenticated_without_get_current_user_is_detected() -> None:
    """An AUTHENTICATED route with no get_current_user in its graph is flagged."""
    bad_app = FastAPI()

    @bad_app.get("/me")
    @declare_policy(RoutePolicy.AUTHENTICATED)
    def me(session: Session = Depends(get_db)):  # noqa: B008 — FastAPI idiom
        return {"ok": True}

    assert _unmet_routes(bad_app) == ["GET /me: missing get_current_user"]


def test_transitive_satisfaction_is_not_flagged() -> None:
    """A policy satisfied only through an intermediate is not flagged.

    ``get_standings_service`` depends on ``require_league_member`` (which depends
    on ``get_current_user``), so the LEAGUE_SCOPED requirement is met
    transitively. A direct-dependency walk would falsely reject this route.
    """
    good_app = FastAPI()

    @good_app.get("/leagues/{league_season_id}/standings")
    @declare_policy(RoutePolicy.LEAGUE_SCOPED)
    def standings(
        svc: StandingsReadService = Depends(get_standings_service)  # noqa: B008
    ):
        return {"ok": True}

    assert _unmet_routes(good_app) == []


def test_policy_missing_from_map_is_detected() -> None:
    """A RoutePolicy member absent from the map is flagged (driven from the enum)."""
    partial = dict(POLICY_REQUIRED_DEPENDENCY)
    del partial[RoutePolicy.MANAGER_PRIVATE]
    assert _unmapped_policies(partial) == [RoutePolicy.MANAGER_PRIVATE]


def test_policy_without_enforcement_rule_is_flagged() -> None:
    """A route declaring a policy that has no enforcement rule yet is flagged."""
    bad_app = FastAPI()

    @bad_app.get("/admin/secrets")
    @declare_policy(RoutePolicy.MANAGER_PRIVATE)
    def secrets() -> dict[str, str]:
        return {"ok": True}

    assert _unmet_routes(bad_app) == [
        "GET /admin/secrets: manager_private has no enforcement rule"
    ]
