"""Matchups data access (league_season scope): season context + matchups.

Two concerns, kept in one file because they share the S1-10a "sync one league's
final periods" job: :class:`LeagueSeasonRepository` loads the season context the
sync needs (season, scoring categories, teams, final periods), and
:class:`MatchupRepository` reads/writes the ``matchups`` + ``matchup_category_results``
facts with supersession semantics (a resync supersedes, never deletes).

Both are :class:`~backend.repos.base.LeagueSeasonScopedRepository` subclasses:
they cannot be constructed without a :class:`~backend.repos.scope.LeagueSeasonScope`,
and every read is scope-filtered (charter D26 — tenancy is structural, not a
convention).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select

from backend.models.fantasy import (
    Category,
    FantasyTeamSeason,
    LeagueSeason,
    LeagueSeasonCategory,
    Matchup,
    MatchupCategoryResult,
    MatchupPeriod,
)
from backend.repos.base import LeagueSeasonScopedRepository


class LeagueSeasonRepository(LeagueSeasonScopedRepository):
    """Loads one season's sync context, scoped to a single league_season."""

    def get(self) -> LeagueSeason | None:
        # Reads the ``league_seasons`` row itself, whose primary key *is* the
        # scope's ``league_season_id`` — so it goes through ``session.get``
        # directly rather than ``scoped_select`` (whose ``league_season_id``
        # column does not exist on the ``league_seasons`` table). The other
        # methods read tables that carry ``league_season_id`` and use the
        # default ``scope_column``.
        return self.session.get(LeagueSeason, self.scope.league_season_id)

    def scoring_categories(self) -> list[Category]:
        """The season's scoring categories, in ordinal order (D11 — the count is
        whatever the season declares, never assumed to be nine)."""
        # The scope column lives on the join table ``LeagueSeasonCategory``, not
        # on the reference ``Category`` table, so this filters on the join table
        # rather than via ``scoped_select(Category)``.
        return list(
            self.session.scalars(
                select(Category)
                .join(
                    LeagueSeasonCategory,
                    LeagueSeasonCategory.category_id == Category.id,
                )
                .where(
                    LeagueSeasonCategory.league_season_id
                    == self.scope.league_season_id,
                    LeagueSeasonCategory.is_scoring.is_(True),
                )
                .order_by(LeagueSeasonCategory.ordinal)
            )
        )

    def teams_by_provider(self) -> dict[str, FantasyTeamSeason]:
        """The season's teams keyed by ``provider_team_id`` — how scoreboard sides
        resolve to ``fantasy_team_season_id`` (team name is never a join key)."""
        teams = self.session.scalars(self.scoped_select(FantasyTeamSeason))
        return {t.provider_team_id: t for t in teams}

    def final_periods(self) -> list[MatchupPeriod]:
        """The season's ``final`` periods, in ordinal order — the only periods a
        sync ever touches (02-fantasy: final periods are never refetched)."""
        return list(
            self.session.scalars(
                self.scoped_select(MatchupPeriod)
                .where(MatchupPeriod.status == "final")
                .order_by(MatchupPeriod.ordinal)
            )
        )

    def periods(self) -> list[MatchupPeriod]:
        """Every period in the season, ordinal-ordered — including the ones not
        yet played.

        The reader needs the season's actual shape (a half-finished season must
        not look complete). Which periods are *selectable* is a UI decision the
        caller makes from ``status``; this returns them all.
        """
        return list(
            self.session.scalars(
                self.scoped_select(MatchupPeriod).order_by(MatchupPeriod.ordinal)
            )
        )

    def teams(self) -> list[FantasyTeamSeason]:
        """All teams in a season, for name/abbreviation enrichment on read."""
        return list(self.session.scalars(self.scoped_select(FantasyTeamSeason)))


class MatchupRepository(LeagueSeasonScopedRepository):
    """Reads/writes matchups + category results (supersession, never deletion)."""

    def add(self, matchup: Matchup) -> None:
        self.session.add(matchup)

    def add_category_result(self, result: MatchupCategoryResult) -> None:
        self.session.add(result)

    def find_live(
        self, matchup_period_id: uuid.UUID, home_team_season_id: uuid.UUID
    ) -> Matchup | None:
        """The non-superseded matchup for a slot (one per period+home team)."""
        return self.session.scalars(
            self.scoped_select(Matchup).where(
                Matchup.matchup_period_id == matchup_period_id,
                Matchup.home_team_season_id == home_team_season_id,
                Matchup.superseded_at.is_(None),
            )
        ).one_or_none()

    def category_results(self, matchup_id: uuid.UUID) -> list[MatchupCategoryResult]:
        """A matchup's category rows, for the idempotency comparison.

        ``MatchupCategoryResult`` has no league column, so the scope is applied
        by joining through ``matchups`` (charter D26) — the ids are not trusted
        to be pre-scoped.
        """
        return list(
            self.session.scalars(
                select(MatchupCategoryResult)
                .join(Matchup, MatchupCategoryResult.matchup_id == Matchup.id)
                .where(
                    Matchup.league_season_id == self.scope.league_season_id,
                    MatchupCategoryResult.matchup_id == matchup_id,
                )
            )
        )

    def live_for_season(
        self,
        *,
        period_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[Matchup]:
        """Non-superseded matchups for the scoped season, optionally limited to
        periods.

        The standings read path calls this with the ``final`` periods it wants
        folded, so a superseded row is excluded here rather than post-filtered.
        """
        stmt = self.scoped_select(Matchup).where(Matchup.superseded_at.is_(None))
        if period_ids is not None:
            stmt = stmt.where(Matchup.matchup_period_id.in_(period_ids))
        return list(self.session.scalars(stmt))

    def category_results_for(
        self, matchup_ids: Sequence[uuid.UUID]
    ) -> list[MatchupCategoryResult]:
        """Batch category rows for many matchups (avoids an N+1 on read).

        Scoped by joining through ``matchups`` — ``MatchupCategoryResult`` has no
        league column of its own.
        """
        if not matchup_ids:
            return []
        return list(
            self.session.scalars(
                select(MatchupCategoryResult)
                .join(Matchup, MatchupCategoryResult.matchup_id == Matchup.id)
                .where(
                    Matchup.league_season_id == self.scope.league_season_id,
                    MatchupCategoryResult.matchup_id.in_(matchup_ids),
                )
            )
        )

    def flush(self) -> None:
        """Flush pending writes.

        The sync uses this to control supersession ordering — the old row's
        ``superseded_at`` must hit the database before the new live row is
        inserted (else the partial unique index rejects the insert).
        """
        self.session.flush()

    def commit(self) -> None:
        """Commit the session.

        The finalize path commits per period (not per run) so a mid-run failure
        leaves earlier periods durable and a re-run resumes where it stopped.
        """
        self.session.commit()
