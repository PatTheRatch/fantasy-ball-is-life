"""Identity tables: users, managers, manager_user_links.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-21

S1-05 · Identity + tenancy. Creates the three pure-identity tables exactly per
docs/v2/schema/01-identity.md, plus the partial unique index enforcing at most
one primary user per manager. Constraint names match Base.metadata's naming
convention so a future autogenerate sees no drift.

``email`` is ``citext`` (case-insensitive unique) — the extension is enabled by
0001. Downgrade drops the index then the tables (reverse dependency order).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("auth_subject", sa.Text(), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("auth_subject", name="uq_users_auth_subject"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_table(
        "managers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_managers"),
    )

    op.create_table(
        "manager_user_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("manager_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "linked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("linked_by_user_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_manager_user_links"),
        sa.ForeignKeyConstraint(
            ["manager_id"], ["managers.id"], name="fk_manager_user_links_manager_id_managers"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_manager_user_links_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["linked_by_user_id"],
            ["users.id"],
            name="fk_manager_user_links_linked_by_user_id_users",
        ),
        sa.UniqueConstraint("manager_id", "user_id", name="uq_manager_user_links_manager_user"),
    )

    op.create_index(
        "manager_user_links_one_primary_idx",
        "manager_user_links",
        ["manager_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )


def downgrade() -> None:
    op.drop_index("manager_user_links_one_primary_idx", table_name="manager_user_links")
    op.drop_table("manager_user_links")
    op.drop_table("managers")
    op.drop_table("users")
