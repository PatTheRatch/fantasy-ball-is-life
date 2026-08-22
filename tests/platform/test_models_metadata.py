"""Metadata guard: the models declare the tables and enum types they should.

No database needed — this asserts against ``Base.metadata`` so a typo in a table
name or enum type is caught without a Postgres round-trip.
"""

from __future__ import annotations

from backend.platform.db import Base

EXPECTED_TABLES = {
    "nba_seasons",
    "players",
    "leagues",
    "league_seasons",
    "categories",
    "league_season_categories",
    "fantasy_teams",
    "fantasy_team_seasons",
    "matchup_periods",
    "matchups",
    "matchup_category_results",
    "fantasy_team_season_managers",
    "providers",
    "provider_connections",
    "ingestion_runs",
    "raw_payloads",
    "provider_identities",
    "identity_links",
    "identity_review_queue",
}

#: (table, column) -> expected native Postgres enum type name.
ENUM_COLUMNS = {
    ("league_seasons", "status"): "league_season_status",
    ("league_seasons", "provider_key"): "provider_key",
    ("categories", "kind"): "category_kind",
    ("matchup_periods", "type"): "period_type",
    ("matchup_periods", "status"): "period_status",
    ("fantasy_team_season_managers", "role"): "manager_role",
    ("providers", "key"): "provider_key",
    ("ingestion_runs", "status"): "run_status",
    ("provider_identities", "entity_kind"): "provider_entity_kind",
    ("identity_links", "fcp_entity_kind"): "provider_entity_kind",
    ("identity_links", "match_method"): "match_method",
    ("identity_review_queue", "status"): "review_status",
    ("matchups", "status"): "period_status",
    ("matchups", "computed_result"): "matchup_result",
    ("matchups", "provider_result"): "matchup_result",
    ("matchup_category_results", "result"): "matchup_result",
}

#: The synced canonical tables that must carry a lineage column.
LINEAGE_TABLES = (
    "league_seasons",
    "league_season_categories",
    "fantasy_team_seasons",
    "matchup_periods",
    "matchups",
)


def test_fantasy_tables_are_registered() -> None:
    actual = set(Base.metadata.tables)
    assert actual >= EXPECTED_TABLES, f"missing tables: {EXPECTED_TABLES - actual}"


def test_enum_columns_carry_expected_types() -> None:
    for (table, column), expected in ENUM_COLUMNS.items():
        col = Base.metadata.tables[table].columns[column]
        assert col.type.name == expected, f"{table}.{column} is {col.type.name}, not {expected}"


def test_synced_tables_carry_lineage_column() -> None:
    for table in LINEAGE_TABLES:
        cols = Base.metadata.tables[table].columns
        assert "ingestion_run_id" in cols, f"{table} is missing its lineage column"
