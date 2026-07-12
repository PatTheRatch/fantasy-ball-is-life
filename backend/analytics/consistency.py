from __future__ import annotations

import argparse
import math
import sqlite3
from functools import lru_cache
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

DB_PATH_DEFAULT = "data/game_logs.db"

# Filter thresholds to reduce noise from tiny samples.
MIN_GAME_MINUTES = 18
MIN_SEASON_AVG_MINUTES = 22

# Standard stats in your SQLite schema.
STAT_COLS = [
    "pts",
    "reb",
    "ast",
    "stl",
    "blk",
    "to",
    "fgm",
    "fga",
    "ftm",
    "fta",
    "3pm",
]

# For get_confidence direction handling.
LOWER_IS_BETTER = {"to"}  # turnovers


def _quoted_col(col: str) -> str:
    if col in {"to", "3pm"}:
        return f"\"{col}\""
    return col


def load_game_logs(db_path: str) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        select_cols = ["player_name", "season"] + STAT_COLS + ["minutes"]
        cols_sql = ", ".join(_quoted_col(c) for c in select_cols)
        sql = f"""
            SELECT {cols_sql}
            FROM game_logs
            WHERE minutes IS NOT NULL AND minutes >= {MIN_GAME_MINUTES}
        """
        df = pd.read_sql_query(sql, conn)
        # ensure numeric
        for c in STAT_COLS + ["minutes"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df
    finally:
        conn.close()


def compute_player_season_averages(game_logs: pd.DataFrame) -> pd.DataFrame:
    # Mean of game-level stats across games where minutes > 0.
    avg_df = game_logs.groupby(["player_name", "season"], as_index=False).agg(
        **{c: (c, "mean") for c in STAT_COLS},
        avg_minutes=("minutes", "mean"),
    )
    avg_df = avg_df[avg_df["avg_minutes"] >= MIN_SEASON_AVG_MINUTES].copy()
    avg_df = avg_df.rename(columns={c: f"avg_{c}" for c in STAT_COLS})
    return avg_df


def assign_tiers_qcut(avg_df: pd.DataFrame) -> pd.DataFrame:
    out = avg_df.copy()
    for stat in STAT_COLS:
        series = out[f"avg_{stat}"]
        # pandas qcut gives quantile bins from the actual data distribution.
        try:
            out[f"tier_{stat}"] = pd.qcut(
                series,
                q=10,
                labels=list(range(1, 11)),
                duplicates="drop",
            ).astype(float)
        except Exception:
            # Fallback: rank-based percentiles always produce 1..10.
            # (Still data-driven, but not strictly qcut.)
            pct = series.rank(method="average", pct=True).fillna(0)
            tier = (pct * 10).astype(int) + 1
            tier = tier.clip(1, 10)
            out[f"tier_{stat}"] = tier.astype(float)

        # normalize missing -> NaN
        out[f"tier_{stat}"] = pd.to_numeric(out[f"tier_{stat}"], errors="coerce")
    return out


def compute_stat_distributions(
    game_logs: pd.DataFrame,
    player_tiers: pd.DataFrame,
) -> pd.DataFrame:
    # Join per-player season tiers onto game rows, so tier buckets apply to each game.
    tier_cols = [f"tier_{s}" for s in STAT_COLS]
    join_df = game_logs.merge(
        player_tiers[["player_name", "season"] + [f"avg_{s}" for s in STAT_COLS] + tier_cols],
        on=["player_name", "season"],
        how="inner",
    )

    rows: list[dict[str, Any]] = []
    for stat in STAT_COLS:
        tier_col = f"tier_{stat}"
        for tier in range(1, 11):
            g = join_df[join_df[tier_col] == tier][stat].dropna()
            if g.empty:
                rows.append(
                    {
                        "stat": stat,
                        "tier": tier,
                        "mean": np.nan,
                        "std": np.nan,
                        "p10": np.nan,
                        "p25": np.nan,
                        "p75": np.nan,
                        "p90": np.nan,
                        "sample_size": 0,
                    }
                )
                continue
            rows.append(
                {
                    "stat": stat,
                    "tier": tier,
                    "mean": float(g.mean()),
                    "std": float(g.std(ddof=1)) if len(g) > 1 else 0.0,
                    "p10": float(g.quantile(0.10)),
                    "p25": float(g.quantile(0.25)),
                    "p75": float(g.quantile(0.75)),
                    "p90": float(g.quantile(0.90)),
                    "sample_size": int(len(g)),
                }
            )
    return pd.DataFrame(rows)


def write_tables(
    db_path: str,
    *,
    stat_distributions: pd.DataFrame,
    player_tiers: pd.DataFrame,
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # Keep existing game_logs, overwrite the derived tables.
        cur.execute("DROP TABLE IF EXISTS stat_distributions;")
        cur.execute("DROP TABLE IF EXISTS player_tiers;")
        conn.commit()

        stat_distributions.to_sql("stat_distributions", conn, index=False)
        player_tiers.to_sql("player_tiers", conn, index=False)
        conn.commit()
    finally:
        conn.close()


def _tier_for_value_qcut(avg_series: pd.Series, player_avg: float) -> Optional[int]:
    """
    Assign tier number (1..10) for a value using qcut bin edges learned
    from the historical avg_series.
    """
    avg_series = pd.to_numeric(avg_series, errors="coerce").dropna()
    if avg_series.empty:
        return None

    # Learn bin edges from data.
    try:
        # retbins provides bin edges; we can then cut the new value.
        _, bins = pd.qcut(avg_series, q=10, retbins=True, duplicates="drop")
        # If bins got collapsed due to duplicates, pandas may return <6 edges.
        labels = list(range(1, 11))
        cut = pd.cut([player_avg], bins=bins, labels=labels, include_lowest=True)
        # `pd.cut([x], ...)` returns a Categorical; index it directly.
        val = cut[0]
        if pd.isna(val):
            # Clamp out-of-range values into nearest tier.
            try:
                lo = float(bins[0])
                hi = float(bins[-1])
                if player_avg < lo:
                    return int(labels[0])
                if player_avg > hi:
                    return int(labels[-1])
            except Exception:
                pass
            return None
        return int(val)
    except Exception:
        # Fallback: rank-based buckets.
        pct = avg_series.rank(pct=True).mean()  # dummy; we do deterministic below
        ranks = avg_series.rank(method="average", pct=True)
        # use overall distribution percentile by comparing to sorted values
        sorted_vals = np.sort(avg_series.to_numpy())
        idx = np.searchsorted(sorted_vals, player_avg, side="right") - 1
        pct2 = (idx + 1) / max(1, len(sorted_vals))
        tier = int(pct2 * 10) + 1
        return int(max(1, min(10, tier)))


@lru_cache(maxsize=2)
def _load_cached_for_confidence(db_path: str) -> dict[str, Any]:
    conn = sqlite3.connect(db_path)
    try:
        game_logs = pd.read_sql_query(
            """
            SELECT player_name, season, minutes,
                   pts, reb, ast, stl, blk, "to", fgm, fga, ftm, fta, "3pm"
            FROM game_logs
            WHERE minutes IS NOT NULL AND minutes > 0
            """,
            conn,
        )
        for c in STAT_COLS + ["minutes"]:
            if c in game_logs.columns:
                game_logs[c] = pd.to_numeric(game_logs[c], errors="coerce")

        player_tiers = pd.read_sql_query("SELECT * FROM player_tiers;", conn)
        stat_distributions = pd.read_sql_query("SELECT * FROM stat_distributions;", conn)

        return {
            "game_logs": game_logs,
            "player_tiers": player_tiers,
            "stat_distributions": stat_distributions,
        }
    finally:
        conn.close()


@lru_cache(maxsize=4)
def _build_pct_confidence_model(db_path: str, stat_key: str) -> dict[str, Any]:
    """
    Build a tier-based distribution model for FG% / FT% on the fly.

    This avoids needing to rebuild the precomputed tables when percent
    categories are requested by the API.
    """
    cache = _load_cached_for_confidence(db_path)
    game_logs = cache["game_logs"].copy()

    # Align with the same filtering concept used in the main pipeline.
    game_logs = game_logs[game_logs["minutes"].notna() & (game_logs["minutes"] >= MIN_GAME_MINUTES)].copy()

    if stat_key == "fg%":
        game_logs["_outcome"] = np.where(game_logs["fga"].ne(0), game_logs["fgm"] / game_logs["fga"], np.nan)
    elif stat_key == "ft%":
        game_logs["_outcome"] = np.where(game_logs["fta"].ne(0), game_logs["ftm"] / game_logs["fta"], np.nan)
    else:
        raise ValueError(f"Unexpected pct stat_key '{stat_key}'")

    # Player-season averages for the derived percentage.
    player_season = (
        game_logs.groupby(["player_name", "season"], as_index=False)
        .agg(avg_outcome=("_outcome", "mean"), avg_minutes=("minutes", "mean"))
    )
    player_season = player_season.dropna(subset=["avg_outcome"])
    player_season = player_season[player_season["avg_minutes"] >= MIN_SEASON_AVG_MINUTES].copy()
    if player_season.empty:
        return {
            "bins": None,
            "labels": [],
            "tier_stats": {},
            "tier_outcomes": {},
        }

    avg_series = player_season["avg_outcome"]

    # Learn bin edges from the actual distribution.
    _, bins = pd.qcut(avg_series, q=10, retbins=True, duplicates="drop")
    labels = list(range(1, len(bins)))

    player_season["_tier"] = pd.cut(
        player_season["avg_outcome"],
        bins=bins,
        labels=labels,
        include_lowest=True,
    )
    player_season["_tier"] = pd.to_numeric(player_season["_tier"], errors="coerce")
    player_season = player_season.dropna(subset=["_tier"])

    joined = game_logs.merge(
        player_season[["player_name", "season", "_tier"]],
        on=["player_name", "season"],
        how="inner",
    )

    tier_stats: dict[int, dict[str, Any]] = {}
    tier_outcomes: dict[int, np.ndarray] = {}
    for tier in labels:
        g = joined.loc[joined["_tier"] == tier, "_outcome"].dropna()
        if g.empty:
            tier_stats[int(tier)] = {
                "mean": None,
                "std": None,
                "p10": None,
                "p25": None,
                "p75": None,
                "p90": None,
                "sample_size": 0,
            }
            tier_outcomes[int(tier)] = np.array([], dtype=float)
            continue

        tier_stats[int(tier)] = {
            "mean": float(g.mean()),
            "std": float(g.std(ddof=1)) if len(g) > 1 else 0.0,
            "p10": float(g.quantile(0.10)),
            "p25": float(g.quantile(0.25)),
            "p75": float(g.quantile(0.75)),
            "p90": float(g.quantile(0.90)),
            "sample_size": int(len(g)),
        }
        tier_outcomes[int(tier)] = g.to_numpy(dtype=float)

    return {
        "bins": bins,
        "labels": labels,
        "tier_stats": tier_stats,
        "tier_outcomes": tier_outcomes,
    }


def _tier_from_pct_bins(model: dict[str, Any], player_avg: float) -> Optional[int]:
    bins = model.get("bins")
    labels = model.get("labels") or []
    if bins is None or len(labels) == 0:
        return None
    try:
        # `pd.cut([x], ...)` can return a Categorical; index it directly.
        cut = pd.cut([player_avg], bins=bins, labels=labels, include_lowest=True)
        tier_val = cut[0]
        if pd.isna(tier_val):
            # Clamp out-of-range values.
            try:
                lo = float(bins[0])
                hi = float(bins[-1])
                if player_avg < lo:
                    return int(labels[0])
                if player_avg > hi:
                    return int(labels[-1])
            except Exception:
                pass
            return None
        return int(tier_val)
    except Exception:
        return None


def get_confidence(
    projected_value: float,
    stat: str,
    player_avg: float,
    *,
    db_path: str = DB_PATH_DEFAULT,
    games_played: int = 0,
    total_games: int = 1,
) -> dict[str, Any]:
    """
    Given a projected value and the player's season average for `stat`,
    look up the tier bucket and return tier percentiles + confidence_pct.

    confidence_pct = % of historical game outcomes in that tier that
    hit at least 80% of the projected_value.
    """
    completion_factor: float
    try:
        total_g = int(total_games)
        played_g = int(games_played)
        if total_g <= 0:
            completion_factor = 0.0
        else:
            completion_factor = max(0.0, min(1.0, played_g / total_g))
    except Exception:
        completion_factor = 0.0

    stat_key = stat.strip().lower()
    if stat_key.upper() == "PTS":
        stat_key = "pts"
    elif stat_key.upper() == "REB":
        stat_key = "reb"
    elif stat_key.upper() == "AST":
        stat_key = "ast"
    elif stat_key.upper() == "STL":
        stat_key = "stl"
    elif stat_key.upper() == "BLK":
        stat_key = "blk"
    elif stat_key in {"TO", "to"}:
        stat_key = "to"
    elif stat_key in {"3PM", "3pm"}:
        stat_key = "3pm"
    elif stat_key.upper() == "FG%":
        stat_key = "fg%"
    elif stat_key.upper() == "FT%":
        stat_key = "ft%"

    if stat_key in {"fg%", "ft%"}:
        # Dynamic model for percentage categories.
        model = _build_pct_confidence_model(db_path, stat_key)
        if pd.isna(projected_value) or projected_value is None:
            return {
                "tier": None,
                "p10": None,
                "p25": None,
                "mean": None,
                "p75": None,
                "p90": None,
                "confidence_pct": None,
            }
        tier = _tier_from_pct_bins(model, player_avg)
        if tier is None:
            return {
                "tier": None,
                "p10": None,
                "p25": None,
                "mean": None,
                "p75": None,
                "p90": None,
                "confidence_pct": None,
            }

        stats = model["tier_stats"].get(tier)
        outcomes = model["tier_outcomes"].get(tier)
        if not stats or outcomes is None:
            return {
                "tier": tier,
                "p10": None,
                "p25": None,
                "mean": None,
                "p75": None,
                "p90": None,
                "confidence_pct": None,
            }

        thresh = 0.8 * projected_value
        ok = outcomes >= thresh
        confidence_pct = float(ok.mean() * 100.0) if len(outcomes) > 0 else None
        historical_confidence_pct = 0.0 if confidence_pct is None else float(confidence_pct)
        adjusted_confidence_pct = (
            (completion_factor * 100.0) + ((1.0 - completion_factor) * historical_confidence_pct)
        )

        return {
            "tier": tier,
            "p10": stats.get("p10"),
            "p25": stats.get("p25"),
            "mean": stats.get("mean"),
            "p75": stats.get("p75"),
            "p90": stats.get("p90"),
            "confidence_pct": adjusted_confidence_pct,
        }

    if stat_key not in STAT_COLS:
        raise ValueError(f"Unknown stat '{stat}'. Expected one of: {STAT_COLS}")

    cache = _load_cached_for_confidence(db_path)
    game_logs = cache["game_logs"]
    player_tiers = cache["player_tiers"]
    stat_distributions = cache["stat_distributions"]

    # Determine tier for this player's average.
    avg_col = f"avg_{stat_key}"
    if avg_col not in player_tiers.columns:
        raise KeyError(f"player_tiers is missing column '{avg_col}'. Re-run consistency.py.")

    tier = _tier_for_value_qcut(player_tiers[avg_col], player_avg)
    if tier is None:
        return {
            "tier": None,
            "p10": None,
            "p25": None,
            "mean": None,
            "p75": None,
            "p90": None,
            "confidence_pct": None,
        }

    # Pull tier percentiles from stat_distributions.
    dist_row = stat_distributions[
        (stat_distributions["stat"] == stat_key) & (stat_distributions["tier"] == tier)
    ]
    if dist_row.empty:
        raise RuntimeError(f"No stat distribution row found for stat={stat_key}, tier={tier}")
    dist = dist_row.iloc[0].to_dict()

    # Filter all historical game outcomes in that tier.
    tier_col = f"tier_{stat_key}"
    if tier_col not in player_tiers.columns:
        raise KeyError(f"player_tiers is missing column '{tier_col}'. Re-run consistency.py.")

    joined = game_logs.merge(
        player_tiers[["player_name", "season", tier_col]],
        on=["player_name", "season"],
        how="inner",
    )
    outcomes = joined.loc[joined[tier_col] == tier, stat_key].dropna()
    total = len(outcomes)

    if total == 0:
        confidence_pct = None
    else:
        # "Hit at least 80% of projected value"
        # For turnovers, smaller is better, so we interpret "hit 80%" as <= 80% target.
        thresh = 0.8 * projected_value
        if stat_key in LOWER_IS_BETTER:
            ok = outcomes <= thresh
        else:
            ok = outcomes >= thresh
        confidence_pct = float(ok.mean() * 100.0)

    historical_confidence_pct = 0.0 if confidence_pct is None else float(confidence_pct)
    adjusted_confidence_pct = (
        (completion_factor * 100.0) + ((1.0 - completion_factor) * historical_confidence_pct)
    )

    return {
        "tier": int(tier),
        "p10": dist.get("p10"),
        "p25": dist.get("p25"),
        "mean": dist.get("mean"),
        "p75": dist.get("p75"),
        "p90": dist.get("p90"),
        "confidence_pct": adjusted_confidence_pct,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Build tier-based stat distributions from game_logs.db.")
    ap.add_argument("--db", default=DB_PATH_DEFAULT, help=f"Path to SQLite db (default: {DB_PATH_DEFAULT})")
    args = ap.parse_args()

    game_logs = load_game_logs(args.db)
    if game_logs.empty:
        raise RuntimeError("game_logs table is empty or missing minutes>0 rows.")

    player_avg_df = compute_player_season_averages(game_logs)
    modeled_player_seasons = (
        player_avg_df[["player_name", "season"]].drop_duplicates().shape[0]
        if not player_avg_df.empty
        else 0
    )
    print(
        f"Modeled player-season combinations (avg_minutes >= {MIN_SEASON_AVG_MINUTES}): {modeled_player_seasons:,}"
    )
    player_tiers_df = assign_tiers_qcut(player_avg_df)
    stat_dist_df = compute_stat_distributions(game_logs, player_tiers_df)

    write_tables(
        args.db,
        stat_distributions=stat_dist_df,
        player_tiers=player_tiers_df,
    )

    # Sanity check: print full table (it's small: ~11 stats * 5 tiers).
    stat_dist_df_sorted = stat_dist_df.sort_values(["stat", "tier"]).reset_index(drop=True)
    print("\nStat distribution summary (stat, tier):")
    print(
        stat_dist_df_sorted.to_string(
            index=False,
            float_format=lambda x: f"{x:.4f}" if isinstance(x, (float, np.floating)) else str(x),
        )
    )


if __name__ == "__main__":
    main()

