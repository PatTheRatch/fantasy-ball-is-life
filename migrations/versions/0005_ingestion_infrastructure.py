"""Ingestion infrastructure: providers, connections, runs, raw payloads.

04-provider-ingestion.md. Charter §6 ("replay beats patching") and D16 (raw
retention) land here: the pipeline persists raw payloads *before* interpreting
them, and ``ingestion_runs`` records which normalizer version produced the rows
so a mapping bug is fixed by re-running over stored payloads, not refetching.

``provider_key`` was created by ``0003_fantasy_core`` and is reused here
(``create_type=False``), NOT re-created. ``run_status`` is new and created here.
The ``providers`` table is seeded with the eight known providers — reference
data, not V1 migration (charter D25 governs league/user data only).

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from backend.models import enums
from backend.models.base import uuid7

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

#: (key, name, kind) — kind distinguishes fantasy_platform / stats / projections.
_PROVIDERS = (
    ("espn", "ESPN", "fantasy_platform"),
    ("yahoo", "Yahoo", "fantasy_platform"),
    ("sleeper", "Sleeper", "fantasy_platform"),
    ("nba", "NBA", "stats"),
    ("kaggle", "Kaggle", "stats"),
    ("bbm", "Basketball Monster", "projections"),
    ("hashtag", "Hashtag Basketball", "projections"),
    ("manual", "Manual", "manual"),
)


def upgrade() -> None:
    bind = op.get_bind()
    enums.run_status.create(bind, checkfirst=False)

    op.create_table(
        "providers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("key", enums.provider_key, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_providers"),
        sa.UniqueConstraint("key", name="uq_providers_key"),
    )

    op.create_table(
        "provider_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("league_id", sa.Uuid(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("credentials_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("credentials_key_id", sa.Text(), nullable=True),
        sa.Column(
            "status", sa.Text(), server_default=sa.text("'unverified'"), nullable=False
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_connections"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.id"], name="fk_provider_connections_provider_id_providers"
        ),
        sa.ForeignKeyConstraint(
            ["league_id"], ["leagues.id"], name="fk_provider_connections_league_id_leagues"
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name="fk_provider_connections_owner_user_id_users"
        ),
    )

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("connection_id", sa.Uuid(), nullable=True),
        sa.Column("league_season_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("normalizer_version", sa.Text(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status", enums.run_status, server_default=sa.text("'running'"), nullable=False
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stats", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("replayed_from_run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingestion_runs"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.id"], name="fk_ingestion_runs_provider_id_providers"
        ),
        sa.ForeignKeyConstraint(
            ["connection_id"],
            ["provider_connections.id"],
            name="fk_ingestion_runs_connection_id_provider_connections",
        ),
        sa.ForeignKeyConstraint(
            ["league_season_id"],
            ["league_seasons.id"],
            name="fk_ingestion_runs_league_season_id_league_seasons",
        ),
        sa.ForeignKeyConstraint(
            ["replayed_from_run_id"],
            ["ingestion_runs.id"],
            name="fk_ingestion_runs_replayed_from_run_id_ingestion_runs",
        ),
    )
    op.create_index(
        "ingestion_runs_league_kind_idx",
        "ingestion_runs",
        ["league_season_id", "kind", sa.text("started_at DESC")],
    )

    op.create_table(
        "raw_payloads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column(
            "request_params", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("storage_ref", sa.Text(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_raw_payloads"),
        sa.CheckConstraint(
            "payload IS NOT NULL OR storage_ref IS NOT NULL",
            name="ck_raw_payloads_payload_or_storage",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_raw_payloads_ingestion_run_id_ingestion_runs",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.id"], name="fk_raw_payloads_provider_id_providers"
        ),
    )
    op.create_index("raw_payloads_run_idx", "raw_payloads", ["ingestion_run_id"])
    op.create_index(
        "raw_payloads_hash_idx", "raw_payloads", ["provider_id", "endpoint", "content_hash"]
    )

    providers = sa.table(
        "providers",
        sa.column("id", sa.Uuid()),
        sa.column("key", enums.provider_key),
        sa.column("name", sa.Text()),
        sa.column("kind", sa.Text()),
    )
    op.bulk_insert(
        providers,
        [{"id": uuid7(), "key": key, "name": name, "kind": kind} for key, name, kind in _PROVIDERS],
    )


def downgrade() -> None:
    op.drop_table("raw_payloads")
    op.drop_table("ingestion_runs")
    op.drop_table("provider_connections")
    op.drop_table("providers")

    bind = op.get_bind()
    enums.run_status.drop(bind, checkfirst=False)
