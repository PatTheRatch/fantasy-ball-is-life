"""Claim repositories: user-by-email lookup and the manager↔user link (D-03).

The claim is an *operator* action (the CLI), not a scoped user action — there is
no ``user_id`` to scope on until the user is found. These repositories take a
plain ``Session``, exactly as the bootstrap repositories do, and are deliberately
kept out of the read path (which stays scoped).

Two invariants the caller must respect (and the service enforces):

- **Never create a user.** ``users.auth_subject`` is ``NOT NULL UNIQUE`` and
  holds the IdP's subject claim; an invented one would fork a second user at the
  first real sign-in. Look up by email, fail if absent.
- **Get-or-create the link.** ``uq_manager_user_links_manager_user`` makes
  ``(manager_id, user_id)`` unique, so a re-run must be a no-op, not a crash.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.fantasy import FantasyTeamSeason
from backend.models.identity import FantasyTeamSeasonManager, Manager, ManagerUserLink, User


@dataclass(frozen=True, slots=True)
class TeamChoice:
    """A claimable team, as the CLI lists it (self-describing, no DB needed)."""

    provider_team_id: str
    name: str
    owner_manager: str


class ClaimRepository:
    """Cross-tenant lookups for the claim operation (D-03)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_user_by_email(self, email: str) -> User | None:
        """The existing user for ``email``, or ``None``. Never creates one."""
        return self.session.scalars(
            select(User).where(User.email == email)
        ).one_or_none()

    def find_team_season(
        self, league_season_id: uuid.UUID, provider_team_id: str
    ) -> FantasyTeamSeason | None:
        return self.session.scalars(
            select(FantasyTeamSeason).where(
                FantasyTeamSeason.league_season_id == league_season_id,
                FantasyTeamSeason.provider_team_id == provider_team_id,
            )
        ).one_or_none()

    def find_owner_manager(self, fantasy_team_season_id: uuid.UUID) -> Manager | None:
        """The team-season's ``owner``-role manager (the claimable identity)."""
        return self.session.scalars(
            select(Manager)
            .join(
                FantasyTeamSeasonManager,
                FantasyTeamSeasonManager.manager_id == Manager.id,
            )
            .where(
                FantasyTeamSeasonManager.fantasy_team_season_id == fantasy_team_season_id,
                FantasyTeamSeasonManager.role == "owner",
            )
        ).one_or_none()

    def find_link(self, manager_id: uuid.UUID, user_id: uuid.UUID) -> ManagerUserLink | None:
        return self.session.scalars(
            select(ManagerUserLink).where(
                ManagerUserLink.manager_id == manager_id,
                ManagerUserLink.user_id == user_id,
            )
        ).one_or_none()

    def list_teams(self, league_season_id: uuid.UUID) -> list[TeamChoice]:
        """Every team in a season, each with its owner manager's display name."""
        rows = self.session.execute(
            select(FantasyTeamSeason, Manager.display_name)
            .join(
                FantasyTeamSeasonManager,
                FantasyTeamSeasonManager.fantasy_team_season_id == FantasyTeamSeason.id,
            )
            .join(Manager, Manager.id == FantasyTeamSeasonManager.manager_id)
            .where(
                FantasyTeamSeason.league_season_id == league_season_id,
                FantasyTeamSeasonManager.role == "owner",
            )
            .order_by(FantasyTeamSeason.provider_team_id)
        ).all()
        return [
            TeamChoice(team.provider_team_id, team.name, owner_name)
            for team, owner_name in rows
        ]

    def add(self, link: ManagerUserLink) -> None:
        self.session.add(link)

    def commit(self) -> None:
        self.session.commit()
