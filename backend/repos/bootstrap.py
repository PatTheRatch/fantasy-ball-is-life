"""Bootstrap repositories: get-or-create for the league write path (D-01).

These are **ingestion-side and cross-tenant by nature** — they create the
``league_season`` that a read-side scope would later be built from. They take a
plain ``Session`` (no ``LeagueSeasonScope``), exactly as ``require_league_member``
does in H-04a: the write path *establishes* tenancy, it does not consume it.
They are deliberately kept out of the read path, which stays scoped.

The repositories are thin on purpose: the natural-key lookup (``find_*``) lives
here, but model construction and the get-or-create orchestration live in
``LeagueBootstrapService`` — the same split as ``MatchupSyncService`` vs
``MatchupRepository``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.fantasy import (
    Category,
    FantasyTeam,
    FantasyTeamSeason,
    League,
    LeagueSeason,
    LeagueSeasonCategory,
    MatchupPeriod,
)
from backend.models.identity import FantasyTeamSeasonManager, Manager
from backend.models.nba import NbaSeason


class NbaSeasonRepository:
    """Look up the ``nba_seasons`` reference table by ``season_year``."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_year(self, season_year: int) -> NbaSeason | None:
        return self.session.scalars(
            select(NbaSeason).where(NbaSeason.season_year == season_year)
        ).one_or_none()


class CategoryRepository:
    """Look up the ``categories`` reference table by key (D11)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_key(self, key: str) -> Category | None:
        return self.session.scalars(
            select(Category).where(Category.key == key)
        ).one_or_none()


class LeagueRepository:
    """``leagues`` — get-or-create the franchise by its derived slug.

    The league has no provider identity (02-fantasy: ``leagues`` deliberately
    carries no provider id); the slug is the closest thing to a natural key. It
    is only ever reached when a season is new, so a hit here means a prior season
    already created the franchise.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_by_slug(self, slug: str) -> League | None:
        return self.session.scalars(select(League).where(League.slug == slug)).one_or_none()

    def add(self, league: League) -> None:
        self.session.add(league)

    def flush(self) -> None:
        """Flush the shared session — parents must land before children.

        The bootstrap models carry bare ``ForeignKey`` columns (no ORM
        ``relationship``), so the unit-of-work cannot infer insert order from
        them; the service flushes each parent explicitly.
        """
        self.session.flush()


class LeagueSeasonRepository:
    """``league_seasons`` — the idempotency anchor (provider identity)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def find_by_provider(
        self, provider_key: str, provider_league_id: str, season_year: int
    ) -> LeagueSeason | None:
        """The existing season for this provider league + season year, if any.

        Backed by ``uq_league_seasons_provider_league_season`` — this is the
        query that makes a re-run over unchanged data a no-op.
        """
        return self.session.scalars(
            select(LeagueSeason).where(
                LeagueSeason.provider_key == provider_key,
                LeagueSeason.provider_league_id == provider_league_id,
                LeagueSeason.season_year == season_year,
            )
        ).one_or_none()

    def add(self, season: LeagueSeason) -> None:
        self.session.add(season)

    def flush(self) -> None:
        self.session.flush()


class LeagueSeasonCategoryRepository:
    """``league_season_categories`` — the season's scoring categories (D11)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, row: LeagueSeasonCategory) -> None:
        self.session.add(row)


class FantasyTeamRepository:
    """``fantasy_teams`` — the franchise (one per team per bootstrap, D-01)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, team: FantasyTeam) -> None:
        self.session.add(team)

    def flush(self) -> None:
        self.session.flush()


class FantasyTeamSeasonRepository:
    """``fantasy_team_seasons`` — the per-season team instance."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, team_season: FantasyTeamSeason) -> None:
        self.session.add(team_season)

    def flush(self) -> None:
        self.session.flush()


class ManagerRepository:
    """``managers`` — created unclaimed (charter D13); no user link here."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, manager: Manager) -> None:
        self.session.add(manager)

    def flush(self) -> None:
        self.session.flush()


class FantasyTeamSeasonManagerRepository:
    """``fantasy_team_season_managers`` — who owned a team in a season (D9)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, row: FantasyTeamSeasonManager) -> None:
        self.session.add(row)


class MatchupPeriodRepository:
    """``matchup_periods`` — written ``scheduled``, never ``final`` (D-02's job)."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, period: MatchupPeriod) -> None:
        self.session.add(period)
