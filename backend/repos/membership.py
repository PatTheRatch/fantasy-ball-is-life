"""League-membership existence check (global scope)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.fantasy import FantasyTeamSeason
from backend.models.identity import FantasyTeamSeasonManager, ManagerUserLink


class LeagueMembershipRepository:
    """Answers "is this user a manager of any team in this league_season?".

    The V1 read path had no membership check at all — knowing a slug was enough
    to read a private league's standings. This existence query is the gate the
    ``LEAGUE_SCOPED`` policy hangs off, following the chain ``users → managers →
    fantasy_team_season_managers → fantasy_team_seasons`` (the last carries the
    ``league_season_id``).
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def is_member(self, league_season_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = (
            select(FantasyTeamSeasonManager.id)
            .join(
                ManagerUserLink,
                ManagerUserLink.manager_id == FantasyTeamSeasonManager.manager_id,
            )
            .join(
                FantasyTeamSeason,
                FantasyTeamSeason.id == FantasyTeamSeasonManager.fantasy_team_season_id,
            )
            .where(
                ManagerUserLink.user_id == user_id,
                FantasyTeamSeason.league_season_id == league_season_id,
            )
            .limit(1)
        )
        return self.session.scalars(stmt).first() is not None
