"""
FCP Projections M-3a — NBA data reader.

Reads nba_player_seasons and nba_player_bio from Supabase via RecapStore
and returns pandas DataFrames with the M-1 data contract.  Handles empty
tables gracefully (the prod backfill may not have run yet).
"""

from __future__ import annotations

import logging

import pandas as pd

from backend.recaps.store import RecapStore

logger = logging.getLogger(__name__)

# Column type map so numeric columns don't become object dtype
_NUMERIC_COLS: dict[str, str] = {
    "person_id": "Int64",
    "season": "Int64",
    "age": "float64",
    "gp": "Int64",
    "gs": "Int64",
    "minutes": "float64",
    "mpg": "float64",
    "fgm": "float64",
    "fga": "float64",
    "ftm": "float64",
    "fta": "float64",
    "tpm": "float64",
    "tpa": "float64",
    "tov": "float64",
    "usg_pct": "float64",
    "pts": "float64",
    "reb": "float64",
    "ast": "float64",
    "stl": "float64",
    "blk": "float64",
    "team_pace": "float64",
    "team_ortg": "float64",
}


def read_player_seasons(
    store: RecapStore,
    *,
    season: int | None = None,
) -> pd.DataFrame:
    """Read all nba_player_seasons rows, optionally filtered by season.

    Returns a DataFrame with the M-1 data contract:
      - Stats are per-game averages, exactly as the ingest stored them.
      - ``minutes`` is the season total; ``mpg`` is minutes/game.
      - ``usg_pct``, ``team_pace``, ``team_ortg`` may be NaN (advanced data
        is fetched in a second pass that may not have run yet).
      - Unique key: (person_id, season).
      - ``normalized_name`` is the join key to ESPN players.

    Empty table → empty DataFrame with the correct columns (no crash).
    """
    rows = store.list_nba_player_seasons(season=season)

    if not rows:
        logger.info(
            "nba_player_seasons is empty — the prod backfill may not have run yet. "
            "Returning an empty DataFrame with the expected schema."
        )
        return pd.DataFrame(columns=list(_NUMERIC_COLS) + [
            "normalized_name", "display_name", "team", "position", "fetched_at",
        ])

    df = pd.DataFrame(rows)

    # Coerce numeric columns (PostgREST returns them as strings for JSON safety)
    for col, dtype in _NUMERIC_COLS.items():
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(dtype)

    return df


def read_player_bios(store: RecapStore) -> pd.DataFrame:
    """Read all nba_player_bio rows.

    Empty table → empty DataFrame with the correct columns (no crash).
    """
    rows = store.list_nba_player_bios()

    if not rows:
        logger.info(
            "nba_player_bio is empty — the prod backfill may not have run yet. "
            "Returning an empty DataFrame."
        )
        return pd.DataFrame(columns=[
            "person_id", "normalized_name", "display_name", "dob",
            "height", "weight", "position", "draft_year", "draft_round",
            "draft_pick", "experience",
        ])

    df = pd.DataFrame(rows)

    # Coerce numeric columns
    for col in ("person_id", "weight", "draft_year", "draft_round", "draft_pick", "experience"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "person_id" in df.columns:
        df["person_id"] = df["person_id"].astype("Int64")

    return df
