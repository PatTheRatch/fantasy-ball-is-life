from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional

from pathlib import Path

import pandas as pd
import kagglehub
from kagglehub import KaggleDatasetAdapter


def _infer_season_end_year(dt: pd.Series) -> pd.Series:
    dt = pd.to_datetime(dt, errors="coerce")
    year = dt.dt.year
    month = dt.dt.month
    # For NBA "season ending year", Oct-Dec bumps the season end year.
    return year + (month >= 10).astype(int)


def _infer_date_str(dt: pd.Series) -> pd.Series:
    dt = pd.to_datetime(dt, errors="coerce")
    return dt.dt.strftime("%Y-%m-%d")


def _first_present(df: pd.DataFrame, candidates: list[str]) -> str:
    lower_map = {c.lower(): c for c in df.columns}
    for c in candidates:
        if c in df.columns:
            return c
        cl = c.lower()
        if cl in lower_map:
            return lower_map[cl]
    raise KeyError(f"None of the candidate columns were found: {candidates}")


def clean_and_standardize(df: pd.DataFrame, *, season_start: int, season_end: int) -> pd.DataFrame:
    # --- Player name ---
    if {"firstName", "lastName"}.issubset(df.columns):
        player_name = (df["firstName"].astype(str).str.strip() + " " + df["lastName"].astype(str).str.strip()).str.strip()
    else:
        player_name_col = _first_present(df, ["player_name", "playerName", "Player", "player"])
        player_name = df[player_name_col].astype(str).str.strip()

    # --- Dates / season ---
    datetime_col = None
    if "gameDateTimeEst" in df.columns:
        datetime_col = "gameDateTimeEst"
    elif "gameDateTime" in df.columns:
        datetime_col = "gameDateTime"
    elif "gameDate" in df.columns:
        datetime_col = "gameDate"

    if datetime_col is None:
        raise KeyError("Could not find a datetime column (expected one of: gameDateTimeEst, gameDateTime, gameDate).")

    season = _infer_season_end_year(df[datetime_col]).astype("Int64")
    date_str = _infer_date_str(df[datetime_col])

    # --- Team/opponent ---
    team_col = _first_present(df, ["playerteamName", "team"])
    opp_col = _first_present(df, ["opponentteamName", "opponent"])
    team = df[team_col].astype(str).str.strip()
    opponent = df[opp_col].astype(str).str.strip()

    # --- Minutes gate: drop DNP/inactive rows ---
    minutes_col = _first_present(df, ["numMinutes", "minutes", "MIN"])
    minutes = pd.to_numeric(df[minutes_col], errors="coerce")

    dnp_mask = pd.Series(False, index=df.index)
    for label_col in ["gameLabel", "gameSubLabel"]:
        if label_col in df.columns:
            dnp_mask = dnp_mask | df[label_col].astype(str).str.contains("DNP", case=False, na=False)

    keep = minutes.notna() & (minutes > 0) & (~dnp_mask)

    df2 = pd.DataFrame(
        {
            "player_name": player_name,
            "season": season,
            "date": date_str,
            "team": team,
            "opponent": opponent,
            "minutes": minutes,
        }
    ).loc[keep].copy()

    # --- Box score stats ---
    # These column names match the Kaggle dataset's PlayerStatistics.csv.
    pts_col = _first_present(df, ["points"])
    reb_col = _first_present(df, ["reboundsTotal"])
    ast_col = _first_present(df, ["assists"])
    stl_col = _first_present(df, ["steals"])
    blk_col = _first_present(df, ["blocks"])
    to_col = _first_present(df, ["turnovers"])
    fgm_col = _first_present(df, ["fieldGoalsMade"])
    fga_col = _first_present(df, ["fieldGoalsAttempted"])
    ftm_col = _first_present(df, ["freeThrowsMade"])
    fta_col = _first_present(df, ["freeThrowsAttempted"])
    three_pm_col = _first_present(df, ["threePointersMade"])

    # Attach stats from original df using the same keep mask index.
    stats_df = pd.DataFrame(
        {
            "pts": pd.to_numeric(df[pts_col], errors="coerce"),
            "reb": pd.to_numeric(df[reb_col], errors="coerce"),
            "ast": pd.to_numeric(df[ast_col], errors="coerce"),
            "stl": pd.to_numeric(df[stl_col], errors="coerce"),
            "blk": pd.to_numeric(df[blk_col], errors="coerce"),
            "to": pd.to_numeric(df[to_col], errors="coerce"),
            "fgm": pd.to_numeric(df[fgm_col], errors="coerce"),
            "fga": pd.to_numeric(df[fga_col], errors="coerce"),
            "ftm": pd.to_numeric(df[ftm_col], errors="coerce"),
            "fta": pd.to_numeric(df[fta_col], errors="coerce"),
            "3pm": pd.to_numeric(df[three_pm_col], errors="coerce"),
        }
    ).loc[keep].copy()

    out = pd.concat([df2.reset_index(drop=True), stats_df.reset_index(drop=True)], axis=1)

    # Drop rows with missing season/date/team/opponent essentials.
    out = out.dropna(subset=["season", "date", "team", "opponent", "player_name", "minutes"])
    out["season"] = out["season"].astype(int)

    # Filter seasons.
    out = out[(out["season"] >= season_start) & (out["season"] <= season_end)]

    # Final numeric float cleanup.
    for c in ["pts", "reb", "ast", "stl", "blk", "to", "fgm", "fga", "ftm", "fta", "3pm", "minutes"]:
        out[c] = pd.to_numeric(out[c], errors="coerce").astype(float)

    # Round numeric stats? requirement says none for DB; keep full precision.
    return out


