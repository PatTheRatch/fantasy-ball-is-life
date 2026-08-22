"""Lineage columns: ``ingestion_run_id`` on the synced canonical tables.

Charter D17 / 04-provider-ingestion "every canonical fact in 02 and 03 carries
``ingestion_run_id``". Applied to the *synced* tables the pipeline writes —
``league_seasons``, ``fantasy_team_seasons``, ``matchup_periods`` and
``league_season_categories`` — so the provenance of any normalized row is one
join away. Reference/franchise tables (``leagues``, ``fantasy_teams``,
``categories``, ``nba_seasons``) are not "facts" the pipeline authors, so they
deliberately do not get the column.

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

#: table → the FK constraint name the model's naming convention generates for
#: ``ForeignKey("ingestion_runs.id")`` (``fk_<table>_<col>_<referred>``).
_LINEAGE_TABLES = (
    ("league_seasons", "fk_league_seasons_ingestion_run_id_ingestion_runs"),
    ("league_season_categories", "fk_league_season_categories_ingestion_run_id_ingestion_runs"),
    ("fantasy_team_seasons", "fk_fantasy_team_seasons_ingestion_run_id_ingestion_runs"),
    ("matchup_periods", "fk_matchup_periods_ingestion_run_id_ingestion_runs"),
)


def upgrade() -> None:
    for table, constraint in _LINEAGE_TABLES:
        op.add_column(table, sa.Column("ingestion_run_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            constraint, table, "ingestion_runs", ["ingestion_run_id"], ["id"]
        )


def downgrade() -> None:
    for table, constraint in reversed(_LINEAGE_TABLES):
        op.drop_constraint(constraint, table, type_="foreignkey")
        op.drop_column(table, "ingestion_run_id")
