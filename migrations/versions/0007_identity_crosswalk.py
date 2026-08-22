"""Identity crosswalk: players + provider identities, links, review queue.

03-nba (``players``) and 04-provider-ingestion (the crosswalk). Charter D18
(ambiguous matches are flagged, never silently fuzzy-matched) and D19 (durable,
permanent crosswalk). ``players`` deliberately has no external-id columns — the
crosswalk is ``provider_identities`` → ``identity_links``, and a record that
cannot be confidently resolved is a ``identity_review_queue`` row (counted, never
dropped). A wrong link is superseded, never deleted.

Creates three new enum types (``provider_entity_kind``, ``match_method``,
``review_status``). ``match_method`` values mirror ``backend.domain.names.MatchMethod``.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from backend.models import enums

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

ENUM_TYPES = (
    enums.provider_entity_kind,
    enums.match_method,
    enums.review_status,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.create(bind, checkfirst=False)

    op.create_table(
        "players",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("birthdate", sa.Date(), nullable=True),
        sa.Column("height_inches", sa.Integer(), nullable=True),
        sa.Column("weight_lbs", sa.Integer(), nullable=True),
        sa.Column("primary_position", sa.Text(), nullable=True),
        sa.Column("debut_season_year", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_players"),
    )
    op.create_index("players_last_name_idx", "players", [sa.text("lower(last_name)")])

    op.create_table(
        "provider_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_id", sa.Uuid(), nullable=False),
        sa.Column("entity_kind", enums.provider_entity_kind, nullable=False),
        sa.Column("provider_entity_id", sa.Text(), nullable=True),
        sa.Column("raw_name", sa.Text(), nullable=True),
        sa.Column(
            "raw_attributes", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_identities"),
        sa.UniqueConstraint(
            "provider_id", "entity_kind", "provider_entity_id",
            name="uq_provider_identities_provider_entity",
        ),
        sa.CheckConstraint(
            "provider_entity_id IS NOT NULL OR raw_name IS NOT NULL",
            name="ck_provider_identities_id_or_name",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["providers.id"], name="fk_provider_identities_provider_id_providers"
        ),
    )

    op.create_table(
        "identity_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_identity_id", sa.Uuid(), nullable=False),
        sa.Column("fcp_entity_kind", enums.provider_entity_kind, nullable=False),
        sa.Column("fcp_entity_id", sa.Uuid(), nullable=False),
        sa.Column("match_method", enums.match_method, nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False),
        sa.Column("evidence", postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("verified_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_id", sa.Uuid(), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_identity_links"),
        sa.ForeignKeyConstraint(
            ["provider_identity_id"],
            ["provider_identities.id"],
            name="fk_identity_links_provider_identity_id_provider_identities",
        ),
        sa.ForeignKeyConstraint(
            ["verified_by_user_id"],
            ["users.id"],
            name="fk_identity_links_verified_by_user_id_users",
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by_id"],
            ["identity_links.id"],
            name="fk_identity_links_superseded_by_id_identity_links",
        ),
    )
    op.create_index(
        "identity_links_active_idx",
        "identity_links",
        ["provider_identity_id"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )
    op.create_index(
        "identity_links_entity_idx", "identity_links", ["fcp_entity_kind", "fcp_entity_id"]
    )

    op.create_table(
        "identity_review_queue",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider_identity_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "candidates", postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False
        ),
        sa.Column(
            "status", enums.review_status, server_default=sa.text("'open'"), nullable=False
        ),
        sa.Column("resolved_link_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_identity_review_queue"),
        sa.ForeignKeyConstraint(
            ["provider_identity_id"],
            ["provider_identities.id"],
            name="fk_identity_review_queue_provider_identity_id",
        ),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["ingestion_runs.id"],
            name="fk_identity_review_queue_ingestion_run_id_ingestion_runs",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_link_id"],
            ["identity_links.id"],
            name="fk_identity_review_queue_resolved_link_id_identity_links",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"],
            ["users.id"],
            name="fk_identity_review_queue_resolved_by_user_id_users",
        ),
    )
    op.create_index(
        "identity_review_open_idx",
        "identity_review_queue",
        ["status", "created_at"],
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_table("identity_review_queue")
    op.drop_table("identity_links")
    op.drop_table("provider_identities")
    op.drop_table("players")

    bind = op.get_bind()
    for enum_type in reversed(ENUM_TYPES):
        enum_type.drop(bind, checkfirst=False)
