"""
Monte Carlo draft-target engine.

Ported from the v1 ``monte_carlo_targets.py`` (Patrick's original work). Instead
of deriving category targets from last season's box scores (the historical
method in ``OptimizeLineup.get_target_stats``), this simulates many realistic
drafts of *this* season's projected player pool and reads the targets off the
resulting distribution of buildable teams. It needs no league history, so it
works for a brand-new league on day one.

The public surface used by the optimizer:
  - ``monte_carlo_drafts_13team_daily(pool_df, ...)`` -> per-team distributions
  - ``mc_targets_from_percentile(teams_df, fg, ft, pct)`` -> ``{cat: target}``

Sign convention: this engine sums whatever it is given. Callers that use the
optimizer's internal convention (turnovers stored negated, "higher is better")
should pass turnovers already negated; the resulting TO target then comes back
in that same convention and drops straight into the optimizer's constraints. See
docs/specs/MC_DRAFT_TARGETS.md.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

# The fixed 13-slot roster and per-slot eligibility. Do not reorder casually:
# the Monte Carlo fills these slots (in random order per simulated team).
ROSTER_TEMPLATE: List[str] = [
    "PG", "SG", "SF", "PF", "C",
    "G", "F",
    "UTIL", "UTIL", "UTIL",
    "BN", "BN", "BN",
]

_SLOT_ELIGIBILITY: Dict[str, Tuple[str, ...]] = {
    "PG": ("is_PG",),
    "SG": ("is_SG",),
    "SF": ("is_SF",),
    "PF": ("is_PF",),
    "C": ("is_C",),
    "G": ("is_PG", "is_SG"),
    "F": ("is_SF", "is_PF"),
    "UTIL": ("is_PG", "is_SG", "is_SF", "is_PF", "is_C"),
    "BN": ("is_PG", "is_SG", "is_SF", "is_PF", "is_C"),
}

# Per-week counting-stat columns produced per simulated team, in a fixed order.
_STAT_COLS_PG: Tuple[str, ...] = (
    "PTS_PG", "REB_PG", "AST_PG", "STL_PG", "BLK_PG", "3PM_PG", "TO_PG",
    "FGM_PG", "FGA_PG", "FTM_PG", "FTA_PG",
)

_COL_ALIASES: Dict[str, List[str]] = {
    "PTS_PG": ["PTS_PG", "PTS/G", "PTS", "Points", "p/g"],
    "REB_PG": ["REB_PG", "REB/G", "TRB/G", "REB", "Reb", "r/g"],
    "AST_PG": ["AST_PG", "AST/G", "AST", "Ast", "a/g"],
    "STL_PG": ["STL_PG", "STL/G", "STL", "Stl", "s/g"],
    "BLK_PG": ["BLK_PG", "BLK/G", "BLK", "Blk", "b/g"],
    "3PM_PG": ["3PM_PG", "3PM/G", "3PTM", "3PM", "3P Made", "3P/G", "3-PTM", "3/g"],
    "TO_PG": ["TO_PG", "TOV_PG", "TO/G", "TOV/G", "TO", "TOV", "to/g"],
    "FGM_PG": ["FGM_PG", "FGM/G", "FGM", "FG Made", "fgm/g"],
    "FGA_PG": ["FGA_PG", "FGA/G", "FGA", "FG Att", "fga/g"],
    "FTM_PG": ["FTM_PG", "FTM/G", "FTM", "FT Made", "ftm/g"],
    "FTA_PG": ["FTA_PG", "FTA/G", "FTA", "FT Att", "fta/g"],
    "Price": ["Price", "Auc$", "Cost", "$", "Auction"],
    "Value": ["Value", "ZSum", "VORP", "TotalZ", "Score", "League Value", "LeagV"],
    "Player": ["Player", "Name", "PLAYER"],
    "POS": ["POS", "Position", "Positions", "Pos"],
    "GPW": ["GP_PW", "GPW", "Games_PW", "Games/Week", "G/W"],
}

# Columns that must exist (after aliasing) for a simulation to run.
_REQUIRED_COLS: Tuple[str, ...] = (
    "Player", "Price", "Value",
    "PTS_PG", "REB_PG", "AST_PG", "STL_PG", "BLK_PG", "3PM_PG", "TO_PG",
    "FGM_PG", "FGA_PG", "FTM_PG", "FTA_PG",
)


def _find_col(df: pd.DataFrame, candidates: Iterable[str], required: bool = True) -> Optional[str]:
    """First column in ``df`` matching any candidate (case-insensitive)."""
    for cand in candidates:
        for col in df.columns:
            if col == cand or str(col).lower() == str(cand).lower():
                return col
    if required:
        raise KeyError(
            f"None of {list(candidates)} found in columns: {list(df.columns)[:25]} ..."
        )
    return None


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename source columns to the engine's canonical names via ``_COL_ALIASES``."""
    df = df.copy()
    mapping = {}
    for std, aliases in _COL_ALIASES.items():
        col = _find_col(df, aliases, required=False)
        if col is not None:
            mapping[col] = std
    return df.rename(columns=mapping)


