"""Projection-source framework (per docs/specs/PROJECTION_SOURCE_FRAMEWORK.md).

P-1 ships ``EspnAdapter`` and a minimal ``get_active_projections``
accessor for ``horizon='week'``.  The full multi-source
registry arrives in P-2.
"""

from backend.projections.adapter import EspnAdapter, PlayerProjection, ProjectionAdapter
from backend.projections.registry import get_active_projections

__all__ = [
    "EspnAdapter",
    "PlayerProjection",
    "ProjectionAdapter",
    "get_active_projections",
]
