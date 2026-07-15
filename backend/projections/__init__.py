"""Projection-source framework (per docs/specs/PROJECTION_SOURCE_FRAMEWORK.md).

P-1: EspnAdapter + get_active_projections('week')
P-2: BbmAdapter + on-disk store/manifest + 4 endpoints
P-3: Consumer swap (scoreboard + optimizer)
P-4: Projection badge UI
P-5: HashtagAdapter (file + paste-input)
P-6: Week-scoping, virtual ESPN, explicit-request-wins precedence
"""

from backend.projections.adapter import EspnAdapter, PlayerProjection, ProjectionAdapter
from backend.projections.bbm_adapter import BbmAdapter
from backend.projections.hashtag_adapter import HashtagAdapter
from backend.projections.registry import get_active_projections
from backend.projections.store import (
    ESPN_VIRTUAL_SET_ID,
    ProjectionSet,
    ProjectionStore,
)

__all__ = [
    "BbmAdapter",
    "ESPN_VIRTUAL_SET_ID",
    "EspnAdapter",
    "HashtagAdapter",
    "PlayerProjection",
    "ProjectionAdapter",
    "ProjectionSet",
    "ProjectionStore",
    "get_active_projections",
]
