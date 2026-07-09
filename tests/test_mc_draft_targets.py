"""Tests for the Monte Carlo draft-target engine (draft_targets_mc).

Engine-level only: these build a synthetic player pool and never touch ESPN or
cvxpy, so they run anywhere numpy/pandas are installed. The optimizer wiring
(OptimizeLineup.set_requirements dispatch) needs a live MyLeague and is exercised
in the ESPN-dependent integration suite.
"""
import numpy as np
import pandas as pd
import pytest

import draft_targets_mc as mc


def make_pool(n=120, seed=0):
    """Synthetic pool in the engine's canonical per-week columns. TO is negated
    to match the optimizer's internal 'higher is better' convention."""
    rng = np.random.default_rng(seed)
    positions = ["PG", "SG", "SF", "PF", "C", "PG/SG", "SF/PF", "PG/SF", "PF/C"]
    rows = []
    for i in range(n):
        rows.append({
            "Player": f"Player{i}",
            "POS": positions[i % len(positions)],
            "Price": float(rng.integers(1, 45)),
            "Value": float(abs(rng.normal(6, 3)) + 1),
            "PTS_PG": float(rng.uniform(10, 80)),
            "REB_PG": float(rng.uniform(3, 40)),
            "AST_PG": float(rng.uniform(2, 35)),
            "STL_PG": float(rng.uniform(1, 8)),
            "BLK_PG": float(rng.uniform(0, 8)),
            "3PM_PG": float(rng.uniform(0, 15)),
            "TO_PG": float(-rng.uniform(2, 12)),   # NEGATED
            "FGM_PG": float(rng.uniform(5, 35)),
            "FGA_PG": float(rng.uniform(10, 60)),
            "FTM_PG": float(rng.uniform(2, 20)),
            "FTA_PG": float(rng.uniform(3, 25)),
        })
    return pd.DataFrame(rows)


def run(pool, seed=7, n_teams=300):
    return mc.monte_carlo_drafts_13team_daily(
        pool, n_teams=n_teams, budget=200, avg_games_per_week=1.0, rng_seed=seed,
    )


# ---------------------------------------------------------------- helpers ----

def test_softmax_sums_to_one_and_handles_empty():
    probs = mc._softmax(np.array([1.0, 2.0, 3.0]), alpha=6.0)
    assert probs.shape == (3,)
    assert pytest.approx(probs.sum(), rel=1e-9) == 1.0
    assert np.all(probs >= 0)
    assert mc._softmax(np.array([]), alpha=6.0).size == 0


def test_normalize_columns_maps_bbm_style_aliases():
    raw = pd.DataFrame({
        "Name": ["A"], "Pos": ["PG"], "$": [10.0], "LeagV": [4.0],
        "p/g": [20.0], "r/g": [5.0], "a/g": [4.0], "s/g": [1.0], "b/g": [0.5],
        "3/g": [2.0], "to/g": [2.0], "fgm/g": [7.0], "fga/g": [15.0],
        "ftm/g": [4.0], "fta/g": [5.0],
    })
    out = mc.normalize_columns(raw)
    for col in ("Player", "Price", "Value", "PTS_PG", "REB_PG", "3PM_PG", "TO_PG", "FGA_PG"):
        assert col in out.columns


def test_eligibility_flags_parse_multi_position():
    df = pd.DataFrame({"POS": ["PG/SG", "C", "SF-PF".replace("-", "/"), "G", "F"]})
    out = mc.add_eligibility_flags(df)
    assert out.loc[0, "is_PG"] and out.loc[0, "is_SG"] and not out.loc[0, "is_C"]
    assert out.loc[1, "is_C"] and not out.loc[1, "is_PG"]
    assert out.loc[3, "is_PG"] and out.loc[3, "is_SG"]      # "G"
    assert out.loc[4, "is_SF"] and out.loc[4, "is_PF"]      # "F"


# ------------------------------------------------------------ simulation ----

def test_determinism_same_seed_identical():
    pool = make_pool()
    t1, fg1, ft1, _ = run(pool, seed=7)
    t2, fg2, ft2, _ = run(pool, seed=7)
    assert t1.equals(t2)
    assert fg1.equals(fg2) and ft1.equals(ft2)


def test_different_seed_differs():
    pool = make_pool()
    t1, *_ = run(pool, seed=7)
    t3, *_ = run(pool, seed=99)
    assert not t1.equals(t3)


def test_budget_and_center_caps_respected():
    pool = make_pool()
    _, _, _, meta = run(pool, seed=7)
    assert meta["spent"].max() <= 200 + 1e-6
    assert int(meta["centers"].max()) <= 3


def test_team_columns_present():
    pool = make_pool()
    teams_df, *_ = run(pool, seed=7)
    for col in ("PTS", "REB", "AST", "STL", "BLK", "3PM", "TO", "FGM", "FGA", "FTM", "FTA"):
        assert col in teams_df.columns
    assert len(teams_df) == 300


# --------------------------------------------------------------- targets ----

def test_targets_keys_and_percentage_ranges():
    pool = make_pool()
    teams_df, fg, ft, _ = run(pool, seed=7)
    tg = mc.mc_targets_from_percentile(teams_df, fg, ft, pct=0.80)
    for cat in ("PTS", "REB", "AST", "STL", "BLK", "3PM", "TO", "FG%", "FT%"):
        assert cat in tg
        assert np.isfinite(tg[cat])
    assert 0.0 <= tg["FG%"] <= 1.0
    assert 0.0 <= tg["FT%"] <= 1.0


def test_percentile_is_more_ambitious_for_counting_stats():
    pool = make_pool()
    teams_df, fg, ft, _ = run(pool, seed=7)
    p80 = mc.mc_targets_from_percentile(teams_df, fg, ft, pct=0.80)
    p50 = mc.mc_targets_from_percentile(teams_df, fg, ft, pct=0.50)
    assert p80["PTS"] >= p50["PTS"]


def test_to_negated_convention_higher_is_better():
    """With TO negated, the higher (p80) target must mean *fewer* turnovers,
    i.e. p80 TO >= p50 TO (less negative). Guards Aisha's TO sign flag."""
    pool = make_pool()
    teams_df, fg, ft, _ = run(pool, seed=7)
    p80 = mc.mc_targets_from_percentile(teams_df, fg, ft, pct=0.80)
    p50 = mc.mc_targets_from_percentile(teams_df, fg, ft, pct=0.50)
    assert p80["TO"] < 0            # stays in negated convention
    assert p80["TO"] >= p50["TO"]   # ambitious = fewer turnovers


# --------------------------------------------------------------- failure ----

def test_missing_required_columns_raises_keyerror():
    pool = make_pool().drop(columns=["FTA_PG"])
    with pytest.raises(KeyError):
        run(pool, seed=7)


def test_infeasible_pool_raises_runtimeerror():
    """A pool that can't field a legal 13-man team under budget must fail loudly,
    not return garbage. Here: far too few players for 13 slots."""
    pool = make_pool(n=4)
    with pytest.raises((RuntimeError, KeyError, ValueError)):
        run(pool, seed=7, n_teams=50)
