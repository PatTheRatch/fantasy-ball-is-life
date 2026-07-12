import numpy as np
import pandas as pd
import pytest

from backend.draft import values as player_values


def make_value_pool(n=30):
    rows = []
    for i in range(n):
        rows.append({
            "Player": f"Player{i}",
            "POS": ["PG", "SG", "SF", "PF", "C", "PG/SG"][i % 6],
            "Price": 1 if i == 0 else max(1, 30 - i),
            "Value": 1 if i == 0 else max(1, 30 - i),
            "PTS_PG": 45 if i == 0 else max(4, 24 - (i * 0.5)),
            "REB_PG": 14 if i == 0 else max(2, 11 - (i * 0.25)),
            "AST_PG": 8 if i == 0 else max(1, 8 - (i * 0.2)),
            "STL_PG": 2.0 if i == 0 else max(0.2, 1.8 - (i * 0.04)),
            "BLK_PG": 4.2 if i == 0 else max(0.1, 1.6 - (i * 0.05)),
            "3PM_PG": 3.0 if i == 0 else max(0.1, 3.2 - (i * 0.08)),
            "TO_PG": -2.0 if i == 0 else -max(0.5, 4.5 - (i * 0.08)),
            "FGM_PG": 12 if i == 0 else max(2, 9 - (i * 0.15)),
            "FGA_PG": 20 if i == 0 else max(5, 18 - (i * 0.2)),
            "FTM_PG": 6 if i == 0 else max(1, 6 - (i * 0.1)),
            "FTA_PG": 7 if i == 0 else max(2, 7 - (i * 0.1)),
        })
    return pd.DataFrame(rows)


def test_model_value_ignores_garbage_external_price_for_elite_player():
    out = player_values.calculate_player_values(
        make_value_pool(),
        n_teams=3,
        roster_size=5,
        budget=100,
        dollar_one_players=3,
        star_exponent=1.15,
    )

    elite = out[out["Player"] == "Player0"].iloc[0]
    assert elite["external_price"] == 1
    assert elite["model_value"] > 1
    assert elite["value_rank"] == 1


def test_top_drafted_values_approximately_conserve_budget():
    n_teams = 3
    roster_size = 5
    budget = 100
    out = player_values.calculate_player_values(
        make_value_pool(),
        n_teams=n_teams,
        roster_size=roster_size,
        budget=budget,
        dollar_one_players=4,
    )

    drafted = out.sort_values("value_score", ascending=False).head(n_teams * roster_size)
    assert drafted["model_value"].sum() == pytest.approx(n_teams * budget, abs=0.5)


def test_dollar_one_players_controls_replacement_tier_size():
    out = player_values.calculate_player_values(
        make_value_pool(),
        n_teams=3,
        roster_size=5,
        budget=100,
        dollar_one_players=5,
    )

    drafted = out.sort_values("value_score", ascending=False).head(15)
    assert int((drafted["model_value"] == 1).sum()) >= 5


def test_star_exponent_concentrates_more_value_at_the_top():
    pool = make_value_pool()
    flat = player_values.calculate_player_values(
        pool, n_teams=3, roster_size=5, budget=100, dollar_one_players=4, star_exponent=1.0,
    )
    concentrated = player_values.calculate_player_values(
        pool, n_teams=3, roster_size=5, budget=100, dollar_one_players=4, star_exponent=1.35,
    )

    flat_top = float(flat.sort_values("model_value", ascending=False).iloc[0]["model_value"])
    concentrated_top = float(concentrated.sort_values("model_value", ascending=False).iloc[0]["model_value"])
    assert concentrated_top > flat_top


def test_rejects_unknown_category_weight():
    with pytest.raises(ValueError):
        player_values.calculate_player_values(make_value_pool(), category_weights={"POINTS": 1.0})
