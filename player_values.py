"""
Projection-derived fantasy basketball auction values.

This module deliberately does not trust an external dollar column as the source
of truth. It converts player projections into category impact, compares each
player to the replacement tier, and distributes the league's auction premium
dollars across the players above that tier.
"""
from __future__ import annotations

from typing import Dict, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

import draft_targets_mc as target_mc


CATEGORIES: Tuple[str, ...] = ("PTS", "REB", "AST", "STL", "BLK", "3PM", "TO", "FG%", "FT%")

_COUNTING_SOURCE: Dict[str, str] = {
    "PTS": "PTS_PG",
    "REB": "REB_PG",
    "AST": "AST_PG",
    "STL": "STL_PG",
    "BLK": "BLK_PG",
    "3PM": "3PM_PG",
    "TO": "TO_PG",
}


def calculate_player_values(
    df_raw: pd.DataFrame,
    *,
    n_teams: int = 12,
    roster_size: int = 13,
    budget: float = 200.0,
    min_bid: float = 1.0,
    dollar_one_players: Optional[int] = None,
    category_weights: Optional[Mapping[str, float]] = None,
    star_exponent: float = 1.15,
) -> pd.DataFrame:
    """Return the projection pool with an internally calculated ``model_value``.

    ``dollar_one_players`` is the expected number of drafted players who only
    carry minimum-bid value. The premium budget is distributed to the remaining
    drafted players by positive production above that replacement tier.
    """

    if n_teams < 1:
        raise ValueError("n_teams must be >= 1")
    if roster_size < 1:
        raise ValueError("roster_size must be >= 1")
    if budget <= 0:
        raise ValueError("budget must be positive")
    if min_bid <= 0:
        raise ValueError("min_bid must be positive")
    if star_exponent <= 0:
        raise ValueError("star_exponent must be positive")

    df = _normalize_value_pool(df_raw)
    drafted_count = int(n_teams * roster_size)
    if len(df) < drafted_count:
        raise ValueError("player pool is smaller than n_teams * roster_size")

    if dollar_one_players is None:
        dollar_one_players = max(n_teams * 2, int(round(drafted_count * 0.15)))
    dollar_one_players = int(np.clip(dollar_one_players, 0, drafted_count - 1))
    premium_player_count = drafted_count - dollar_one_players

    weights = _category_weights(category_weights)
    df = _add_category_value_scores(df, weights)
    df["value_score"] = sum(df[f"{cat}_value_score"] * weights[cat] for cat in CATEGORIES)

    ranked = df["value_score"].sort_values(ascending=False).reset_index(drop=True)
    replacement_index = min(premium_player_count, len(ranked) - 1)
    replacement_score = float(ranked.iloc[replacement_index])
    df["replacement_score"] = replacement_score
    df["replacement_adjusted_score"] = (df["value_score"] - replacement_score).clip(lower=0.0)

    premium_basis = np.power(df["replacement_adjusted_score"].to_numpy(float), star_exponent)
    total_basis = float(premium_basis.sum())
    total_slots = n_teams * roster_size
    premium_budget = (n_teams * budget) - (total_slots * min_bid)

    if total_basis <= 1e-12 or premium_budget <= 0:
        df["model_value"] = min_bid
    else:
        df["model_value"] = min_bid + (premium_budget * premium_basis / total_basis)

    df.loc[df["replacement_adjusted_score"] <= 0, "model_value"] = min_bid
    df["model_value"] = df["model_value"].clip(lower=min_bid)
    df["model_value"] = df["model_value"].round(2)
    df["value_rank"] = df["value_score"].rank(method="first", ascending=False).astype(int)
    df["is_replacement_tier"] = df["replacement_adjusted_score"] <= 0
    return df


