"""
Monte Carlo auction-price simulator.

This is separate from ``draft_targets_mc.py``. That module simulates buildable
teams to derive category targets; this one simulates the auction room itself and
records what each player sells for across many draft paths.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from backend.draft import targets_mc as target_mc
from backend.draft import values as player_values


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


@dataclass(frozen=True)
class ManagerProfile:
    """Auction-room behavior knobs for one simulated manager.

    ``category_weights`` says what the manager is building toward. Positive TO
    weight assumes the optimizer convention where TO is already negated, so a
    higher TO score means fewer turnovers.
    """

    manager_id: str
    label: str
    archetype: str = "balanced"
    category_weights: Mapping[str, float] = field(default_factory=dict)
    aggression: float = 1.0
    star_bias: float = 0.0
    mid_tier_bias: float = 0.0
    value_discipline: float = 1.15
    need_reactivity: float = 0.25
    scarcity_reactivity: float = 0.15
    early_heat: float = 0.0
    bid_noise: float = 0.10
    max_single_player_budget_pct: float = 0.40
    nomination_star_bias: float = 0.0

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], index: int = 0) -> "ManagerProfile":
        data = dict(raw)
        if "manager_id" not in data:
            data["manager_id"] = f"manager_{index + 1}"
        if "label" not in data:
            data["label"] = str(data["manager_id"])
        return cls(**data)


@dataclass
class _TeamState:
    profile: ManagerProfile
    budget_left: float
    roster: List[int] = field(default_factory=list)
    category_totals: Dict[str, float] = field(default_factory=dict)
    category_score_totals: Dict[str, float] = field(default_factory=dict)
    centers: int = 0


@dataclass(frozen=True)
class _RoomState:
    progress: float
    inflation: float
    heat: float
    scarcity: Mapping[str, float]
    min_bid: float
    bid_increment: float
    roster_size: int
    max_centers: int


def default_manager_profiles(n_managers: int = 12) -> List[ManagerProfile]:
    """Cycle through generic manager philosophies for a proof-of-concept room."""

    templates = [
        ManagerProfile(
            "stars_1", "Stars buyer", "stars_and_scrubs",
            {"PTS": 1.1, "3PM": 0.6, "AST": 0.4},
            aggression=1.12, star_bias=0.28, value_discipline=1.35,
            early_heat=0.10, bid_noise=0.14, max_single_player_budget_pct=0.46,
            nomination_star_bias=0.25,
        ),
        ManagerProfile(
            "balanced_1", "Balanced", "balanced",
            {"PTS": 0.7, "REB": 0.7, "AST": 0.7, "STL": 0.55, "BLK": 0.45, "3PM": 0.6},
            aggression=1.0, mid_tier_bias=0.14, value_discipline=1.08,
            bid_noise=0.08, max_single_player_budget_pct=0.28,
        ),
        ManagerProfile(
            "value_1", "Value hunter", "value_hunter",
            {"PTS": 0.6, "REB": 0.6, "AST": 0.6, "STL": 0.5, "BLK": 0.5, "3PM": 0.5},
            aggression=0.92, value_discipline=0.98, need_reactivity=0.18,
            scarcity_reactivity=0.08, bid_noise=0.07, max_single_player_budget_pct=0.25,
        ),
        ManagerProfile(
            "big_1", "Big-man build", "big_man_build",
            {"REB": 1.25, "BLK": 1.35, "FG%": 0.65, "TO": 0.25},
            aggression=1.04, value_discipline=1.18, need_reactivity=0.34,
            scarcity_reactivity=0.25, bid_noise=0.11, max_single_player_budget_pct=0.34,
        ),
        ManagerProfile(
            "guard_1", "Guard stats", "guard_stats_build",
            {"PTS": 0.95, "3PM": 1.25, "AST": 1.15, "FT%": 0.5, "STL": 0.35},
            aggression=1.05, value_discipline=1.18, need_reactivity=0.34,
            scarcity_reactivity=0.18, bid_noise=0.11, max_single_player_budget_pct=0.34,
        ),
        ManagerProfile(
            "scarcity_1", "Scarcity chaser", "scarcity_chaser",
            {"REB": 0.75, "BLK": 0.75, "AST": 0.65, "STL": 0.65},
            aggression=1.02, value_discipline=1.22, need_reactivity=0.24,
            scarcity_reactivity=0.42, bid_noise=0.12, max_single_player_budget_pct=0.36,
        ),
    ]

    profiles: List[ManagerProfile] = []
    for idx in range(n_managers):
        base = templates[idx % len(templates)]
        cycle = idx // len(templates)
        profiles.append(
            replace(
                base,
                manager_id=f"{base.archetype}_{idx + 1}",
                label=f"{base.label} {cycle + 1}" if cycle else base.label,
            )
        )
    return profiles


def prepare_auction_pool(
    df_raw: pd.DataFrame,
    *,
    use_model_values: bool = True,
    n_teams: int = 12,
    roster_size: int = 13,
    budget: float = 200.0,
    min_bid: float = 1.0,
    dollar_one_players: Optional[int] = None,
    category_weights: Optional[Mapping[str, float]] = None,
    star_exponent: float = 1.40,
) -> pd.DataFrame:
    """Normalize projection columns and add scoring helpers used by the room."""

    if use_model_values:
        df = player_values.calculate_player_values(
            df_raw,
            n_teams=n_teams,
            roster_size=roster_size,
            budget=budget,
            min_bid=min_bid,
            dollar_one_players=dollar_one_players,
            category_weights=category_weights,
            star_exponent=star_exponent,
        )
    else:
        df = target_mc.normalize_columns(df_raw)
        df = target_mc.add_eligibility_flags(df)
        df = df.reset_index(drop=True).copy()

    required_identity_cols = ("Player", "Price", "POS") if use_model_values else ("Player", "Price", "Value", "POS")
    missing = [c for c in required_identity_cols if c not in df.columns]
    missing.extend(c for c in _COUNTING_SOURCE.values() if c not in df.columns)
    if "FG%" not in df.columns and not {"FGM_PG", "FGA_PG"} <= set(df.columns):
        missing.append("FG% or FGM_PG/FGA_PG")
    if "FT%" not in df.columns and not {"FTM_PG", "FTA_PG"} <= set(df.columns):
        missing.append("FT% or FTM_PG/FTA_PG")
    if missing:
        raise KeyError(f"Missing required auction columns after normalization: {missing}")

    df["Price"] = pd.to_numeric(df["Price"], errors="coerce").fillna(1.0).clip(lower=1.0)
    if use_model_values:
        df["external_price"] = pd.to_numeric(df.get("external_price", df["Price"]), errors="coerce")
        df["external_value"] = pd.to_numeric(df.get("external_value", np.nan), errors="coerce")
        df["Value"] = pd.to_numeric(df["model_value"], errors="coerce").fillna(df["Price"]).clip(lower=min_bid)
    else:
        df["external_price"] = df["Price"]
        df["external_value"] = pd.to_numeric(df["Value"], errors="coerce")
        df["Value"] = pd.to_numeric(df["Value"], errors="coerce").fillna(df["Price"]).clip(lower=0.0)

    if "FG%" not in df.columns:
        df["FG%"] = pd.to_numeric(df["FGM_PG"], errors="coerce") / pd.to_numeric(df["FGA_PG"], errors="coerce")
    if "FT%" not in df.columns:
        df["FT%"] = pd.to_numeric(df["FTM_PG"], errors="coerce") / pd.to_numeric(df["FTA_PG"], errors="coerce")
    df["FG%"] = pd.to_numeric(df["FG%"], errors="coerce").fillna(0.0)
    df["FT%"] = pd.to_numeric(df["FT%"], errors="coerce").fillna(0.0)

    for cat, col in _COUNTING_SOURCE.items():
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        if f"{cat}_score" not in df.columns:
            df[f"{cat}_score"] = _zscore(df[col].to_numpy(float))
    if "FG%_score" not in df.columns:
        df["FG%_score"] = _zscore(df["FG%"].to_numpy(float))
    if "FT%_score" not in df.columns:
        df["FT%_score"] = _zscore(df["FT%"].to_numpy(float))
    df["star_score"] = _percent_rank(df["Value"].to_numpy(float))
    df["mid_tier_score"] = 1.0 - np.minimum(np.abs(df["star_score"].to_numpy(float) - 0.55) / 0.55, 1.0)
    return df


def simulate_auction_prices(
    df_raw: pd.DataFrame,
    *,
    manager_profiles: Optional[Sequence[ManagerProfile | Mapping[str, Any]]] = None,
    n_simulations: int = 500,
    budget: float = 200.0,
    roster_size: int = 13,
    max_centers: int = 3,
    min_bid: float = 1.0,
    bid_increment: float = 1.0,
    rng_seed: int = 7,
    use_model_values: bool = True,
    dollar_one_players: Optional[int] = None,
    category_weights: Optional[Mapping[str, float]] = None,
    star_exponent: float = 1.40,
    return_sales: bool = False,
) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    """Run full-room auction simulations and summarize each player's price.

    Returns ``(summary_df, sales_df_or_none)``. ``summary_df`` is one row per
    player in the pool; prices are conditional on the player being sold.
    """

    if n_simulations < 1:
        raise ValueError("n_simulations must be >= 1")
    if roster_size < 1:
        raise ValueError("roster_size must be >= 1")

    profiles = _coerce_profiles(manager_profiles, n_managers=12)
    n_managers = len(profiles)
    pool = prepare_auction_pool(
        df_raw,
        use_model_values=use_model_values,
        n_teams=n_managers,
        roster_size=roster_size,
        budget=budget,
        min_bid=min_bid,
        dollar_one_players=dollar_one_players,
        category_weights=category_weights,
        star_exponent=star_exponent,
    )
    if len(pool) < n_managers * roster_size:
        raise ValueError("player pool is too small for the requested managers and roster size")

    rng = np.random.default_rng(rng_seed)
    sales_rows: List[Dict[str, Any]] = []
    sale_prices: Dict[str, List[float]] = {str(p): [] for p in pool["Player"]}
    buyer_counts: Dict[str, Dict[str, int]] = {str(p): {} for p in pool["Player"]}

    for sim in range(n_simulations):
        heat = float(np.clip(rng.normal(0.0, 0.08), -0.15, 0.25))
        rows = _simulate_one_auction(
            pool, profiles, budget, roster_size, max_centers, min_bid, bid_increment, rng, sim, heat,
        )
        for row in rows:
            player = str(row["player"])
            price = float(row["price"])
            sale_prices[player].append(price)
            archetype = str(row["buyer_archetype"])
            buyer_counts[player][archetype] = buyer_counts[player].get(archetype, 0) + 1
        if return_sales:
            sales_rows.extend(rows)

    summary_rows: List[Dict[str, Any]] = []
    for _, row in pool.iterrows():
        player = str(row["Player"])
        prices = np.array(sale_prices[player], dtype=float)
        buyer_hist = buyer_counts[player]
        likely_buyer = max(buyer_hist.items(), key=lambda kv: kv[1])[0] if buyer_hist else None
        summary_rows.append({
            "player": player,
            "position": row.get("POS"),
            "base_price": float(row["Value"]),
            "base_value": float(row["Value"]),
            "external_price": _nullable_float(row.get("external_price")),
            "external_value": _nullable_float(row.get("external_value")),
            "model_value": float(row["Value"]),
            "value_score": _nullable_float(row.get("value_score")),
            "replacement_adjusted_score": _nullable_float(row.get("replacement_adjusted_score")),
            "sale_probability": float(len(prices) / n_simulations),
            "avg_price": _nan_if_empty(prices, np.mean),
            "median_price": _nan_if_empty(prices, np.median),
            "p10_price": _nan_if_empty(prices, lambda x: np.quantile(x, 0.10)),
            "p90_price": _nan_if_empty(prices, lambda x: np.quantile(x, 0.90)),
            "max_price": _nan_if_empty(prices, np.max),
            "min_price": _nan_if_empty(prices, np.min),
            "likely_buyer_archetype": likely_buyer,
        })

    summary = pd.DataFrame(summary_rows).sort_values(
        ["sale_probability", "avg_price", "model_value"], ascending=[False, False, False]
    ).reset_index(drop=True)
    sales = pd.DataFrame(sales_rows) if return_sales else None
    return summary, sales


def _simulate_one_auction(
    pool: pd.DataFrame,
    profiles: Sequence[ManagerProfile],
    budget: float,
    roster_size: int,
    max_centers: int,
    min_bid: float,
    bid_increment: float,
    rng: np.random.Generator,
    simulation_id: int,
    heat: float,
) -> List[Dict[str, Any]]:
    n = len(pool)
    available = np.ones(n, dtype=bool)
    teams = [
        _TeamState(
            profile=p,
            budget_left=float(budget),
            category_totals={cat: 0.0 for cat in CATEGORIES},
            category_score_totals={cat: 0.0 for cat in CATEGORIES},
        )
        for p in profiles
    ]
    total_slots = len(teams) * roster_size
    sales: List[Dict[str, Any]] = []
    nominator_cursor = int(rng.integers(0, len(teams)))

    while len(sales) < total_slots and available.any():
        active = [i for i, t in enumerate(teams) if len(t.roster) < roster_size]
        if not active:
            break
        nominator_idx = active[nominator_cursor % len(active)]
        nominator_cursor += 1

        progress = len(sales) / max(total_slots, 1)
        room_state = _room_state(pool, available, teams, budget, roster_size, max_centers, min_bid, bid_increment, progress, heat)
        nomination = _choose_nomination(pool, available, teams[nominator_idx], room_state, rng)
        if nomination is None:
            available[np.nonzero(available)[0][0]] = False
            continue

        bidders: List[Tuple[int, float]] = []
        for idx, team in enumerate(teams):
            ceiling = _manager_bid_ceiling(pool.iloc[nomination], team, room_state, rng)
            if ceiling >= min_bid:
                bidders.append((idx, ceiling))

        available[nomination] = False
        if not bidders:
            continue

        bidders.sort(key=lambda kv: kv[1], reverse=True)
        winner_idx, winner_max = bidders[0]
        second_max = bidders[1][1] if len(bidders) > 1 else 0.0
        winner = teams[winner_idx]
        max_allowed = _max_allowed_bid(winner, roster_size, min_bid)
        price = min(winner_max, max_allowed, max(min_bid, second_max + bid_increment))
        if price < min_bid:
            continue

        _assign_player(pool.iloc[nomination], nomination, winner, price)
        sales.append({
            "simulation": simulation_id,
            "pick": len(sales) + 1,
            "player": str(pool.at[nomination, "Player"]),
            "price": float(round(price, 2)),
            "buyer_id": winner.profile.manager_id,
            "buyer_label": winner.profile.label,
            "buyer_archetype": winner.profile.archetype,
            "base_price": float(pool.at[nomination, "Value"]),
            "external_price": _nullable_float(pool.at[nomination, "external_price"]),
            "room_inflation": float(round(room_state.inflation, 4)),
        })

    return sales


def _room_state(
    pool: pd.DataFrame,
    available: np.ndarray,
    teams: Sequence[_TeamState],
    budget: float,
    roster_size: int,
    max_centers: int,
    min_bid: float,
    bid_increment: float,
    progress: float,
    heat: float,
) -> _RoomState:
    money_left = sum(t.budget_left for t in teams)
    open_slots = sum(roster_size - len(t.roster) for t in teams)
    reserve = open_slots * min_bid
    projected_room_cost = float(pool.loc[available, "Value"].nlargest(open_slots).sum()) if open_slots else 0.0
    fair_room_cost = max(projected_room_cost, reserve, 1.0)
    inflation = float(np.clip((money_left - reserve) / fair_room_cost, 0.65, 1.50))

    scarcity: Dict[str, float] = {}
    for cat in CATEGORIES:
        col = f"{cat}_score"
        if col not in pool.columns:
            scarcity[cat] = 0.0
            continue
        top_left = int((pool.loc[available, col] > 0.75).sum())
        scarcity[cat] = float(1.0 / np.sqrt(max(top_left, 1)))

    return _RoomState(progress, inflation, heat, scarcity, min_bid, bid_increment, roster_size, max_centers)


def _choose_nomination(
    pool: pd.DataFrame,
    available: np.ndarray,
    team: _TeamState,
    room: _RoomState,
    rng: np.random.Generator,
) -> Optional[int]:
    candidates = np.nonzero(available)[0]
    candidates = np.array([idx for idx in candidates if _can_roster(pool.iloc[idx], team, room)])
    if candidates.size == 0:
        return None

    profile = team.profile
    scores = []
    for idx in candidates:
        row = pool.iloc[idx]
        category_fit = _need_adjusted_category_fit(row, team)
        score = (
            0.55 * float(row["star_score"])
            + 0.30 * category_fit
            + 0.20 * float(row["mid_tier_score"])
            + profile.nomination_star_bias * float(row["star_score"])
            + rng.normal(0.0, 0.25)
        )
        scores.append(score)
    probs = target_mc._softmax(np.array(scores, dtype=float), alpha=3.5)
    return int(rng.choice(candidates, p=probs))


def _manager_bid_ceiling(
    row: pd.Series,
    team: _TeamState,
    room: _RoomState,
    rng: np.random.Generator,
) -> float:
    if not _can_roster(row, team, room):
        return 0.0

    profile = team.profile
    base = max(float(row["Value"]), room.min_bid)
    category_fit = _need_adjusted_category_fit(row, team)
    need = profile.need_reactivity * category_fit
    scarcity = sum(
        float(profile.category_weights.get(cat, 0.0)) * float(room.scarcity.get(cat, 0.0))
        for cat in CATEGORIES
    )
    scarcity_adj = profile.scarcity_reactivity * scarcity
    star_adj = profile.star_bias * float(row["star_score"])
    mid_adj = profile.mid_tier_bias * float(row["mid_tier_score"])
    heat_adj = profile.early_heat * max(0.0, 1.0 - room.progress) + room.heat * max(0.0, 0.45 - room.progress)
    random_adj = rng.normal(0.0, profile.bid_noise)

    multiplier = profile.aggression * room.inflation * (1.0 + need + scarcity_adj + star_adj + mid_adj + heat_adj + random_adj)
    ceiling = base * max(0.25, multiplier)
    ceiling = min(ceiling, base * profile.value_discipline)
    max_allowed = _max_allowed_bid(team, room.roster_size, room.min_bid)
    ceiling = min(ceiling, max_allowed)
    if len(team.roster) < room.roster_size - 1:
        ceiling = min(ceiling, team.budget_left * profile.max_single_player_budget_pct)
    return float(max(0.0, ceiling))


def _category_fit(row: pd.Series, profile: ManagerProfile) -> float:
    total_weight = sum(abs(float(v)) for v in profile.category_weights.values()) or 1.0
    raw = 0.0
    for cat, weight in profile.category_weights.items():
        col = f"{cat}_score"
        if col in row:
            raw += float(weight) * float(row[col])
    return float(np.clip(raw / total_weight, -1.5, 1.5))


def _need_adjusted_category_fit(row: pd.Series, team: _TeamState) -> float:
    """Category fit that cools once a build has already banked that category."""
    profile = team.profile
    total_weight = sum(abs(float(v)) for v in profile.category_weights.values()) or 1.0
    raw = 0.0
    roster_count = max(len(team.roster), 1)
    for cat, weight in profile.category_weights.items():
        col = f"{cat}_score"
        if col not in row:
            continue
        player_score = float(row[col])
        roster_avg = float(team.category_score_totals.get(cat, 0.0)) / roster_count if team.roster else 0.0
        need_factor = float(np.clip(1.15 - (0.25 * roster_avg), 0.75, 1.45))
        raw += float(weight) * player_score * need_factor
    return float(np.clip(raw / total_weight, -1.5, 1.5))


def _assign_player(row: pd.Series, idx: int, team: _TeamState, price: float) -> None:
    team.roster.append(idx)
    team.budget_left -= price
    for cat, source in _COUNTING_SOURCE.items():
        team.category_totals[cat] += float(row[source])
        team.category_score_totals[cat] += float(row[f"{cat}_score"])
    team.category_totals["FG%"] += float(row["FG%"])
    team.category_totals["FT%"] += float(row["FT%"])
    team.category_score_totals["FG%"] += float(row["FG%_score"])
    team.category_score_totals["FT%"] += float(row["FT%_score"])
    if bool(row.get("is_C", False)):
        team.centers += 1


def _can_roster(row: pd.Series, team: _TeamState, room: _RoomState) -> bool:
    if len(team.roster) >= room.roster_size:
        return False
    if team.budget_left < room.min_bid:
        return False
    if bool(row.get("is_C", False)) and team.centers >= room.max_centers:
        return False
    return _max_allowed_bid(team, room.roster_size, room.min_bid) >= room.min_bid


def _max_allowed_bid(team: _TeamState, roster_size: int, min_bid: float) -> float:
    open_after_this = max(roster_size - len(team.roster) - 1, 0)
    return float(team.budget_left - open_after_this * min_bid)


def _coerce_profiles(
    raw_profiles: Optional[Sequence[ManagerProfile | Mapping[str, Any]]],
    *,
    n_managers: int,
) -> List[ManagerProfile]:
    if raw_profiles is None:
        return default_manager_profiles(n_managers)
    profiles: List[ManagerProfile] = []
    for idx, raw in enumerate(raw_profiles):
        profiles.append(raw if isinstance(raw, ManagerProfile) else ManagerProfile.from_mapping(raw, idx))
    if not profiles:
        raise ValueError("manager_profiles cannot be empty")
    return profiles


def _zscore(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    std = float(np.nanstd(values))
    if std <= 1e-9:
        return np.zeros_like(values, dtype=float)
    return (values - float(np.nanmean(values))) / std


def _percent_rank(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(len(values), dtype=float)
    return ranks / max(len(values) - 1, 1)


def _nan_if_empty(values: np.ndarray, fn) -> float:
    if values.size == 0:
        return float("nan")
    return float(fn(values))


def _nullable_float(value: object) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(out):
        return None
    return out
