"""Matchups sync data access (global scope): season context + matchups.

Two concerns, kept in one file because they share the S1-10a "sync one league's
final periods" job: :class:`LeagueSeasonRepository` loads the season context the
sync needs (season, scoring categories, teams, final periods), and
:class:`MatchupRepository` reads/writes the ``matchups`` + ``matchup_category_results``
facts with supersession semantics (a resync supersedes, never deletes).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.fantasy import (
    Category,
    FantasyTeamSeason,
    LeagueSeason,
    LeagueSeasonCategory,
    Matchup,
    MatchupCategoryResult,
    MatchupPeriod,
)


class LeagueSeasonRepository:
    """Loads one season's sync context."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, league_season_id: uuid.UUID) -> LeagueSeason | None:
        return self.session.get(LeagueSeason, league_season_id)

    def scoring_categories(self, league_season_id: uuid.UUID) -> list[Category]:
        """The season's scoring categories, in ordinal order (D11 — the count is
        whatever the season declares, never assumed to be nine)."""
        return list(
            self.session.scalars(
                select(Category)
                .join(
                    LeagueSeasonCategory,
                    LeagueSeasonCategory.category_id == Category.id,
                )
                .where(
                    LeagueSeasonCategory.league_season_id == league_season_id,
                    LeagueSeasonCategory.is_scoring.is_(True),
                )
                .order_by(LeagueSeasonCategory.ordinal)
            )
        )

    def teams_by_provider(self, league_season_id: uuid.UUID) -> dict[str, FantasyTeamSeason]:
        """The season's teams keyed by ``provider_team_id`` — how scoreboard sides
        resolve to ``fantasy_team_season_id`` (team name is never a join key)."""
        teams = self.session.scalars(
            select(FantasyTeamSeason).where(
                FantasyTeamSeason.league_season_id == league_season_id
            )
        )
        return {t.provider_team_id: t for t in teams}

    def final_periods(self, league_season_id: uuid.UUID) -> list[MatchupPeriod]:
        """The season's ``final`` periods, in ordinal order — the only periods a
        sync ever touches (02-fantasy: final periods are never refetched)."""
        return list(
            self.session.scalars(
                select(MatchupPeriod)
                .where(
                    MatchupPeriod.league_season_id == league_season_id,
                    MatchupPeriod.status == "final",
                )
                .order_by(MatchupPeriod.ordinal)
            )
        )


class MatchupRepository:
    """Reads/writes matchups + category results (supersession, never deletion)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, matchup: Matchup) -> None:
        self.session.add(matchup)

    def add_category_result(self, result: MatchupCategoryResult) -> None:
        self.session.add(result)

    def find_live(
        self, matchup_period_id: uuid.UUID, home_team_season_id: uuid.UUID
    ) -> Matchup | None:
        """The non-superseded matchup for a slot (one per period+home team)."""
        return self.session.scalars(
            select(Matchup).where(
                Matchup.matchup_period_id == matchup_period_id,
                Matchup.home_team_season_id == home_team_season_id,
                Matchup.superseded_at.is_(None),
            )
        ).one_or_none()

    def category_results(self, matchup_id: uuid.UUID) -> list[MatchupCategoryResult]:
        """A matchup's category rows, for the idempotency comparison."""
        return list(
            self.session.scalars(
                select(MatchupCategoryResult).where(
                    MatchupCategoryResult.matchup_id == matchup_id
                )
            )
        )

    def flush(self) -> None:
        """Materialize pending UUIDv7 ids so a superseding link can be set."""
        self.session.flush()
