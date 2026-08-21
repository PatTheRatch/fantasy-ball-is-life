"""Native Postgres enum types, shared by the models and the migrations.

These are *closed sets* (schema README §Enums-vs-lookup-tables): they change
only with a code change, so they are Postgres ``enum`` types rather than lookup
tables. ``create_type=False`` on every one of them means the ORM never emits
type DDL — the migrations own all DDL (``0003_fantasy_core`` creates them, and
a future ``04`` migration must reuse them with ``create_type=False``, not
re-``CREATE TYPE``).
"""

from __future__ import annotations

from sqlalchemy.dialects.postgresql import ENUM

#: 04-provider-ingestion. Yahoo/Sleeper are members from day one even though no
#: adapter exists (charter D5) — the multi-provider intent is visible in schema.
provider_key = ENUM(
    "espn", "yahoo", "sleeper", "nba", "kaggle", "bbm", "hashtag", "manual",
    name="provider_key", create_type=False,
)

league_season_status = ENUM(
    "pending", "active", "complete", name="league_season_status", create_type=False
)

category_kind = ENUM("counting", "ratio", name="category_kind", create_type=False)

period_type = ENUM(
    "regular", "playoff", "championship", "consolation", "break",
    name="period_type", create_type=False,
)

period_status = ENUM(
    "scheduled", "in_progress", "final", name="period_status", create_type=False
)

manager_role = ENUM("owner", "co_manager", name="manager_role", create_type=False)
