"""Identity service: resolve an authenticated principal to a user record.

Get-or-create by ``auth_subject``. Creation is delegated through the bootstrap
repository (the declared unscoped seam); everything after resolution runs
through the scoped ``UserRepository``.
"""

from __future__ import annotations

from backend.models.identity import User
from backend.platform.auth import Principal
from backend.repos.identity import AuthBootstrapRepository


class IdentityResolutionError(Exception):
    """The principal cannot be resolved to a user (missing email claim)."""


def resolve_current_user(
    principal: Principal,
    bootstrap: AuthBootstrapRepository,
) -> User:
    """Return the user for ``principal``, creating it on first login."""
    existing = bootstrap.find_by_auth_subject(principal.auth_subject)
    if existing is not None:
        return existing

    if principal.email is None:
        raise IdentityResolutionError("cannot create a user without an email claim")

    # Display name is a placeholder until a profile flow exists — default to the
    # email so the not-null column is always populated honestly.
    user = User(
        auth_subject=principal.auth_subject,
        email=principal.email,
        display_name=principal.email,
    )
    bootstrap.add(user)
    return user
