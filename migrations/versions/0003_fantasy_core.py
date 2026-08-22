"""fantasy core schema: leagues, seasons, categories, teams, periods.

One concern: the fantasy foundation tables (``02-fantasy.md``) plus the two
out-of-domain enablers their foreign keys require — the minimal ``nba_seasons``
table (``03-nba``) and the ``provider_key`` enum (``04``) — and
``fantasy_team_season_managers`` (``01-identity``), which was deferred from
S1-05 only because ``fantasy_team_seasons`` did not yet exist.

Enum types are created explicitly here (never autocreated by the ORM — every
model/enum uses ``create_type=False``). A future ``04`` migration that builds
``providers``/``ingestion_runs`` must reuse ``provider_key`` with
``create_type=False`` and must NOT re-``CREATE TYPE`` it.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from backend.models import enums

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

#: Order matters: types must exist before tables reference them (upgrade) and be
#: dropped only after the referencing tables are gone (downgrade).
ENUM_TYPES = (
    enums.provider_key,
    enums.league_season_status,
    enums.category_kind,
    enums.period_type,
    enums.period_status,
    enums.manager_role,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "nba_seasons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("season_year", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("all_star_break_start", sa.Date(), nullable=True),
        sa.Column("all_star_break_end", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_nba_seasons"),
        sa.UniqueConstraint("season_year", name="uq_nba_seasons_season_year"),
    )

    op.create_table(
        "leagues",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("accent_color", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_leagues"),
        sa.UniqueConstraint("slug", name="uq_leagues_slug"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], name="fk_leagues_created_by_user_id_users"
        ),
        sa.CheckConstraint("slug = lower(slug)", name="ck_leagues_slug_lowercase"),
    )

    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("short_name", sa.Text(), nullable=False),
        sa.Column("kind", enums.category_kind, nullable=False),
        sa.Column("higher_is_better", sa.Boolean(), nullable=False),
        sa.Column("numerator_stat", sa.Text(), nullable=True),
        sa.Column("denominator_stat", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_categories"),
        sa.UniqueConstraint("key", name="uq_categories_key"),
        sa.CheckConstraint(
            "kind = 'counting' OR (numerator_stat IS NOT NULL AND denominator_stat IS NOT NULL)",
            name="ck_categories_ratio_has_components",
        ),
    )

    op.create_table(
        "fantasy_teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("league_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fantasy_teams"),
        sa.ForeignKeyConstraint(
            ["league_id"], ["leagues.id"], name="fk_fantasy_teams_league_id_leagues"
        ),
    )

    op.create_table(
        "league_seasons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("league_id", sa.Uuid(), nullable=False),
        sa.Column("nba_season_id", sa.Uuid(), nullable=False),
        sa.Column("season_year", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            enums.league_season_status,
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "visibility", sa.Text(), server_default=sa.text("'private'"), nullable=False
        ),
        sa.Column("provider_key", enums.provider_key, nullable=False),
        sa.Column("provider_league_id", sa.Text(), nullable=False),
        sa.Column("scoring_type", sa.Text(), nullable=False),
        sa.Column("team_count", sa.Integer(), nullable=True),
        sa.Column("roster_size", sa.Integer(), nullable=True),
        sa.Column("roster_slots", postgresql.JSONB(), nullable=True),
        sa.Column("playoff_team_count", sa.Integer(), nullable=True),
        sa.Column("regular_season_periods", sa.Integer(), nullable=True),
        sa.Column("acquisition_budget", sa.Integer(), nullable=True),
        sa.Column("uses_faab", sa.Boolean(), nullable=True),
        sa.Column(
            "timezone", sa.Text(), server_default=sa.text("'America/New_York'"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_league_seasons"),
        sa.UniqueConstraint(
            "league_id", "nba_season_id", name="uq_league_seasons_league_nba_season"
        ),
        sa.UniqueConstraint(
            "provider_key",
            "provider_league_id",
            "season_year",
            name="uq_league_seasons_provider_league_season",
        ),
        sa.ForeignKeyConstraint(
            ["league_id"], ["leagues.id"], name="fk_league_seasons_league_id_leagues"
        ),
        sa.ForeignKeyConstraint(
            ["nba_season_id"],
            ["nba_seasons.id"],
            name="fk_league_seasons_nba_season_id_nba_seasons",
        ),
    )

    op.create_table(
        "league_season_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("league_season_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("is_scoring", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_league_season_categories"),
        sa.UniqueConstraint(
            "league_season_id", "category_id",
            name="uq_league_season_categories_season_category",
        ),
        sa.UniqueConstraint(
            "league_season_id", "ordinal", name="uq_league_season_categories_season_ordinal"
        ),
        sa.ForeignKeyConstraint(
            ["league_season_id"],
            ["league_seasons.id"],
            name="fk_league_season_categories_league_season_id_league_seasons",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name="fk_league_season_categories_category_id_categories",
        ),
    )

    op.create_table(
        "fantasy_team_seasons",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fantasy_team_id", sa.Uuid(), nullable=False),
        sa.Column("league_season_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("abbreviation", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.Text(), nullable=True),
        sa.Column("provider_team_id", sa.Text(), nullable=False),
        sa.Column("draft_position", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fantasy_team_seasons"),
        sa.UniqueConstraint(
            "league_season_id", "fantasy_team_id", name="uq_fantasy_team_seasons_season_team"
        ),
        sa.UniqueConstraint(
            "league_season_id",
            "provider_team_id",
            name="uq_fantasy_team_seasons_season_provider_team",
        ),
        sa.ForeignKeyConstraint(
            ["fantasy_team_id"],
            ["fantasy_teams.id"],
            name="fk_fantasy_team_seasons_fantasy_team_id_fantasy_teams",
        ),
        sa.ForeignKeyConstraint(
            ["league_season_id"],
            ["league_seasons.id"],
            name="fk_fantasy_team_seasons_league_season_id_league_seasons",
        ),
    )

    op.create_table(
        "matchup_periods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("league_season_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column(
            "type", enums.period_type, server_default=sa.text("'regular'"), nullable=False
        ),
        sa.Column(
            "status", enums.period_status, server_default=sa.text("'scheduled'"), nullable=False
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("provider_period_id", sa.Text(), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_matchup_periods"),
        sa.UniqueConstraint(
            "league_season_id", "ordinal", name="uq_matchup_periods_season_ordinal"
        ),
        sa.CheckConstraint("end_date >= start_date", name="ck_matchup_periods_dates_ordered"),
        sa.ForeignKeyConstraint(
            ["league_season_id"],
            ["league_seasons.id"],
            name="fk_matchup_periods_league_season_id_league_seasons",
        ),
    )
    op.create_index(
        "matchup_periods_dates_idx",
        "matchup_periods",
        ["league_season_id", "start_date", "end_date"],
    )

    op.create_table(
        "fantasy_team_season_managers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fantasy_team_season_id", sa.Uuid(), nullable=False),
        sa.Column("manager_id", sa.Uuid(), nullable=False),
        sa.Column("role", enums.manager_role, server_default=sa.text("'owner'"), nullable=False),
        sa.Column("from_date", sa.Date(), nullable=True),
        sa.Column("to_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_fantasy_team_season_managers"),
        sa.UniqueConstraint(
            "fantasy_team_season_id",
            "manager_id",
            "from_date",
            name="uq_fantasy_team_season_managers_season_manager_from",
        ),
        sa.ForeignKeyConstraint(
            ["fantasy_team_season_id"],
            ["fantasy_team_seasons.id"],
            name="fk_fantasy_team_season_managers_fantasy_team_season_id",
        ),
        sa.ForeignKeyConstraint(
            ["manager_id"],
            ["managers.id"],
            name="fk_fantasy_team_season_managers_manager_id_managers",
        ),
    )
    op.create_index("ftsm_manager_idx", "fantasy_team_season_managers", ["manager_id"])
    op.create_index(
        "ftsm_team_season_idx", "fantasy_team_season_managers", ["fantasy_team_season_id"]
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order.
    op.drop_table("fantasy_team_season_managers")
    op.drop_table("matchup_periods")
    op.drop_table("fantasy_team_seasons")
    op.drop_table("league_season_categories")
    op.drop_table("league_seasons")
    op.drop_table("fantasy_teams")
    op.drop_table("categories")
    op.drop_table("leagues")
    op.drop_table("nba_seasons")

    # Drop enum types only after the tables that reference them are gone.
    bind = op.get_bind()
    for enum_type in reversed(ENUM_TYPES):
        enum_type.drop(bind, checkfirst=False)
