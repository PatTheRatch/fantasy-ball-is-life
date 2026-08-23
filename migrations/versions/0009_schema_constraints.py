"""Additive schema constraints (H-05a).

Four constraints behind guarantees the design already states in prose, all
purely additive — no column changes, no FK rewrites, no data migration:

1. ``uq_provider_identities_name_only`` — partial unique index so name-only
   provider identities (``provider_entity_id IS NULL``) have uniqueness on their
   normalised ``raw_name``. Postgres treats NULLs as distinct, so without this a
   concurrent double-resolution forks one external identity into two.
2. ``uq_identity_review_open_per_identity`` — partial unique index so a provider
   identity has at most one *open* review item. The existing ``identity_review_open_idx``
   (a listing index) is left alone.
3. ``ck_identity_links_confidence_range`` — confidence is a probability, bounded
   0..1 inclusive.
4. ``ck_matchup_periods_finality`` — a period's ``status`` and ``finalized_at``
   agree, as an equivalence (a scheduled period with a timestamp is as wrong as a
   final one without).

The check constraints use raw DDL: the ``ck`` naming convention
(``ck_%(table_name)s_%(constraint_name)s``) would double-prefix an already-named
constraint, so the exact name is spelled out here to match the models.

Revision ID: 0009
Revises: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_provider_identities_name_only",
        "provider_identities",
        ["provider_id", "entity_kind", "raw_name"],
        unique=True,
        postgresql_where=sa.text("provider_entity_id IS NULL"),
    )
    op.create_index(
        "uq_identity_review_open_per_identity",
        "identity_review_queue",
        ["provider_identity_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.execute(
        "ALTER TABLE identity_links "
        "ADD CONSTRAINT ck_identity_links_confidence_range "
        "CHECK (confidence >= 0 AND confidence <= 1)"
    )
    op.execute(
        "ALTER TABLE matchup_periods "
        "ADD CONSTRAINT ck_matchup_periods_finality "
        "CHECK ((status = 'final') = (finalized_at IS NOT NULL))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE matchup_periods DROP CONSTRAINT ck_matchup_periods_finality")
    op.execute("ALTER TABLE identity_links DROP CONSTRAINT ck_identity_links_confidence_range")
    op.drop_index("uq_identity_review_open_per_identity", table_name="identity_review_queue")
    op.drop_index("uq_provider_identities_name_only", table_name="provider_identities")
