"""Seed the nine standard scoring categories (platform reference data).

Charter D11: the product launches on 9-cat H2H, but the schema must not hardcode
nine categories forever — ``categories`` is a lookup table. These nine rows are
the conventional default; their keys MUST match ``backend.domain.categories.NINE_CAT``
exactly (``TPM`` for three-pointers, not ``3PM``) so ingest and the domain layer
agree. Charter D25 ("V2 starts empty") governs league/user data; this is platform
reference data, not a V1 migration.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from backend.models import enums
from backend.models.base import uuid7

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

# (key, display_name, short_name, kind, higher_is_better, numerator, denominator)
_CATEGORIES = (
    ("PTS", "Points", "PTS", "counting", True, None, None),
    ("REB", "Rebounds", "REB", "counting", True, None, None),
    ("AST", "Assists", "AST", "counting", True, None, None),
    ("STL", "Steals", "STL", "counting", True, None, None),
    ("BLK", "Blocks", "BLK", "counting", True, None, None),
    ("TPM", "Three-Pointers Made", "3PM", "counting", True, None, None),
    ("TO", "Turnovers", "TO", "counting", False, None, None),
    ("FG_PCT", "Field Goal Percentage", "FG%", "ratio", True, "fgm", "fga"),
    ("FT_PCT", "Free Throw Percentage", "FT%", "ratio", True, "ftm", "fta"),
)


def upgrade() -> None:
    categories = sa.table(
        "categories",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.Text()),
        sa.column("display_name", sa.Text()),
        sa.column("short_name", sa.Text()),
        sa.column("kind", enums.category_kind),
        sa.column("higher_is_better", sa.Boolean()),
        sa.column("numerator_stat", sa.Text()),
        sa.column("denominator_stat", sa.Text()),
    )
    op.bulk_insert(
        categories,
        [
            {
                "id": uuid7(),
                "key": key,
                "display_name": display_name,
                "short_name": short_name,
                "kind": kind,
                "higher_is_better": higher_is_better,
                "numerator_stat": numerator,
                "denominator_stat": denominator,
            }
            for (key, display_name, short_name, kind, higher_is_better, numerator, denominator)
            in _CATEGORIES
        ],
    )


def downgrade() -> None:
    keys = ", ".join(f"'{c[0]}'" for c in _CATEGORIES)
    op.execute(sa.text(f"DELETE FROM categories WHERE key IN ({keys})"))
