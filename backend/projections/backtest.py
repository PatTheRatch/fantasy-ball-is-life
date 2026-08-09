"""
FCP Projections M-3a — backtest harness + naive baseline.

``evaluate()`` compares predictions to actuals on per-game MAE across eight
categories.  Percentages are derived from makes/attempts (attempt-weighted),
never averaged.  The naive baseline predicts season N from season N-1
unchanged — this is the bar every future model slice must beat.

CLI: ``python -m backend.projections.backtest --season 2024``
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass

import pandas as pd

from backend.nbadata.reader import read_player_seasons
from backend.recaps.store import RecapStore

logger = logging.getLogger(__name__)

# Categories evaluated — per-game, rate-based.
# Percentages are derived from makes/attempts, not stored directly.
CATEGORIES = ["pts", "reb", "ast", "stl", "blk", "tpm", "tov", "fg_pct", "ft_pct"]

# The "counting" categories where MAE is on raw per-game values.
_COUNT_CATS = ["pts", "reb", "ast", "stl", "blk", "tpm", "tov"]

# Map prediction/actual column → what we evaluate.
# For the counting cats it's 1:1.  Percentages are computed.
_CAT_MAP: dict[str, str] = {
    "pts": "pts",
    "reb": "reb",
    "ast": "ast",
    "stl": "stl",
    "blk": "blk",
    "tpm": "tpm",
    "tov": "tov",
}

# ── public API ────────────────────────────────────────────────────────────────


@dataclass
class BacktestResult:
    """One backtest run — per-category MAE + player counts.

    The two exclusion counts answer different questions and must never be
    conflated: ``excluded_low_gp`` is the target-season sample filter
    (below ``min_gp``); ``excluded_no_prediction`` is qualified players the
    prediction set has no row for — for the naive baseline that means no
    prior season, i.e. rookies (M-5's job). Both are reported, never
    silently dropped.
    """

    season: int
    players_evaluated: int
    excluded_low_gp: int          # below min_gp in the target season
    excluded_no_prediction: int   # qualified but absent from predictions (rookies)
    mae: dict[str, float]         # category → mean absolute error
    # Raw data for inspection / plotting (optional)
    errors_df: pd.DataFrame | None = None

    def __repr__(self) -> str:
        lines = [
            f"BacktestResult(season={self.season}, "
            f"n={self.players_evaluated}, "
            f"excluded_low_gp={self.excluded_low_gp}, "
            f"excluded_no_prediction={self.excluded_no_prediction})"
        ]
        for cat, val in self.mae.items():
            lines.append(f"  {cat:>6s}: {val:.4f}")
        return "\n".join(lines)

    def mae_table(self) -> str:
        """Human-readable per-category MAE table."""
        header = f"{'Category':>8s}  {'MAE':>8s}"
        sep = f"{'─' * 8}  {'─' * 8}"
        rows = [header, sep]
        for cat in CATEGORIES:
            if cat in self.mae:
                rows.append(f"{cat:>8s}  {self.mae[cat]:8.4f}")
        rows.append("")
        rows.append(
            f"  Evaluated: {self.players_evaluated}  "
            f"Excluded: {self.excluded_low_gp} below min GP, "
            f"{self.excluded_no_prediction} without a prediction "
            f"(no prior season = rookie, M-5's job)"
        )
        return "\n".join(rows)


def evaluate(
    predictions: pd.DataFrame,
    actuals: pd.DataFrame,
    *,
    min_gp: int = 20,
) -> BacktestResult:
    """Compare predictions to actuals, returning per-category per-game MAE.

    Args:
        predictions: DataFrame with columns ``person_id`` plus per-game
            stat columns (pts, reb, ast, stl, blk, tpm, tov, fgm, fga,
            ftm, fta).
        actuals: DataFrame with the same columns, plus ``gp`` and
            ``season`` for filtering.
        min_gp: Minimum games played in the target season for inclusion.

    Returns:
        BacktestResult with per-category MAE, player counts, and the
        per-player error DataFrame for inspection.

    Percentages (FG%, FT%) are derived from makes/attempts, not averaged:
        FG% error = |pred_fgm/pred_fga - actual_fgm/actual_fga|
        FT% error = |pred_ftm/pred_fta - actual_ftm/actual_fta|
    Attempt-weighted so players taking 1,000 FGA don't carry the same
    percentage weight as players taking 90.
    """
    # Filter actuals to players with sufficient GP
    qualified = actuals[actuals["gp"] >= min_gp].copy()
    excluded_low_gp = actuals["person_id"].nunique() - qualified["person_id"].nunique()

    # Merge on person_id
    merged = pd.merge(
        predictions,
        qualified[["person_id", "gp", "season"] + list(_CAT_MAP.values())
                   + ["fgm", "fga", "ftm", "fta"]],
        on="person_id",
        suffixes=("_pred", "_actual"),
        how="inner",
    )

    players_evaluated = merged["person_id"].nunique()
    # Qualified players the prediction set has no row for. The inner merge
    # drops them silently — count them so they're reported, not vanished.
    excluded_no_prediction = qualified["person_id"].nunique() - players_evaluated

    if players_evaluated == 0:
        return BacktestResult(
            season=int(qualified["season"].iloc[0]) if len(qualified) > 0 else 0,
            players_evaluated=0,
            excluded_low_gp=excluded_low_gp,
            excluded_no_prediction=excluded_no_prediction,
            mae={cat: float("nan") for cat in CATEGORIES},
        )

    mae: dict[str, float] = {}

    # Counting stats — simple abs difference on per-game values
    for cat in _COUNT_CATS:
        col = _CAT_MAP[cat]
        errors = (merged[f"{col}_pred"] - merged[f"{col}_actual"]).abs()
        mae[cat] = float(errors.mean())

    # FG% — attempt-weighted, derived from makes/attempts
    fg_pct_pred = _safe_pct(merged["fgm_pred"], merged["fga_pred"])
    fg_pct_actual = _safe_pct(merged["fgm_actual"], merged["fga_actual"])
    fg_errors = (fg_pct_pred - fg_pct_actual).abs()
    mae["fg_pct"] = _weighted_mae(fg_errors, merged["fga_actual"])

    # FT% — attempt-weighted
    ft_pct_pred = _safe_pct(merged["ftm_pred"], merged["fta_pred"])
    ft_pct_actual = _safe_pct(merged["ftm_actual"], merged["fta_actual"])
    ft_errors = (ft_pct_pred - ft_pct_actual).abs()
    mae["ft_pct"] = _weighted_mae(ft_errors, merged["fta_actual"])

    # Build per-player error DataFrame for inspection
    errors_df = merged[["person_id", "gp"]].copy()
    for cat in _COUNT_CATS:
        col = _CAT_MAP[cat]
        errors_df[f"{cat}_err"] = (merged[f"{col}_pred"] - merged[f"{col}_actual"]).abs()
    errors_df["fg_pct_err"] = fg_errors
    errors_df["ft_pct_err"] = ft_errors

    season_val = int(qualified["season"].iloc[0]) if len(qualified) > 0 else 0

    return BacktestResult(
        season=season_val,
        players_evaluated=players_evaluated,
        excluded_low_gp=excluded_low_gp,
        excluded_no_prediction=excluded_no_prediction,
        mae=mae,
        errors_df=errors_df,
    )


# ── naive baseline ────────────────────────────────────────────────────────────


def naive_baseline(
    store: RecapStore,
    *,
    target_season: int,
    min_gp: int = 20,
) -> BacktestResult:
    """Predict season *target_season* from season *target_season - 1* unchanged.

    This is the bar every future model slice must beat.  Players with no
    prior-season row are excluded (reported as rookies — M-5's job later).

    Returns a BacktestResult you can print or pipe into a comparison table.
    """
    df = read_player_seasons(store)

    if df.empty:
        logger.warning(
            "nba_player_seasons is empty — the prod backfill may not have run yet. "
            "Returning an empty backtest result."
        )
        return BacktestResult(
            season=target_season,
            players_evaluated=0,
            excluded_low_gp=0,
            excluded_no_prediction=0,
            mae={cat: float("nan") for cat in CATEGORIES},
        )

    prior_season = target_season - 1

    # Predictions: each player's prior-season per-game line
    prior = df[df["season"] == prior_season].copy()

    # Actuals: target season stats
    actual = df[df["season"] == target_season].copy()

    pred_cols = list(_CAT_MAP.values()) + ["fgm", "fga", "ftm", "fta"]
    predictions = prior[["person_id"] + pred_cols].copy()

    # Actuals need gp for min_gp filter + season
    actual_for_eval = actual[
        ["person_id", "gp", "season"] + pred_cols
    ].copy()

    return evaluate(predictions, actual_for_eval, min_gp=min_gp)


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    """Entry point: ``python -m backend.projections.backtest --season 2024``"""
    parser = argparse.ArgumentParser(
        description="FCP Projections M-3a — backtest harness (naive baseline)",
    )
    parser.add_argument(
        "--season",
        type=int,
        required=True,
        help="Target (held-out) season to backtest against (e.g. 2024).",
    )
    parser.add_argument(
        "--min-gp",
        type=int,
        default=20,
        help="Minimum games played in target season for inclusion (default: 20).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    store = RecapStore()
    result = naive_baseline(store, target_season=args.season, min_gp=args.min_gp)

    print()
    print(result.mae_table())
    print()
    print("Naive baseline: season N-1 stats repeated unchanged.")
    print(
        "Future slices must beat these MAE values on the same held-out season."
    )

    if result.players_evaluated == 0:
        print()
        print(
            "⚠  No players evaluated — the nba_player_seasons table is likely empty "
            "(the prod backfill may not have run yet).  Run the M-1 ingest first."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()


# ── helpers ───────────────────────────────────────────────────────────────────


def _safe_pct(makes: pd.Series, attempts: pd.Series) -> pd.Series:
    """Derive percentages safely — 0 / 0 → NaN, not inf."""
    result = makes / attempts.replace(0, float("nan"))
    return result.clip(0.0, 1.0)


def _weighted_mae(errors: pd.Series, weights: pd.Series) -> float:
    """Weighted MAE where a NaN error drops the player from BOTH sides.

    A player with an undefined percentage (0 attempts on either side)
    contributes neither error nor weight — leaving their attempts in the
    denominator would silently understate the MAE.
    """
    mask = errors.notna()
    denom = weights[mask].sum()
    if denom <= 0:
        return float("nan")
    return float((errors[mask] * weights[mask]).sum() / denom)
