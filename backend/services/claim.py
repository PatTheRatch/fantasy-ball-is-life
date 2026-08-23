"""League claim: link a real user to a manager (D-03).

The auditable act D-01 deliberately left undone. The CLI is the only caller: it
finds an *existing* user by email and links them to a team-season's ``owner``
manager. It never creates a user — an invented ``auth_subject`` would fork a
second user at the first real sign-in (see ``01-identity.md`` / charter D13).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from backend.models.identity import ManagerUserLink
from backend.repos.claim import ClaimRepository, TeamChoice


class ClaimError(Exception):
    """The claim could not run."""


class UnknownUserError(ClaimError):
    """No user row for the email — sign in once first, then re-run."""


class UnknownTeamError(ClaimError):
    """No team-season with that ``provider_team_id`` in this season."""


@dataclass(frozen=True, slots=True)
class ClaimResult:
    """What one claim did."""

    manager_display_name: str
    team_name: str
    created: bool


class LeagueClaimService:
    """Turns a bootstrapped league into one the user can read."""

    def __init__(self, repo: ClaimRepository) -> None:
        self.repo = repo

    def list_teams(self, league_season_id: uuid.UUID) -> list[TeamChoice]:
        """The season's claimable teams, for the CLI's self-describing list."""
        return self.repo.list_teams(league_season_id)

    def claim(
        self, league_season_id: uuid.UUID, email: str, provider_team_id: str
    ) -> ClaimResult:
        """Link ``email``'s user to ``provider_team_id``'s owner manager.

        Idempotent: re-running over an already-linked pair is a no-op. Never
        creates a user — an unknown email raises :class:`UnknownUserError`.
        """
        user = self.repo.find_user_by_email(email)
        if user is None:
            raise UnknownUserError(
                f"no user with email {email!r}; sign in once through the frontend "
                f"(that creates the user row), then re-run with --claim-email"
            )

        team = self.repo.find_team_season(league_season_id, provider_team_id)
        if team is None:
            raise UnknownTeamError(
                f"no team with provider_team_id {provider_team_id!r} in this season"
            )

        manager = self.repo.find_owner_manager(team.id)
        if manager is None:
            raise ClaimError(f"team {team.name!r} has no owner manager to claim")

        created = False
        if self.repo.find_link(manager.id, user.id) is None:
            self.repo.add(
                ManagerUserLink(manager_id=manager.id, user_id=user.id, is_primary=True)
            )
            created = True

        self.repo.commit()
        return ClaimResult(
            manager_display_name=manager.display_name, team_name=team.name, created=created
        )
