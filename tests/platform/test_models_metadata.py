"""Metadata guard: the models declare the tables and enum types they should.

No database needed — this asserts against ``Base.metadata`` so a typo in a table
name or enum type is caught without a Postgres round-trip.
"""

from __future__ import annotations

from backend.platform.db import Base

EXPECTED_TABLES = {
    "nba_seasons",
    "leagues",
    "league_seasons",
    "categories",
    "league_season_categories",
    "fantasy_teams",
    "fantasy_team_seasons",
    "matchup_periods",
    "fantasy_team_season_managers",
}

#: (table, column) -> expected native Postgres enum type name.
ENUM_COLUMNS = {
    ("league_seasons", "status"): "league_season_status",
    ("league_seasons", "provider_key"): "provider_key",
    ("categories", "kind"): "category_kind",
    ("matchup_periods", "type"): "period_type",
    ("matchup_periods", "status"): "period_status",
    ("fantasy_team_season_managers", "role"): "manager_role",
}


def test_fantasy_tables_are_registered() -> None:
    actual = set(Base.metadata.tables)
    assert actual >= EXPECTED_TABLES, f"missing tables: {EXPECTED_TABLES - actual}"


def test_enum_columns_carry_expected_types() -> None:
    for (table, column), expected in ENUM_COLUMNS.items():
        col = Base.metadata.tables[table].columns[column]
        assert col.type.name == expected, f"{table}.{column} is {col.type.name}, not {expected}"
