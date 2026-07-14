"""Projection-source framework (per docs/specs/PROJECTION_SOURCE_FRAMEWORK.md).

P-1: EspnAdapter + get_active_projections('week')
P-2: BbmAdapter + on-disk store/manifest + 4 endpoints
"""

from backend.projections.adapter import EspnAdapter, PlayerProjection, ProjectionAdapter
from backend.projections.bbm_adapter import BbmAdapter
from backend.projections.registry import get_active_projections
from backend.projections.store import ProjectionSet, ProjectionStore

__all__ = [
    "BbmAdapter",
    "EspnAdapter",
    "PlayerProjection",
    "ProjectionAdapter",
    "ProjectionSet",
    "ProjectionStore",
    "get_active_projections",
]
