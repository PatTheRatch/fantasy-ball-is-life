import numpy as np
import pandas as pd
import pytest

from backend.draft import auction_sim as auction


def make_pool(n=36, seed=0):
    rng = np.random.default_rng(seed)
    positions = ["PG", "SG", "SF", "PF", "C", "PG/SG", "SF/PF", "PF/C"]
    rows = []
    for i in range(n):
        is_big = i % 6 in (3, 4)
        is_guard = i % 6 in (0, 1)
        rows.append({
            "Player": f"Player{i}",
            "POS": positions[i % len(positions)],
            "Price": float(max(1, 40 - i + rng.integers(-3, 4))),
            "Value": float(max(1, 39 - i + rng.integers(-2, 5))),
            "PTS_PG": float(12 + rng.uniform(0, 18) + (8 if is_guard else 0)),
            "REB_PG": float(3 + rng.uniform(0, 8) + (8 if is_big else 0)),
            "AST_PG": float(2 + rng.uniform(0, 7) + (5 if is_guard else 0)),
            "STL_PG": float(0.4 + rng.uniform(0, 2)),
            "BLK_PG": float(0.1 + rng.uniform(0, 2) + (2.5 if is_big else 0)),
            "3PM_PG": float(0.2 + rng.uniform(0, 4) + (2 if is_guard else 0)),
            "TO_PG": float(-rng.uniform(1, 4)),
            "FGM_PG": float(4 + rng.uniform(0, 6)),
            "FGA_PG": float(8 + rng.uniform(0, 10)),
            "FTM_PG": float(1 + rng.uniform(0, 6)),
            "FTA_PG": float(2 + rng.uniform(0, 7)),
        })
    return pd.DataFrame(rows)


def test_prepare_auction_pool_adds_scores_and_eligibility():
    pool = auction.prepare_auction_pool(make_pool(), n_teams=4, roster_size=3)
    for col in (
        "Player", "Price", "Value", "model_value", "external_price",
        "is_PG", "is_C", "PTS_score", "REB_score", "FG%_score",
    ):
        assert col in pool.columns
    assert pool["star_score"].between(0, 1).all()
    assert (pool["model_value"] >= 1).all()


def test_simulation_is_deterministic_for_same_seed():
    pool = make_pool()
    profiles = auction.default_manager_profiles(6)

    s1, sales1 = auction.simulate_auction_prices(
        pool, manager_profiles=profiles, n_simulations=20, roster_size=3, rng_seed=11, return_sales=True,
    )
    s2, sales2 = auction.simulate_auction_prices(
        pool, manager_profiles=profiles, n_simulations=20, roster_size=3, rng_seed=11, return_sales=True,
    )

    assert s1.equals(s2)
    assert sales1.equals(sales2)


def test_summary_contract_contains_price_distribution_columns():
    summary, sales = auction.simulate_auction_prices(
        make_pool(), n_simulations=15, roster_size=2, rng_seed=4, return_sales=True,
    )

    expected = {
        "player", "position", "base_price", "external_price", "model_value",
        "sale_probability", "avg_price", "median_price", "p10_price",
        "p90_price", "likely_buyer_archetype",
    }
    assert expected <= set(summary.columns)
    assert len(summary) == 36
    assert sales is not None
    assert {"simulation", "pick", "player", "price", "buyer_archetype"} <= set(sales.columns)
    assert summary["sale_probability"].between(0, 1).all()


def test_category_build_profiles_change_likely_buyers():
    pool = pd.DataFrame([
        {
            "Player": "Block Center", "POS": "C", "Price": 22, "Value": 22,
            "PTS_PG": 13, "REB_PG": 15, "AST_PG": 1, "STL_PG": 0.5, "BLK_PG": 3.2,
            "3PM_PG": 0.1, "TO_PG": -2.0, "FGM_PG": 6, "FGA_PG": 10, "FTM_PG": 2, "FTA_PG": 4,
        },
        {
            "Player": "Three Guard", "POS": "PG", "Price": 22, "Value": 22,
            "PTS_PG": 24, "REB_PG": 3, "AST_PG": 8, "STL_PG": 1.1, "BLK_PG": 0.2,
            "3PM_PG": 4.5, "TO_PG": -2.8, "FGM_PG": 8, "FGA_PG": 18, "FTM_PG": 4, "FTA_PG": 5,
        },
    ])
    for i in range(20):
        pool.loc[len(pool)] = {
            "Player": f"Filler{i}", "POS": ["PG", "SG", "SF", "PF", "C"][i % 5],
            "Price": 2, "Value": 2, "PTS_PG": 5, "REB_PG": 3, "AST_PG": 1,
            "STL_PG": 0.3, "BLK_PG": 0.2, "3PM_PG": 0.5, "TO_PG": -1,
            "FGM_PG": 2, "FGA_PG": 5, "FTM_PG": 1, "FTA_PG": 2,
        }

    profiles = [
        auction.ManagerProfile(
            "big", "Bigs", "big_man_build",
            {"REB": 1.3, "BLK": 1.4, "FG%": 0.5},
            aggression=1.15, value_discipline=1.35, need_reactivity=0.7,
            bid_noise=0.01, max_single_player_budget_pct=0.8,
        ),
        auction.ManagerProfile(
            "guard", "Guards", "guard_stats_build",
            {"PTS": 0.9, "3PM": 1.4, "AST": 1.3, "FT%": 0.5},
            aggression=1.15, value_discipline=1.35, need_reactivity=0.7,
            bid_noise=0.01, max_single_player_budget_pct=0.8,
        ),
    ]

    _, sales = auction.simulate_auction_prices(
        pool, manager_profiles=profiles, n_simulations=40, roster_size=2, rng_seed=8,
        dollar_one_players=0, return_sales=True,
    )

    featured = sales[sales["player"].isin(["Block Center", "Three Guard"])]
    buyers = featured.groupby("player")["buyer_archetype"].agg(lambda s: s.value_counts().idxmax()).to_dict()
    assert buyers["Block Center"] == "big_man_build"
    assert buyers["Three Guard"] == "guard_stats_build"


def test_model_value_can_override_bad_external_price():
    pool = make_pool()
    pool.loc[0, "Price"] = 1
    pool.loc[0, "Value"] = 1
    pool.loc[0, ["PTS_PG", "REB_PG", "AST_PG", "STL_PG", "BLK_PG", "3PM_PG"]] = [42, 16, 8, 2.5, 4.0, 3.5]
    prepared = auction.prepare_auction_pool(pool, n_teams=4, roster_size=4, dollar_one_players=4)

    elite = prepared.loc[prepared["Player"] == "Player0"].iloc[0]
    assert elite["external_price"] == 1
    assert elite["model_value"] > 1
    assert elite["Value"] == elite["model_value"]


def test_rejects_too_small_pool():
    with pytest.raises(ValueError):
        auction.simulate_auction_prices(make_pool(n=4), n_simulations=1, roster_size=2)
