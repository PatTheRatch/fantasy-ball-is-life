"""D-01 league bootstrap: the write path, exercised against Postgres.

These run only when ``TEST_DATABASE_URL`` is set (the ``db_session`` fixture).
The adapter is faked — no live ESPN — so the bootstrap's persistence is what is
under test: the full membership chain is created, re-running is a no-op, and the
finality / D11 / unclaimed rules hold.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from backend.domain.dto import (
    LeagueSettingsDTO,
    MatchupPeriodDTO,
    PeriodType,
    TeamDTO,
    TeamOwnerDTO,
)
from backend.models.fantasy import (
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
from backend.models.ingestion import IngestionRun
from backend.models.nba import NbaSeason
from backend.repos.bootstrap import (
    CategoryRepository,
    FantasyTeamRepository,
    FantasyTeamSeasonManagerRepository,
    FantasyTeamSeasonRepository,
    LeagueRepository,
    LeagueSeasonCategoryRepository,
    LeagueSeasonRepository,
    ManagerRepository,
    MatchupPeriodRepository,
    NbaSeasonRepository,
)
from backend.repos.ingestion import (
    IngestionRunRepository,
    ProviderRepository,
    RawPayloadRepository,
)
from backend.repos.membership import LeagueMembershipRepository
from backend.services.ingestion import IngestionService
from backend.services.league_bootstrap import LeagueBootstrapService

SEASON_YEAR = 2026
PROVIDER_LEAGUE_ID = "3853870"
CATEGORIES = ("PTS", "REB", "AST", "STL", "BLK", "TPM", "TO", "FG_PCT", "FT_PCT")


def _clean(db_session: Session) -> None:
    for table in (
        "fantasy_team_season_managers",
        "fantasy_team_seasons",
        "fantasy_teams",
        "matchup_periods",
        "league_season_categories",
        "league_seasons",
        "leagues",
        "nba_seasons",
        "ingestion_runs",
        "raw_payloads",
        "manager_user_links",
        "managers",
        "users",
    ):
        db_session.execute(text(f'TRUNCATE "{table}" CASCADE'))
    db_session.commit()


def _seed_nba_season(db_session: Session, season_year: int = SEASON_YEAR) -> None:
    db_session.add(
        NbaSeason(
            season_year=season_year,
            label=str(season_year),
            start_date=date(2025, 10, 1),
            end_date=date(2026, 6, 1),
        )
    )
    db_session.commit()


def _service(db_session: Session, adapter: object) -> LeagueBootstrapService:
    return LeagueBootstrapService(
        IngestionService(
            ProviderRepository(db_session),
            IngestionRunRepository(db_session),
            RawPayloadRepository(db_session),
        ),
        adapter,
        LeagueRepository(db_session),
        LeagueSeasonRepository(db_session),
        NbaSeasonRepository(db_session),
        CategoryRepository(db_session),
        LeagueSeasonCategoryRepository(db_session),
        FantasyTeamRepository(db_session),
        FantasyTeamSeasonRepository(db_session),
        ManagerRepository(db_session),
        FantasyTeamSeasonManagerRepository(db_session),
        MatchupPeriodRepository(db_session),
    )


class _FakeAdapter:
    def __init__(self, settings, teams, periods, *, fail: bool = False) -> None:
        self.settings = settings
        self.teams = teams
        self.periods = periods
        self.fail = fail

    def fetch_settings(self, connection, season_year):
        if self.fail:
            raise RuntimeError("adapter boom")
        return self.settings

    def fetch_teams(self, connection, season_year):
        return self.teams

    def fetch_periods(self, connection, season_year):
        return self.periods


def _settings(**overrides) -> LeagueSettingsDTO:
    fields = dict(
        provider_league_id=PROVIDER_LEAGUE_ID,
        name="Patriot Games",
        season_year=SEASON_YEAR,
        scoring_type="H2H_CAT",
        timezone="America/New_York",
        team_count=12,
        categories=CATEGORIES,
    )
    fields.update(overrides)
    return LeagueSettingsDTO(**fields)


def _teams() -> list[TeamDTO]:
    return [
        TeamDTO(
            provider_team_id="1",
            name="Ballers",
            owners=(TeamOwnerDTO("{GUID-1}", "Patrick Owner"),),
        ),
        TeamDTO(
            provider_team_id="2",
            name="Scorers",
            owners=(
                TeamOwnerDTO("{GUID-2}", "Mike Owner"),
                TeamOwnerDTO("{GUID-3}", "Co Manager"),
            ),
        ),
    ]


def _periods() -> list[MatchupPeriodDTO]:
    return [
        MatchupPeriodDTO(
            ordinal=1, type=PeriodType.REGULAR, provider_period_id="1",
            start_date=date(2025, 10, 21), end_date=date(2025, 10, 27),
        ),
        MatchupPeriodDTO(
            ordinal=2, type=PeriodType.REGULAR, provider_period_id="2",
            start_date=date(2025, 10, 28), end_date=date(2025, 11, 3),
        ),
        # A future period with no games yet → null dates → skipped, never invented.
        MatchupPeriodDTO(
            ordinal=3, type=PeriodType.REGULAR, provider_period_id="3",
            start_date=None, end_date=None,
        ),
    ]


def _count(db_session: Session, model: type) -> int:
    return db_session.scalar(select(func.count()).select_from(model)) or 0


def _table_counts(db_session: Session) -> tuple[int, ...]:
    models = (League, LeagueSeason, LeagueSeasonCategory, FantasyTeam,
              FantasyTeamSeason, Manager, FantasyTeamSeasonManager, MatchupPeriod)
    return tuple(_count(db_session, m) for m in models)


# --- the happy path ----------------------------------------------------------


def test_bootstrap_creates_the_full_chain(db_session: Session) -> None:
    _clean(db_session)
    _seed_nba_season(db_session)
    adapter = _FakeAdapter(_settings(), _teams(), _periods())
    service = _service(db_session, adapter)

    summary = service.bootstrap(object(), PROVIDER_LEAGUE_ID, SEASON_YEAR)

    assert summary.season_created is True
    assert summary.league_created is True
    assert summary.teams_created == 2
    assert summary.periods_created == 2
    assert summary.periods_skipped == 1
    assert summary.managers_created == 3  # owner + owner + co_manager
    assert summary.categories_created == 9

    assert _count(db_session, League) == 1
    assert _count(db_session, LeagueSeason) == 1
    assert _count(db_session, LeagueSeasonCategory) == 9
    assert _count(db_session, FantasyTeam) == 2
    assert _count(db_session, FantasyTeamSeason) == 2
    assert _count(db_session, Manager) == 3
    assert _count(db_session, FantasyTeamSeasonManager) == 3
    assert _count(db_session, MatchupPeriod) == 2  # the null-date period skipped


def test_re_running_creates_zero_new_rows(db_session: Session) -> None:
    _clean(db_session)
    _seed_nba_season(db_session)
    adapter = _FakeAdapter(_settings(), _teams(), _periods())
    service = _service(db_session, adapter)

    service.bootstrap(object(), PROVIDER_LEAGUE_ID, SEASON_YEAR)
    before = _table_counts(db_session)

    second = service.bootstrap(object(), PROVIDER_LEAGUE_ID, SEASON_YEAR)
    after = _table_counts(db_session)

    assert second.season_created is False
    assert second.teams_created == 0
    assert before == after


# --- the rules that are not obvious -----------------------------------------


def test_no_period_is_written_final(db_session: Session) -> None:
    _clean(db_session)
    _seed_nba_season(db_session)
    service = _service(db_session, _FakeAdapter(_settings(), _teams(), _periods()))
    service.bootstrap(object(), PROVIDER_LEAGUE_ID, SEASON_YEAR)

    statuses = set(db_session.scalars(select(MatchupPeriod.status)))
    assert statuses == {"scheduled"}


def test_unmapped_category_finishes_partial(db_session: Session) -> None:
    _clean(db_session)
    _seed_nba_season(db_session)
    adapter = _FakeAdapter(
        _settings(categories=CATEGORIES + ("NOT_A_CATEGORY",)), _teams(), _periods()
    )
    service = _service(db_session, adapter)

    summary = service.bootstrap(object(), PROVIDER_LEAGUE_ID, SEASON_YEAR)

    assert summary.unmapped_categories == ("NOT_A_CATEGORY",)
    assert summary.categories_created == 9  # the nine mapped ones, not ten
    run = db_session.scalars(select(IngestionRun)).one()
    assert run.status == "partial"


def test_co_managed_team_gets_owner_and_co_manager(db_session: Session) -> None:
    _clean(db_session)
    _seed_nba_season(db_session)
    service = _service(db_session, _FakeAdapter(_settings(), _teams(), _periods()))
    service.bootstrap(object(), PROVIDER_LEAGUE_ID, SEASON_YEAR)

    scorers = db_session.scalars(
        select(FantasyTeamSeason).where(FantasyTeamSeason.provider_team_id == "2")
    ).one()
    roles = set(
        db_session.scalars(
            select(FantasyTeamSeasonManager.role).where(
                FantasyTeamSeasonManager.fantasy_team_season_id == scorers.id
            )
        )
    )
    assert roles == {"owner", "co_manager"}


def test_managers_created_unclaimed(db_session: Session) -> None:
    _clean(db_session)
    _seed_nba_season(db_session)
    service = _service(db_session, _FakeAdapter(_settings(), _teams(), _periods()))
    service.bootstrap(object(), PROVIDER_LEAGUE_ID, SEASON_YEAR)

    assert _count(db_session, Manager) == 3
    assert _count(db_session, ManagerUserLink) == 0  # claiming is D-03


def test_same_owner_id_is_one_manager(db_session: Session) -> None:
    _clean(db_session)
    _seed_nba_season(db_session)
    shared = TeamOwnerDTO("{GUID-SHARED}", "Shared Owner")
    teams = [
        TeamDTO(provider_team_id="1", name="A", owners=(shared,)),
        TeamDTO(provider_team_id="2", name="B", owners=(shared,)),
    ]
    service = _service(db_session, _FakeAdapter(_settings(), teams, _periods()))
    summary = service.bootstrap(object(), PROVIDER_LEAGUE_ID, SEASON_YEAR)

    assert summary.managers_created == 1
    assert _count(db_session, Manager) == 1
    assert _count(db_session, FantasyTeamSeasonManager) == 2


# --- the one that proves the point ------------------------------------------


def test_linked_user_passes_is_member_and_unlinked_does_not(db_session: Session) -> None:
    _clean(db_session)
    _seed_nba_season(db_session)
    service = _service(db_session, _FakeAdapter(_settings(), _teams(), _periods()))
    service.bootstrap(object(), PROVIDER_LEAGUE_ID, SEASON_YEAR)

    season_id = db_session.scalar(select(LeagueSeason.id))
    manager = db_session.scalars(select(Manager)).first()
    assert manager is not None

    member = User(
        auth_subject="auth-member", email="member@example.com", display_name="Member"
    )
    outsider = User(
        auth_subject="auth-outsider", email="outsider@example.com", display_name="Outsider"
    )
    db_session.add_all([member, outsider])
    db_session.flush()
    db_session.add(ManagerUserLink(manager_id=manager.id, user_id=member.id, is_primary=True))
    db_session.commit()

    membership = LeagueMembershipRepository(db_session)
    assert membership.is_member(season_id, member.id) is True
    assert membership.is_member(season_id, outsider.id) is False


# --- the run lifecycle (H-03's guarantee, exercised here) --------------------


def test_adapter_failure_leaves_run_failed(db_session: Session) -> None:
    _clean(db_session)
    _seed_nba_season(db_session)
    service = _service(
        db_session, _FakeAdapter(_settings(), _teams(), _periods(), fail=True)
    )

    with pytest.raises(RuntimeError):
        service.bootstrap(object(), PROVIDER_LEAGUE_ID, SEASON_YEAR)

    run = db_session.scalars(select(IngestionRun)).one()
    assert run.status == "failed"
    assert _count(db_session, League) == 0  # the half-written work rolled back
