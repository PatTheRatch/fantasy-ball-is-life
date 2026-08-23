"""League bootstrap: fetch + persist one league's full season (D-01).

The first write path. Joins the S1-07 adapter (settings/teams/periods) to the
S1-06 schema: fetches an ESPN league and creates the ``league``, ``league_season``,
``league_season_categories``, ``fantasy_teams``, ``fantasy_team_seasons``,
``managers``, ``fantasy_team_season_managers`` and ``matchup_periods`` rows.

The whole operation runs inside :meth:`IngestionService.run_scope` (H-03) so the
raw payloads are recorded before interpretation, the canonical rows carry
``ingestion_run_id`` lineage, and the run is guaranteed a terminal status.

Four rules, none obvious:

- **Idempotent by natural key.** The ``league_seasons`` provider-identity unique
  constraint is the anchor: a re-run over unchanged data finds the existing
  season and creates zero new rows.
- **The membership chain is the trap.** ``require_league_member`` gates every
  league route through ``users → manager_user_links → managers →
  fantasy_team_season_managers → fantasy_team_seasons``. Without manager rows the
  bootstrap looks done and every league route 403s — so this creates the manager
  side too. Managers are created **unclaimed** (no ``manager_user_links``);
  claiming is D-03.
- **No period is written ``final``.** Finality is D-02's job; periods land as
  ``scheduled``. Periods whose dates cannot be derived are skipped and counted,
  never invented (the DTO contract).
- **D11 — the count is whatever the season declares.** ``NINE_CAT`` is a
  test/seed convenience, never a runtime default. An unmapped category key is a
  real condition: the run finishes ``partial`` rather than silently dropping it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Protocol

from backend.domain.dto import LeagueSettingsDTO, MatchupPeriodDTO, TeamDTO
from backend.models.base import uuid7
from backend.models.fantasy import (
    FantasyTeam,
    FantasyTeamSeason,
    League,
    LeagueSeason,
    LeagueSeasonCategory,
    MatchupPeriod,
)
from backend.models.identity import FantasyTeamSeasonManager, Manager
from backend.models.ingestion import IngestionRun
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
from backend.services.ingestion import (
    RUN_PARTIAL,
    RUN_SUCCEEDED,
    IngestionService,
)

_SLUG_SEP = re.compile(r"[^a-z0-9]+")

PROVIDER_KEY = "espn"


def slugify(name: str) -> str:
    """Derive a lowercase URL slug from a league name.

    ``leagues.slug`` has ``slug = lower(slug)``, so the provider's casing must
    never reach it. Non-alphanumerics collapse to a single hyphen; an empty
    result falls back to ``"league"`` so NOT NULL is always satisfied.
    """
    return _SLUG_SEP.sub("-", name.lower()).strip("-") or "league"


class BootstrapError(Exception):
    """The bootstrap could not run (missing NBA season, no scoring type)."""


class LeagueBootstrapAdapter(Protocol):
    """The adapter seam the bootstrap depends on (satisfied by ``ESPNAdapter``)."""

    def fetch_settings(self, connection: object, season_year: int) -> LeagueSettingsDTO: ...
    def fetch_teams(self, connection: object, season_year: int) -> list[TeamDTO]: ...
    def fetch_periods(self, connection: object, season_year: int) -> list[MatchupPeriodDTO]: ...


@dataclass(frozen=True, slots=True)
class BootstrapSummary:
    """What one bootstrap did."""

    league_created: bool
    season_created: bool
    teams_created: int
    periods_created: int
    periods_skipped: int
    managers_created: int
    categories_created: int
    unmapped_categories: tuple[str, ...] = ()


def _period_payload(p: MatchupPeriodDTO) -> dict[str, object]:
    """A JSON-safe dict for the raw-payload ledger (date/enum → JSON types)."""
    return {
        "ordinal": p.ordinal,
        "type": p.type.value,
        "provider_period_id": p.provider_period_id,
        "start_date": p.start_date.isoformat() if p.start_date else None,
        "end_date": p.end_date.isoformat() if p.end_date else None,
        "label": p.label,
    }


class LeagueBootstrapService:
    """Fetches + persists one league's full season (the D-01 write path)."""

    def __init__(
        self,
        ingestion: IngestionService,
        adapter: LeagueBootstrapAdapter,
        leagues: LeagueRepository,
        league_seasons: LeagueSeasonRepository,
        nba_seasons: NbaSeasonRepository,
        categories: CategoryRepository,
        league_season_categories: LeagueSeasonCategoryRepository,
        fantasy_teams: FantasyTeamRepository,
        fantasy_team_seasons: FantasyTeamSeasonRepository,
        managers: ManagerRepository,
        team_season_managers: FantasyTeamSeasonManagerRepository,
        periods: MatchupPeriodRepository,
    ) -> None:
        self.ingestion = ingestion
        self.adapter = adapter
        self.leagues = leagues
        self.league_seasons = league_seasons
        self.nba_seasons = nba_seasons
        self.categories = categories
        self.league_season_categories = league_season_categories
        self.fantasy_teams = fantasy_teams
        self.fantasy_team_seasons = fantasy_team_seasons
        self.managers = managers
        self.team_season_managers = team_season_managers
        self.periods = periods

    def bootstrap(self, connection: object, season_year: int) -> BootstrapSummary:
        """Fetch + persist the league. Idempotent on re-run (zero new rows).

        The provider league id is taken from ``settings.provider_league_id`` (what
        the adapter actually reported and what the raw-payload ledger records) —
        a single source of truth, so the idempotency anchor and the persisted
        column cannot drift from the payload.
        """
        with self.ingestion.run_scope(PROVIDER_KEY, kind="league_bootstrap") as run:
            settings = self.adapter.fetch_settings(connection, season_year)
            teams = self.adapter.fetch_teams(connection, season_year)
            periods = self.adapter.fetch_periods(connection, season_year)
            self._record_payloads(run, settings, teams, periods)

            summary = self._persist(run, settings, teams, periods)

            status = RUN_PARTIAL if summary.unmapped_categories else RUN_SUCCEEDED
            stats = asdict(summary)
            stats["unmapped_categories"] = list(summary.unmapped_categories)
            self.ingestion.finish_run(run, status, stats=stats)
            return summary

    def _record_payloads(
        self,
        run: IngestionRun,
        settings: LeagueSettingsDTO,
        teams: list[TeamDTO],
        periods: list[MatchupPeriodDTO],
    ) -> None:
        self.ingestion.record_payload(run, "settings", asdict(settings))
        self.ingestion.record_payload(run, "teams", {"teams": [asdict(t) for t in teams]})
        self.ingestion.record_payload(
            run, "periods", {"periods": [_period_payload(p) for p in periods]}
        )

    def _persist(
        self,
        run: IngestionRun,
        settings: LeagueSettingsDTO,
        teams: Sequence[TeamDTO],
        periods: Sequence[MatchupPeriodDTO],
    ) -> BootstrapSummary:
        if settings.scoring_type is None:
            raise BootstrapError("league has no scoring_type; cannot persist a season")

        nba_season = self.nba_seasons.get_by_year(settings.season_year)
        if nba_season is None:
            raise BootstrapError(f"no nba_seasons row for season_year {settings.season_year}")

        season = self.league_seasons.find_by_provider(
            PROVIDER_KEY, settings.provider_league_id, settings.season_year
        )
        if season is not None:
            # Idempotent: a prior run created everything in one transaction.
            return BootstrapSummary(
                league_created=False,
                season_created=False,
                teams_created=0,
                periods_created=0,
                periods_skipped=0,
                managers_created=0,
                categories_created=0,
            )

        category_by_key = {
            key: self.categories.get_by_key(key) for key in settings.categories
        }
        unmapped = tuple(
            key for key in settings.categories if category_by_key[key] is None
        )

        league = self.leagues.find_by_slug(slugify(settings.name))
        league_created = league is None
        if league is None:
            league = League(id=uuid7(), slug=slugify(settings.name), name=settings.name)
            self.leagues.add(league)
            self.leagues.flush()

        season = LeagueSeason(
            id=uuid7(),
            league_id=league.id,
            nba_season_id=nba_season.id,
            season_year=settings.season_year,
            provider_key=PROVIDER_KEY,
            provider_league_id=settings.provider_league_id,
            scoring_type=settings.scoring_type,
            team_count=settings.team_count,
            roster_size=settings.roster_size,
            roster_slots=settings.roster_slots,
            playoff_team_count=settings.playoff_team_count,
            regular_season_periods=settings.regular_season_periods,
            acquisition_budget=settings.acquisition_budget,
            uses_faab=settings.uses_faab,
            timezone=settings.timezone,
            ingestion_run_id=run.id,
        )
        self.league_seasons.add(season)
        self.league_seasons.flush()

        categories_created = 0
        for ordinal, key in enumerate(settings.categories):
            category = category_by_key.get(key)
            if category is None:
                continue  # unmapped — recorded, the run finishes partial
            self.league_season_categories.add(
                LeagueSeasonCategory(
                    league_season_id=season.id,
                    category_id=category.id,
                    ordinal=ordinal,
                    is_scoring=True,
                    ingestion_run_id=run.id,
                )
            )
            categories_created += 1

        managers_created = 0
        owner_manager: dict[str, Manager] = {}
        for team_dto in teams:
            team = FantasyTeam(id=uuid7(), league_id=league.id)
            self.fantasy_teams.add(team)
            self.fantasy_teams.flush()
            team_season = FantasyTeamSeason(
                id=uuid7(),
                fantasy_team_id=team.id,
                league_season_id=season.id,
                name=team_dto.name,
                abbreviation=team_dto.abbreviation,
                logo_url=team_dto.logo_url,
                provider_team_id=team_dto.provider_team_id,
                draft_position=team_dto.draft_position,
                ingestion_run_id=run.id,
            )
            self.fantasy_team_seasons.add(team_season)
            self.fantasy_team_seasons.flush()
            for index, owner in enumerate(team_dto.owners):
                manager = owner_manager.get(owner.provider_owner_id)
                if manager is None:
                    # Unclaimed: a manager is an identity, not a user link (D13).
                    manager = Manager(id=uuid7(), display_name=owner.display_name)
                    self.managers.add(manager)
                    self.managers.flush()
                    owner_manager[owner.provider_owner_id] = manager
                    managers_created += 1
                self.team_season_managers.add(
                    FantasyTeamSeasonManager(
                        fantasy_team_season_id=team_season.id,
                        manager_id=manager.id,
                        role="owner" if index == 0 else "co_manager",
                    )
                )

        periods_created = 0
        periods_skipped = 0
        for period in periods:
            if period.start_date is None or period.end_date is None:
                # Underivable dates are skipped, never invented (DTO contract).
                periods_skipped += 1
                continue
            self.periods.add(
                MatchupPeriod(
                    league_season_id=season.id,
                    ordinal=period.ordinal,
                    type=period.type.value,
                    status="scheduled",
                    start_date=period.start_date,
                    end_date=period.end_date,
                    provider_period_id=period.provider_period_id,
                    label=period.label,
                    ingestion_run_id=run.id,
                )
            )
            periods_created += 1

        return BootstrapSummary(
            league_created=league_created,
            season_created=True,
            teams_created=len(teams),
            periods_created=periods_created,
            periods_skipped=periods_skipped,
            managers_created=managers_created,
            categories_created=categories_created,
            unmapped_categories=unmapped,
        )
