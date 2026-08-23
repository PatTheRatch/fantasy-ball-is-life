"""Route policy declaration.

Every route declares a :class:`RoutePolicy` via :func:`declare_policy`. The
matrix test (``tests/api/test_route_policy_matrix.py``) enumerates every route
on ``create_app()`` and enforces charter D26 / non-negotiable #1 in two ways:
it fails CI if any route lacks a declared policy, and it walks each route's
transitive dependency graph to verify the policy's required dependency is
actually present — a declared policy is a promise, not a label.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any, TypeVar

#: Attribute set on an endpoint by :func:`declare_policy`.
POLICY_ATTR = "_fcp_route_policy"


class RoutePolicy(StrEnum):
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    LEAGUE_SCOPED = "league_scoped"
    MANAGER_PRIVATE = "manager_private"


_F = TypeVar("_F", bound=Callable[..., Any])


def declare_policy(policy: RoutePolicy) -> Callable[[_F], _F]:
    """Tag an endpoint with its required policy."""

    def decorator(endpoint: _F) -> _F:
        setattr(endpoint, POLICY_ATTR, policy)
        return endpoint

    return decorator


def route_policy(endpoint: Any) -> RoutePolicy | None:
    """Return the declared policy for an endpoint, or ``None`` if undeclared."""
    return getattr(endpoint, POLICY_ATTR, None)
