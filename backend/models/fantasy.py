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
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models import enums
from backend.models.base import CreatedAtMixin, TimestampMixin, uuid7
from backend.platform.db import Base


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


class LeagueSeason(TimestampMixin, Base):
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


class LeagueSeasonCategory(CreatedAtMixin, Base):
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


class FantasyTeamSeason(TimestampMixin, Base):
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


class MatchupPeriod(TimestampMixin, Base):
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