def add_eligibility_flags(df: pd.DataFrame, pos_col: str = "POS") -> pd.DataFrame:
    """Derive boolean ``is_PG..is_C`` columns from a position string like 'PG/SG'."""
    df = df.copy()
    existing = [c for c in df.columns if c in ("is_PG", "is_SG", "is_SF", "is_PF", "is_C")]
    if len(existing) == 5:
        return df
    if pos_col not in df.columns:
        # No positions available: leave flags absent; only UTIL/BN slots fillable.
        for flag in ("is_PG", "is_SG", "is_SF", "is_PF", "is_C"):
            df[flag] = False
        return df

    def tags_for(pos_str: object) -> set:
        if not isinstance(pos_str, str):
            return set()
        parts = pos_str.replace("/", ",").replace(" ", "").split(",")
        return {p.upper() for p in parts if p}

    is_pg, is_sg, is_sf, is_pf, is_c = [], [], [], [], []
    for s in df[pos_col].astype(str):
        tags = tags_for(s)
        is_pg.append("PG" in tags or "G" in tags)
        is_sg.append("SG" in tags or "G" in tags)
        is_sf.append("SF" in tags or "F" in tags)
        is_pf.append("PF" in tags or "F" in tags)
        is_c.append("C" in tags)
    df["is_PG"], df["is_SG"], df["is_SF"], df["is_PF"], df["is_C"] = (
        is_pg, is_sg, is_sf, is_pf, is_c
    )
    return df


def _softmax(x: np.ndarray, alpha: float = 6.0) -> np.ndarray:
    """Numerically stable softmax with a greediness knob ``alpha``."""
    if x.size == 0:
        return x
    z = (x - np.max(x)) * alpha
    np.clip(z, -60, 60, out=z)
    e = np.exp(z)
    s = e.sum()
    return e / s if s > 0 else np.ones_like(x) / len(x)


