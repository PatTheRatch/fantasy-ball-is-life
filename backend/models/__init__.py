"""ORM models.

Models import SQLAlchemy, so they live here rather than in ``backend.domain``,
which the architecture test keeps free of I/O and infrastructure imports.
"""

from backend.models.fantasy import (
    Category,
    FantasyTeam,
    FantasyTeamSeason,
    League,
    LeagueSeason,
    LeagueSeasonCategory,
    MatchupPeriod,
)
from backend.models.identity import (
    FantasyTeamSeasonManager,
    Manager,
    ManagerUserLink,
    User,
)
from backend.models.ingestion import (
    IngestionRun,
    Provider,
    ProviderConnection,
    RawPayload,
)
from backend.models.nba import NbaSeason

__all__ = [
    "Category",
    "FantasyTeam",
    "FantasyTeamSeason",
    "FantasyTeamSeasonManager",
    "IngestionRun",
    "League",
    "LeagueSeason",
    "LeagueSeasonCategory",
    "Manager",
    "ManagerUserLink",
    "MatchupPeriod",
    "NbaSeason",
    "Provider",
    "ProviderConnection",
    "RawPayload",
    "User",
]
