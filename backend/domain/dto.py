"""Provider-ingest DTOs: FCP's canonical shapes for provider data.

These are the contract between the provider adapters (``backend/providers``) and
the ingestion pipeline (S1-08): an adapter maps a provider's objects into these
and returns them; nothing provider-specific crosses the boundary (charter §7 —
provider objects never escape the package, never become the domain model).

Pure ``frozen`` dataclasses so they sit in ``backend.domain`` (which imports
nothing — the architecture test enforces it) and are trivially testable. Each
maps 1:1 onto a fantasy-core table from ``02-fantasy.md``:

- ``LeagueSettingsDTO`` → ``league_seasons``
- ``TeamDTO``            → ``fantasy_team_seasons``
- ``MatchupPeriodDTO``   → ``matchup_periods``
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum


class PeriodType(StrEnum):
    """A matchup period's kind. Values mirror the ``period_type`` PG enum."""

    REGULAR = "regular"
    PLAYOFF = "playoff"
    CHAMPIONSHIP = "championship"
    CONSOLATION = "consolation"
    BREAK = "break"


@dataclass(frozen=True, slots=True)
class LeagueSettingsDTO:
    """One league-season's settings (→ ``league_seasons``).

    Fields nullable here are nullable on the table. ``timezone`` defaults to the
    schema default when the provider does not expose one — every date boundary
    resolves through it (02-fantasy.md).
    """

    provider_league_id: str
    season_year: int
    scoring_type: str
    timezone: str
    team_count: int | None = None
    roster_size: int | None = None
    roster_slots: dict[str, int] | None = None
    playoff_team_count: int | None = None
    regular_season_periods: int | None = None
    acquisition_budget: int | None = None
    uses_faab: bool | None = None


@dataclass(frozen=True, slots=True)
class TeamDTO:
    """One team in one season (→ ``fantasy_team_seasons``)."""

    provider_team_id: str
    name: str
    abbreviation: str | None = None
    logo_url: str | None = None
    draft_position: int | None = None


@dataclass(frozen=True, slots=True)
class MatchupPeriodDTO:
    """One matchup period with derived dates (→ ``matchup_periods``).

    ``start_date``/``end_date`` are derived from the provider's pro schedule, so
    they are ``None`` when the period has no games yet (a future period, or one
    whose scoring periods are empty). The ingestion pipeline decides how to
    treat an underivable period — the adapter reports it, never invents dates
    (charter D28; S1-03 "derive dates from the pro schedule, never arithmetic").
    """

    ordinal: int
    type: PeriodType
    provider_period_id: str
    start_date: date | None
    end_date: date | None
    label: str | None = None