def monte_carlo_drafts_13team_daily(
    df_raw: pd.DataFrame,
    *,
    n_teams: int = 1000,
    budget: float = 200.0,
    alpha: float = 6.0,
    avg_games_per_week: float = 3.5,
    max_centers: int = 3,
    rng_seed: int = 7,
    max_retries_per_team: int = 250,
) -> Tuple[pd.DataFrame, pd.Series, pd.Series, pd.DataFrame]:
    """
    Simulate ``n_teams`` feasible 13-man rosters (PG,SG,SF,PF,C,G,F,UTILx3,BNx3;
    max 3 C; ``budget`` cap) by softmax-sampling players on value-per-dollar.

    ``avg_games_per_week`` scales per-game stats to per-week. Pass ``1.0`` when
    the input columns are already per-week.

    Returns ``(teams_df, fg_pct, ft_pct, meta_df)`` — one row per simulated team.
    Deterministic given ``rng_seed``.
    """
    df = normalize_columns(df_raw)
    df = add_eligibility_flags(df)
    df = df.reset_index(drop=True).copy()

    missing = [c for c in _REQUIRED_COLS if c not in df.columns]
    if missing:
        raise KeyError(f"Missing required columns after normalization: {missing}")

    n = len(df)
    if n == 0:
        raise ValueError("Empty player DataFrame.")

    gpw = (
        df["GPW"].to_numpy(float)
        if "GPW" in df.columns
        else np.full(n, float(avg_games_per_week), dtype=float)
    )

    stats_pg = df.loc[:, _STAT_COLS_PG].to_numpy(float)
    stats_pw = stats_pg * gpw[:, None]
    (PTS_pw, REB_pw, AST_pw, STL_pw, BLK_pw, TPM_pw, TO_pw,
     FGM_pw, FGA_pw, FTM_pw, FTA_pw) = stats_pw.T

    price = df["Price"].to_numpy(float)
    value = df["Value"].to_numpy(float)
    is_C = df["is_C"].to_numpy(bool)
    elig = {slot: _eligible_mask(df, slot) for slot in set(ROSTER_TEMPLATE)}

    eff = value / np.maximum(price, 1e-6)

    rng = np.random.default_rng(rng_seed)
    teams = 0
    attempts = 0
    max_attempts = n_teams * max_retries_per_team

    teams_rows: List[Dict[str, float]] = []
    fg_list: List[float] = []
    ft_list: List[float] = []
    meta_rows: List[Dict[str, object]] = []

    while teams < n_teams and attempts < max_attempts:
        attempts += 1
        budget_left = float(budget)
        available = np.ones(n, dtype=bool)
        centers_taken = 0
        picks: List[int] = []

        slots = ROSTER_TEMPLATE[:]
        rng.shuffle(slots)

        feasible = True
        for s_idx, slot in enumerate(slots):
            mask = elig[slot] & available
            if centers_taken >= max_centers:
                mask = mask & ~is_C
            cand_idx = np.nonzero(mask)[0]
            if cand_idx.size == 0:
                feasible = False
                break

            # Crude budget floor: reserve the cheapest prices for remaining slots.
            k_remain = len(slots) - s_idx - 1
            rem_prices = price[available]
            if k_remain > 0 and rem_prices.size >= k_remain:
                lb_future = np.partition(rem_prices, k_remain - 1)[:k_remain].sum()
            else:
                lb_future = 0.0

            feas_idx = [c for c in cand_idx if (price[c] + lb_future) <= budget_left + 1e-9]
            if not feas_idx:
                feasible = False
                break

            probs = _softmax(eff[np.array(feas_idx)], alpha=alpha)
            choose = int(rng.choice(feas_idx, p=probs))

            picks.append(choose)
            available[choose] = False
            budget_left -= price[choose]
            if budget_left < -1e-6:
                feasible = False
                break
            if is_C[choose]:
                centers_taken += 1
                if centers_taken > max_centers:
                    feasible = False
                    break

        if not feasible:
            continue

        chosen = np.array(picks, dtype=int)
        team_fgm = float(FGM_pw[chosen].sum())
        team_fga = float(FGA_pw[chosen].sum())
        team_ftm = float(FTM_pw[chosen].sum())
        team_fta = float(FTA_pw[chosen].sum())
        eps = 1e-9

        teams_rows.append({
            "PTS": float(PTS_pw[chosen].sum()),
            "REB": float(REB_pw[chosen].sum()),
            "AST": float(AST_pw[chosen].sum()),
            "STL": float(STL_pw[chosen].sum()),
            "BLK": float(BLK_pw[chosen].sum()),
            "3PM": float(TPM_pw[chosen].sum()),
            "TO": float(TO_pw[chosen].sum()),
            "FGM": team_fgm,
            "FGA": team_fga,
            "FTM": team_ftm,
            "FTA": team_fta,
        })
        fg_list.append(team_fgm / max(team_fga, eps))
        ft_list.append(team_ftm / max(team_fta, eps))
        meta_rows.append({
            "picks": picks,
            "spent": float(budget - budget_left),
            "centers": int(centers_taken),
        })
        teams += 1

    if teams == 0:
        raise RuntimeError(
            "No feasible teams generated. Loosen constraints (budget, centers) or "
            "check the player pool has enough affordable, position-eligible players."
        )

    teams_df = pd.DataFrame(teams_rows)
    fg_pct_series = pd.Series(fg_list, name="FG%")
    ft_pct_series = pd.Series(ft_list, name="FT%")
    meta_df = pd.DataFrame(meta_rows)
    return teams_df, fg_pct_series, ft_pct_series, meta_df


def _eligible_mask(df: pd.DataFrame, slot: str) -> np.ndarray:
    cols = _SLOT_ELIGIBILITY[slot]
    n = len(df)
    if not cols:
        return np.ones(n, dtype=bool)
    m = np.zeros(n, dtype=bool)
    for c in cols:
        if c in df.columns:
            m |= df[c].to_numpy().astype(bool)
    if slot in ("UTIL", "BN"):
        return np.ones(n, dtype=bool)
    return m


def mc_targets_from_percentile(
    teams_df: pd.DataFrame,
    fg_pct: pd.Series,
    ft_pct: pd.Series,
    pct: float = 0.80,
) -> Dict[str, float]:
    """The ``pct``-th percentile team per category → a ``{category: target}`` dict.

    For counting stats, a higher percentile is a more ambitious target. TO follows
    the sign convention of whatever was fed in (negated → "higher is better", so
    the percentile still reads as "ambitious").
    """
    targets = {k: float(v) for k, v in teams_df.quantile(pct).to_dict().items()}
    targets["FG%"] = float(fg_pct.quantile(pct))
    targets["FT%"] = float(ft_pct.quantile(pct))
    return targets