def _normalize_value_pool(df_raw: pd.DataFrame) -> pd.DataFrame:
    df = target_mc.normalize_columns(df_raw)
    df = target_mc.add_eligibility_flags(df)
    df = df.reset_index(drop=True).copy()

    missing = [c for c in ("Player", "POS") if c not in df.columns]
    missing.extend(c for c in _COUNTING_SOURCE.values() if c not in df.columns)
    if "FG%" not in df.columns and not {"FGM_PG", "FGA_PG"} <= set(df.columns):
        missing.append("FG% or FGM_PG/FGA_PG")
    if "FT%" not in df.columns and not {"FTM_PG", "FTA_PG"} <= set(df.columns):
        missing.append("FT% or FTM_PG/FTA_PG")
    if missing:
        raise KeyError(f"Missing required value columns after normalization: {missing}")

    if "Price" in df.columns:
        df["external_price"] = pd.to_numeric(df["Price"], errors="coerce")
    else:
        df["external_price"] = np.nan
        df["Price"] = 1.0
    if "Value" in df.columns:
        df["external_value"] = pd.to_numeric(df["Value"], errors="coerce")
    else:
        df["external_value"] = np.nan

    df["Price"] = pd.to_numeric(df["Price"], errors="coerce").fillna(1.0).clip(lower=1.0)
    for col in _COUNTING_SOURCE.values():
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    if "FG%" not in df.columns:
        fgm = pd.to_numeric(df["FGM_PG"], errors="coerce").fillna(0.0)
        fga = pd.to_numeric(df["FGA_PG"], errors="coerce").fillna(0.0)
        df["FG%"] = fgm / fga.replace(0.0, np.nan)
    if "FT%" not in df.columns:
        ftm = pd.to_numeric(df["FTM_PG"], errors="coerce").fillna(0.0)
        fta = pd.to_numeric(df["FTA_PG"], errors="coerce").fillna(0.0)
        df["FT%"] = ftm / fta.replace(0.0, np.nan)
    df["FG%"] = pd.to_numeric(df["FG%"], errors="coerce").fillna(0.0)
    df["FT%"] = pd.to_numeric(df["FT%"], errors="coerce").fillna(0.0)

    for attempts_col in ("FGA_PG", "FTA_PG"):
        if attempts_col not in df.columns:
            df[attempts_col] = 0.0
        df[attempts_col] = pd.to_numeric(df[attempts_col], errors="coerce").fillna(0.0)
    if "FGM_PG" not in df.columns:
        df["FGM_PG"] = df["FG%"] * df["FGA_PG"]
    if "FTM_PG" not in df.columns:
        df["FTM_PG"] = df["FT%"] * df["FTA_PG"]
    for col in ("FGM_PG", "FTM_PG"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


def _add_category_value_scores(df: pd.DataFrame, weights: Mapping[str, float]) -> pd.DataFrame:
    df = df.copy()
    for cat, col in _COUNTING_SOURCE.items():
        df[f"{cat}_value_score"] = _zscore(df[col].to_numpy(float))

    fg_attempts = df["FGA_PG"].to_numpy(float)
    ft_attempts = df["FTA_PG"].to_numpy(float)
    league_fg = _weighted_pct(df["FGM_PG"].to_numpy(float), fg_attempts)
    league_ft = _weighted_pct(df["FTM_PG"].to_numpy(float), ft_attempts)
    df["FG%_impact"] = df["FGM_PG"].to_numpy(float) - (league_fg * fg_attempts)
    df["FT%_impact"] = df["FTM_PG"].to_numpy(float) - (league_ft * ft_attempts)
    df["FG%_value_score"] = _zscore(df["FG%_impact"].to_numpy(float))
    df["FT%_value_score"] = _zscore(df["FT%_impact"].to_numpy(float))

    # Compatibility with the auction-room category-fit code.
    for cat in CATEGORIES:
        df[f"{cat}_score"] = df[f"{cat}_value_score"]
    return df


def _category_weights(raw: Optional[Mapping[str, float]]) -> Dict[str, float]:
    weights = {cat: 1.0 for cat in CATEGORIES}
    if raw:
        for cat, weight in raw.items():
            if cat not in CATEGORIES:
                raise ValueError(f"unknown category weight {cat!r}; expected one of {CATEGORIES}")
            weights[cat] = float(weight)
    return weights


def _weighted_pct(made: np.ndarray, attempts: np.ndarray) -> float:
    total_attempts = float(np.nansum(attempts))
    if total_attempts <= 1e-12:
        return 0.0
    return float(np.nansum(made) / total_attempts)


def _zscore(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    std = float(np.nanstd(values))
    if std <= 1e-9:
        return np.zeros_like(values, dtype=float)
    return (values - float(np.nanmean(values))) / std
