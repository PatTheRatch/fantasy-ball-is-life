"""Matchups + category results (S1-10a).

The per-period scoreboard fact tables. A matchup's category outcome is a row in
``matchup_category_results`` (ratio categories keep numerator/denominator so
season-to-date aggregation stays correct). ``matchups`` carries the full lineage
(README §Lineage: ``ingestion_run_id`` NOT NULL + ``observed_at`` +
``normalizer_version``) plus self-referential supersession — a resync supersedes,
never deletes (charter §6).

The schema's ``unique (matchup_period_id, home_team_season_id, superseded_at)``
does not enforce the "one live row" intent (Postgres treats NULLs as distinct),
so the live-row invariant is the partial unique index ``uq_matchups_live_slot``.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from backend.models import enums

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    enums.matchup_result.create(bind, checkfirst=False)

    op.create_table(
        "matchups",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("league_season_id", sa.Uuid(), nullable=False),
        sa.Column("matchup_period_id", sa.Uuid(), nullable=False),
        sa.Column("home_team_season_id", sa.Uuid(), nullable=False),
        sa.Column("away_team_season_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status", enums.period_status, server_default=sa.text("'scheduled'"), nullable=False
        ),
        sa.Column("computed_result", enums.matchup_result, nullable=True),
        sa.Column("provider_result", enums.matchup_result, nullable=True),
        sa.Column("result_source", sa.Text(), nullable=True),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("normalizer_version", sa.Text(), nullable=False),
        sa.Column("superseded_by_id", sa.Uuid(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_matchups"),
        sa.ForeignKeyConstraint(
            ["league_season_id"], ["league_seasons.id"],
            name="fk_matchups_league_season_id_league_seasons",
        ),
        sa.ForeignKeyConstraint(
            ["matchup_period_id"], ["matchup_periods.id"],
            name="fk_matchups_matchup_period_id_matchup_periods",
        ),
        sa.ForeignKeyConstraint(
            ["home_team_season_id"], ["fantasy_team_seasons.id"],
            name="fk_matchups_home_team_season_id_fantasy_team_seasons",
        ),
        sa.ForeignKeyConstraint(
            ["away_team_season_id"], ["fantasy_team_seasons.id"],
            name="fk_matchups_away_team_season_id_fantasy_team_seasons",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"], ["ingestion_runs.id"],
            name="fk_matchups_ingestion_run_id_ingestion_runs",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"], ["matchups.id"],
            name="fk_matchups_superseded_by_id_matchups",
        ),
    )
    op.create_index(
        "uq_matchups_live_slot",
        "matchups",
        ["matchup_period_id", "home_team_season_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index(
        "ix_matchups_ls_period_live",
        "matchups",
        ["league_season_id", "matchup_period_id"],
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    op.create_table(
        "matchup_category_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("matchup_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("home_value", sa.Numeric(10, 3), nullable=True),
        sa.Column("away_value", sa.Numeric(10, 3), nullable=True),
        sa.Column("home_numerator", sa.Numeric(10, 2), nullable=True),
        sa.Column("home_denominator", sa.Numeric(10, 2), nullable=True),
        sa.Column("away_numerator", sa.Numeric(10, 2), nullable=True),
        sa.Column("away_denominator", sa.Numeric(10, 2), nullable=True),
        sa.Column("result", enums.matchup_result, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_matchup_category_results"),
        sa.ForeignKeyConstraint(
            ["matchup_id"], ["matchups.id"],
            name="fk_matchup_category_results_matchup_id_matchups",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"],
            name="fk_matchup_category_results_category_id_categories",
        ),
        sa.UniqueConstraint(
            "matchup_id", "category_id",
            name="uq_matchup_category_results_matchup_category",
        ),
    )


def downgrade() -> None:
    op.drop_table("matchup_category_results")
    op.drop_table("matchups")

    bind = op.get_bind()
    enums.matchup_result.drop(bind, checkfirst=False)
