"""Fantasy core models: franchises, seasons, categories, teams, periods.

Schema: ``docs/v2/schema/02-fantasy.md``. Two structural moves the schema makes
real here:

1. **Identity persists; seasons are instances** (charter D8) — ``leagues`` and
   ``fantasy_teams`` are franchises; ``league_seasons`` and
   ``fantasy_team_seasons`` carry the per-season truth (settings, names, provider
   ids).
2. **Matchup periods are rows** (charter D15) — ``matchup_periods`` is a real
   object with dates, a type and a ``status`` whose finality signal drives every
   read path, replacing the hand-typed calendar (non-negotiable).

Each class docstring states its scope + freshness (README §Scope / §Freshness).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import enums
from backend.models.base import (
    CreatedAtMixin,
    LineageMixin,
    ProviderLineageMixin,
    TimestampMixin,
    uuid7,
)
from backend.platform.db import Base

#: Score value precision (10,3) and ratio-component precision (10,2), as floats
#: (``asdecimal=False``) to match the rest of the codebase.
_score_value = Numeric(10, 3, asdecimal=False)
_component_value = Numeric(10, 2, asdecimal=False)


class League(TimestampMixin, Base):
    """A fantasy league franchise. Scope: ``league`` · Freshness: ``reference``.

    Deliberately carries no provider id, season, credentials or visibility —
    all of those are season- or connection-scoped (02-fantasy.md).
    """

    __tablename__ = "leagues"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    accent_color: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (CheckConstraint("slug = lower(slug)", name="slug_lowercase"),)


class LeagueSeason(LineageMixin, TimestampMixin, Base):
    """One league's one season. Scope: ``league_season`` · Freshness: ``synced``
    while active, ``final`` when complete.

    Owns season-specific settings (charter D11), the provider binding, and the
    ``timezone`` that every date boundary resolves through.
    """

    __tablename__ = "league_seasons"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    league_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leagues.id"), nullable=False
    )
    nba_season_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("nba_seasons.id"), nullable=False
    )
    season_year: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(
        enums.league_season_status, nullable=False, server_default=text("'pending'")
    )
    visibility: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'private'")
    )

    provider_key: Mapped[str] = mapped_column(enums.provider_key, nullable=False)
    provider_league_id: Mapped[str] = mapped_column(Text, nullable=False)

    # Settings (charter D11 — season-specific; no separate league_settings table)
    scoring_type: Mapped[str] = mapped_column(Text, nullable=False)
    team_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    roster_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    roster_slots: Mapped[dict[str, int] | None] = mapped_column(JSONB, nullable=True)
    playoff_team_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    regular_season_periods: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acquisition_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uses_faab: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    timezone: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'America/New_York'")
    )

    __table_args__ = (
        UniqueConstraint("league_id", "nba_season_id", name="uq_league_seasons_league_nba_season"),
        UniqueConstraint(
            "provider_key", "provider_league_id", "season_year",
            name="uq_league_seasons_provider_league_season",
        ),
    )


class Category(CreatedAtMixin, Base):
    """A scoring category. Scope: ``global`` · Freshness: ``reference``.

    A lookup table, not an enum (charter D11): the product launches on 9-cat H2H
    but must not hardcode nine categories forever. Ratio categories record their
    components so aggregation stays correct (team FG% = Σfgm/Σfga, never a mean
    of per-player percentages).
    """

    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    short_name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(enums.category_kind, nullable=False)
    higher_is_better: Mapped[bool] = mapped_column(Boolean, nullable=False)
    numerator_stat: Mapped[str | None] = mapped_column(Text, nullable=True)
    denominator_stat: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "kind = 'counting' OR (numerator_stat IS NOT NULL "
            "AND denominator_stat IS NOT NULL)",
            name="ratio_has_components",
        ),
    )


class LeagueSeasonCategory(LineageMixin, CreatedAtMixin, Base):
    """Which categories a season scores, in order. Scope: ``league_season`` ·
    Freshness: ``synced``.

    A 9-cat league has nine rows; a punt-TO league has eight; a points league has
    none. Nothing assumes a count.
    """

    __tablename__ = "league_season_categories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    league_season_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("league_seasons.id"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("categories.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    is_scoring: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )

    __table_args__ = (
        UniqueConstraint(
            "league_season_id", "category_id",
            name="uq_league_season_categories_season_category",
        ),
        UniqueConstraint(
            "league_season_id", "ordinal", name="uq_league_season_categories_season_ordinal"
        ),
    )


class FantasyTeam(CreatedAtMixin, Base):
    """A fantasy team franchise. Scope: ``league`` · Freshness: ``reference``.

    Intentionally near-empty: it exists so a team has continuity across seasons
    even when its name, logo and owner all change (charter D8).
    """

    __tablename__ = "fantasy_teams"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    league_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("leagues.id"), nullable=False
    )


class FantasyTeamSeason(LineageMixin, TimestampMixin, Base):
    """One team's one season. Scope: ``league_season`` · Freshness: ``synced``.

    Carries the name (which changes almost every year), logo and provider id.
    This is the table almost everything else references; team *name* is never a
    join key (02-fantasy.md).
    """

    __tablename__ = "fantasy_team_seasons"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    fantasy_team_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("fantasy_teams.id"), nullable=False
    )
    league_season_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("league_seasons.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    abbreviation: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_team_id: Mapped[str] = mapped_column(Text, nullable=False)
    draft_position: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "league_season_id", "fantasy_team_id",
            name="uq_fantasy_team_seasons_season_team",
        ),
        UniqueConstraint(
            "league_season_id", "provider_team_id",
            name="uq_fantasy_team_seasons_season_provider_team",
        ),
    )


class MatchupPeriod(LineageMixin, TimestampMixin, Base):
    """A matchup period (week). Scope: ``league_season`` · Freshness: ``synced``
    → ``final``.

    A real object with dates, type and ``status`` — imported from the provider,
    never hand-typed (charter D15). ``status = 'final'`` is the finality signal:
    final periods are never refetched and their standings become a deterministic
    fold.
    """

    __tablename__ = "matchup_periods"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    league_season_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("league_seasons.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str] = mapped_column(
        enums.period_type, nullable=False, server_default=text("'regular'")
    )
    status: Mapped[str] = mapped_column(
        enums.period_status, nullable=False, server_default=text("'scheduled'")
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    provider_period_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("league_season_id", "ordinal", name="uq_matchup_periods_season_ordinal"),
        CheckConstraint("end_date >= start_date", name="dates_ordered"),
        Index("matchup_periods_dates_idx", "league_season_id", "start_date", "end_date"),
    )


class Matchup(ProviderLineageMixin, CreatedAtMixin, Base):
    """One matchup in one period. Scope: ``league_season`` · Freshness: ``synced``
    → ``final``.

    ``computed_result`` and ``provider_result`` are stored separately
    (02-fantasy.md: a 4-4 playoff with a tied category read as an undecided tie
    because the code only kept its own tally and never consulted ESPN's
    ``winner``). ``result_source`` records which was used. ``away_team_season_id``
    is null for a bye — never zero-filled (the V1 playoff all-play bug came from
    zero-filling missing matchups).
    """

    __tablename__ = "matchups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    league_season_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("league_seasons.id"), nullable=False
    )
    matchup_period_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("matchup_periods.id"), nullable=False
    )
    home_team_season_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("fantasy_team_seasons.id"), nullable=False
    )
    away_team_season_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("fantasy_team_seasons.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        enums.period_status, nullable=False, server_default=text("'scheduled'")
    )
    computed_result: Mapped[str | None] = mapped_column(enums.matchup_result, nullable=True)
    provider_result: Mapped[str | None] = mapped_column(enums.matchup_result, nullable=True)
    result_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("matchups.id"), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # One live row per (period, home) — the schema's ``unique (..., superseded_at)``
        # does not enforce this (Postgres treats NULLs as distinct), so the live-row
        # invariant is a partial unique index instead.
        Index(
            "uq_matchups_live_slot",
            "matchup_period_id",
            "home_team_season_id",
            unique=True,
            postgresql_where=text("superseded_at IS NULL"),
        ),
        Index(
            "ix_matchups_ls_period_live",
            "league_season_id",
            "matchup_period_id",
            postgresql_where=text("superseded_at IS NULL"),
        ),
    )


class MatchupCategoryResult(Base):
    """One category's outcome within a matchup. Scope: ``league_season`` ·
    Freshness: ``final`` with its matchup.

    Ratio categories keep their components (numerator/denominator) so season-to-
    date aggregation stays correct (team FG% = Σfgm/Σfga, never a mean of
    percentages). Provenance is inherited from the parent ``Matchup``, so this
    table deliberately carries no lineage columns of its own.
    """

    __tablename__ = "matchup_category_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid7)
    matchup_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("matchups.id"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("categories.id"), nullable=False
    )
    home_value: Mapped[float | None] = mapped_column(_score_value, nullable=True)
    away_value: Mapped[float | None] = mapped_column(_score_value, nullable=True)
    home_numerator: Mapped[float | None] = mapped_column(_component_value, nullable=True)
    home_denominator: Mapped[float | None] = mapped_column(_component_value, nullable=True)
    away_numerator: Mapped[float | None] = mapped_column(_component_value, nullable=True)
    away_denominator: Mapped[float | None] = mapped_column(_component_value, nullable=True)
    result: Mapped[str | None] = mapped_column(enums.matchup_result, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "matchup_id", "category_id",
            name="uq_matchup_category_results_matchup_category",
        ),
    )
