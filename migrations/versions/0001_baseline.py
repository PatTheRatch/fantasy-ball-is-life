"""Baseline: enable the citext extension.

Revision ID: 0001
Revises:
Create Date: 2026-08-21

S1-04 · Persistence foundation. Establishes the migration chain and proves the
apply/rollback/re-apply round-trip in CI. ``citext`` is what S1-05's
``users.email`` column requires (case-insensitive unique email — see
docs/v2/schema/01-identity.md), so it is real, reversible content, not
speculation. No tables: "no tables beyond what S1-05 needs" (BACKLOG S1-04).

The extension is owned by migrations rather than assumed from the host, so a
fresh CI Postgres container and production stay in lockstep.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS citext")
