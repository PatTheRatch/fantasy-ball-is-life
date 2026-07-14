"""Contract test for P-3 consumer swap.

Asserts that the optimizer produces identical output whether fed
PlayerProjection rows (new framework path) or raw BBM DataFrame
(old legacy path) from the same fixture data.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.projections.bbm_adapter import BbmAdapter
from backend.draft.optimizer import _projections_to_optimizer_df


# ---------------------------------------------------------------------------
# Gold fixture: a small but realistic BBM season-export sheet
# ---------------------------------------------------------------------------

def _season_fixture() -> pd.DataFrame:
    """10-player mini BBM season export."""
    return pd.DataFrame({
        "Name": [
            "Nikola Jokic", "Luka Doncic", "Shai Gilgeous-Alexander",
            "Giannis Antetokounmpo", "Jayson Tatum", "Anthony Davis",
            "Tyrese Haliburton", "Stephen Curry", "Joel Embiid",
            "Victor Wembanyama",
        ],
        "Team": ["DEN", "DAL", "OKC", "MIL", "BOS", "LAL", "IND", "GSW", "PHI", "SAS"],
        "Pos": ["C", "PG", "PG", "PF", "SF", "PF", "PG", "PG", "C", "C"],
        "g": ["70", "68", "72", "65", "74", "60", "70", "66", "55", "68"],
        "p": ["26.0", "32.0", "30.0", "28.0", "27.0", "24.0", "20.0", "27.0", "33.0", "22.0"],
        "3": ["1.0", "3.0", "1.5", "0.8", "3.2", "0.5", "2.8", "5.0", "1.2", "1.5"],
        "r": ["12.0", "8.5", "5.5", "11.0", "8.0", "12.5", "4.0", "4.5", "10.0", "10.5"],
        "a": ["9.0", "8.0", "6.0", "5.5", "4.5", "3.0", "10.5", "5.0", "4.0", "3.0"],
        "s": ["1.4", "1.5", "1.8", "1.0", "1.0", "1.2", "1.5", "1.0", "1.0", "1.2"],
        "b": ["0.7", "0.5", "0.8", "1.2", "0.7", "2.2", "0.6", "0.2", "1.5", "3.5"],
        "fga": ["18.0", "22.0", "20.0", "19.0", "20.0", "17.0", "14.0", "20.0", "20.0", "15.0"],
        "fta": ["5.5", "7.0", "8.0", "9.0", "5.0", "6.0", "3.0", "4.0", "9.0", "5.0"],
        "to": ["3.0", "3.5", "2.0", "3.0", "2.5", "2.0", "2.5", "3.0", "3.5", "2.5"],
        "fg%": [".560", ".490", ".510", ".580", ".470", ".540", ".480", ".450", ".530", ".490"],
        "ft%": [".820", ".750", ".910", ".680", ".850", ".780", ".860", ".920", ".850", ".800"],
        "LeagV": ["1.80", "1.70", "1.60", "1.55", "1.50", "1.45", "1.40", "1.35", "1.30", "1.25"],
        "Inj": ["", "", "", "", "", "", "", "", "", ""],
    })


# ---------------------------------------------------------------------------
# Contract: identical DataFrames from both paths
# ---------------------------------------------------------------------------

def test_projection_rows_and_df_produce_identical_optimizer_input():
    """BbmAdapter.parse() → _projections_to_optimizer_df() must produce
    the same DataFrame as the raw fixture after the same column
    normalization."""
    fixture = _season_fixture()

    # Path A: BbmAdapter → PlayerProjection → optimizer df
    adapter = BbmAdapter()
    proj_rows = adapter.parse(raw_df=fixture)
    df_from_rows = _projections_to_optimizer_df(proj_rows)

    # Path B: raw fixture passed through the same normalization that
    # the existing process_draft_data() applies (rename bare columns)
    _SEASON_RENAME = {
        "p": "p/g", "3": "3/g", "r": "r/g", "a": "a/g",
        "s": "s/g", "b": "b/g", "fga": "fga/g", "fta": "fta/g",
        "to": "to/g",
    }
    df_legacy = fixture.copy()
    df_legacy.rename(columns=_SEASON_RENAME, inplace=True)

    # Compare numeric columns (the ones that matter)
    _NUM_COLS = ["p/g", "3/g", "r/g", "a/g", "s/g", "b/g",
                  "fga/g", "fta/g", "to/g", "fg%", "ft%", "g"]
    for col in _NUM_COLS:
        if col in df_legacy.columns:
            df_legacy[col] = pd.to_numeric(df_legacy[col], errors="coerce")
        if col in df_from_rows.columns:
            df_from_rows[col] = pd.to_numeric(df_from_rows[col], errors="coerce")

    # Check row count
    assert len(df_from_rows) == len(fixture)

    # Check player names
    assert set(df_from_rows["Name"].tolist()) == set(fixture["Name"].tolist())

    # Check key stat values are identical per player
    for player_name in fixture["Name"]:
        row_a = df_from_rows[df_from_rows["Name"] == player_name]
        row_b = df_legacy[df_legacy["Name"] == player_name]
        if row_a.empty or row_b.empty:
            continue
        for col in _NUM_COLS:
            a_val = row_a[col].values[0]
            b_val = row_b[col].values[0]
            assert abs(float(a_val) - float(b_val)) < 0.01, \
                f"{player_name}/{col}: {a_val} != {b_val}"

    # Check games column
    assert all(pd.notna(df_from_rows["g"]))

    # Check positions are non-empty
    assert all(df_from_rows["Pos"].str.len() > 0)