def write_to_sqlite(df: pd.DataFrame, db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA foreign_keys=ON;")

        # Recreate table so schema matches the standard schema exactly.
        cur.execute("DROP TABLE IF EXISTS game_logs;")
        conn.commit()

        cur.execute(
            """
            CREATE TABLE game_logs (
                player_name TEXT NOT NULL,
                season INTEGER NOT NULL,
                date TEXT NOT NULL,
                team TEXT,
                opponent TEXT,
                pts REAL,
                reb REAL,
                ast REAL,
                stl REAL,
                blk REAL,
                "to" REAL,
                fgm REAL,
                fga REAL,
                ftm REAL,
                fta REAL,
                "3pm" REAL,
                minutes REAL,
                UNIQUE(player_name, season, date, team, opponent)
            );
            """
        )
        conn.commit()

        cols = ["player_name", "season", "date", "team", "opponent", "pts", "reb", "ast", "stl", "blk", "to", "fgm", "fga", "ftm", "fta", "3pm", "minutes"]

        def qident(c: str) -> str:
            # Quote columns that are reserved or not valid identifiers.
            if c in {"to", "3pm"}:
                return f"\"{c}\""
            return c

        col_list = ",".join(qident(c) for c in cols)
        placeholders = ",".join(["?"] * len(cols))
        insert_sql = f"INSERT OR IGNORE INTO game_logs ({col_list}) VALUES ({placeholders});"

        # Chunked inserts so we can handle big datasets without building huge Python lists.
        batch_size = 5000
        batch = []
        inserted_rows = 0
        for row in df[cols].itertuples(index=False, name=None):
            batch.append(row)
            if len(batch) >= batch_size:
                cur.executemany(insert_sql, batch)
                conn.commit()
                inserted_rows += len(batch)
                batch = []
        if batch:
            cur.executemany(insert_sql, batch)
            conn.commit()
            inserted_rows += len(batch)

        conn.commit()

        (count,) = cur.execute("SELECT COUNT(*) FROM game_logs;").fetchone()
        return int(count)
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Load NBA player game logs from Kaggle into SQLite.")
    ap.add_argument("--db", default="data/game_logs.db", help="SQLite db path (default: data/game_logs.db)")
    ap.add_argument("--season-start", type=int, default=2020, help="Filter season start (season ending year; default: 2020)")
    ap.add_argument("--season-end", type=int, default=2025, help="Filter season end (season ending year; default: 2025)")
    args = ap.parse_args()

    # --- Required loading code (verbatim style) ---
    df = kagglehub.load_dataset(
        KaggleDatasetAdapter.PANDAS,
        "eoinamoore/historical-nba-data-and-player-box-scores",
        "PlayerStatistics.csv",
    )

    # Print so we can confirm the dataset schema.
    print("Kaggle df.columns:")
    print(df.columns.tolist())
    print("\nKaggle df.head():")
    print(df.head())

    # Clean + rename into standard schema.
    cleaned = clean_and_standardize(df, season_start=args.season_start, season_end=args.season_end)

    # Write into SQLite.
    written = write_to_sqlite(cleaned, args.db)
    print(f"Done. Rows written to {args.db}: {written:,}")

    # If you previously downloaded the CSV into this repo, remove it now.
    # Kagglehub itself downloads to a cache, but your repo might still contain a manual copy.
    for local_csv in (Path("PlayerStatistics.csv"), Path("data/PlayerStatistics.csv")):
        if local_csv.exists():
            try:
                local_csv.unlink()
                print(f"Cleaned up: deleted local {local_csv}")
            except Exception as e:
                print(f"Cleanup warning: could not delete {local_csv}: {e}")


if __name__ == "__main__":
    main()

