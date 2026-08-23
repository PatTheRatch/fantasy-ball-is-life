"""Tenancy scope value objects.

Scopes are the structural gate for repository construction (charter D26):
a scoped repository *cannot* be built without one. They are frozen so a scope
cannot be mutated after a repository is bound to it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class UserScope:
    """A single authenticated user's tenancy boundary."""

    user_id: uuid.UUID


@dataclass(frozen=True)
class LeagueScope:
    """A single league's tenancy boundary."""

    league_id: uuid.UUID


@dataclass(frozen=True)
class LeagueSeasonScope:
    """A single league_season's tenancy boundary.

    The scope object for every real league table (S1-06 keyed them on
    ``league_season_id``), in contrast to :class:`LeagueScope` which is the
    franchise-level boundary (``fantasy_teams`` outlives any one season).
    """

    league_season_id: uuid.UUID
