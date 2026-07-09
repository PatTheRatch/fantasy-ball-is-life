"""Unit tests for the draft plan strategy map + portfolio diversity logic.

These are pure (no cvxpy / pandas / ESPN) and run offline. They verify the
*mechanism* that makes saved plans diverse — the empirical "are the resulting
rosters distinct on real projections" check lives in the gated integration test.
"""
import pytest

from draft_strategies import (
    BALANCED,
    CATEGORIES,
    COUNTING_CATS,
    PUNT_MULTIPLE,
    PUNT_ONE,
    SPREAD_VALUE,
    STARS_AND_SCRUBS,
    STRATEGY_PERCENTILE_BANDS,
    Plan,
    PlanConfig,
    balanced_config,
    build_plan_configs,
    generate_portfolio,
    punt_config,
    spread_value_config,
    stars_and_scrubs_config,
)


def _in_band(shape, pct):
    lo, hi = STRATEGY_PERCENTILE_BANDS[shape]
    return lo <= pct <= hi


# --- individual strategy shapes -------------------------------------------------

def test_balanced_constrains_all_nine_categories():
    cfg = balanced_config()
    assert cfg.shape == BALANCED
    assert set(cfg.constrained_categories) == set(CATEGORIES)
    assert _in_band(BALANCED, cfg.percentile)


def test_punt_one_drops_exactly_the_punted_category():
    cfg = punt_config(["FT%"])
    assert cfg.shape == PUNT_ONE
    assert "FT%" not in cfg.constrained_categories
    assert len(cfg.constrained_categories) == len(CATEGORIES) - 1
    assert cfg.punts == ("FT%",)
    assert _in_band(PUNT_ONE, cfg.percentile)


def test_punt_multiple_drops_all_punted_categories():
    cfg = punt_config(["FG%", "TO"], stat_to_maximize="3PM")
    assert cfg.shape == PUNT_MULTIPLE
    assert "FG%" not in cfg.constrained_categories
    assert "TO" not in cfg.constrained_categories
    assert len(cfg.constrained_categories) == len(CATEGORIES) - 2
    assert _in_band(PUNT_MULTIPLE, cfg.percentile)


def test_stars_and_scrubs_is_top_heavy():
    stars = stars_and_scrubs_config()
    balanced = balanced_config()
    assert stars.shape == STARS_AND_SCRUBS
    assert _in_band(STARS_AND_SCRUBS, stars.percentile)
    # more required $1 fills than a balanced build (many cheap scrubs)
    assert stars.minimum_value_players > balanced.minimum_value_players


def test_spread_value_is_flat():
    spread = spread_value_config()
    balanced = balanced_config()
    assert spread.shape == SPREAD_VALUE
    assert _in_band(SPREAD_VALUE, spread.percentile)
    # fewer $1 fills than balanced (more mid-tier players), and it lifts the
    # single-top-player reliance
    assert spread.minimum_value_players < balanced.minimum_value_players
    assert spread.ban_top_price is True


# --- validation -----------------------------------------------------------------

def test_cannot_maximize_a_punted_category():
    with pytest.raises(ValueError):
        punt_config(["PTS"], stat_to_maximize="PTS")


def test_rejects_unknown_category():
    with pytest.raises(ValueError):
        punt_config(["POINTS"])


def test_objective_must_be_a_counting_category():
    with pytest.raises(ValueError):
        balanced_config(stat_to_maximize="FG%")


def test_to_optimizer_kwargs_shape():
    kwargs = punt_config(["BLK"], stat_to_maximize="AST").to_optimizer_kwargs()
    assert set(kwargs) == {
        "categories", "percentile", "minimum_value_players",
        "stat_to_maximize", "ban_top_price",
    }
    assert "BLK" not in kwargs["categories"]
    assert kwargs["stat_to_maximize"] == "AST"


# --- portfolio assembly ---------------------------------------------------------

def test_build_plan_configs_returns_ten_distinct_configs():
    configs = build_plan_configs(10)
    assert len(configs) == 10
    # every parameterization is unique
    keys = {
        (c.shape, c.constrained_categories, c.percentile,
         c.minimum_value_players, c.stat_to_maximize)
        for c in configs
    }
    assert len(keys) == 10


def test_build_plan_configs_every_config_is_valid():
    for c in build_plan_configs(10):
        assert c.constrained_categories, "constrained set must be non-empty"
        assert set(c.constrained_categories) <= set(CATEGORIES)
        assert c.stat_to_maximize in COUNTING_CATS
        # never maximize a category the plan is punting
        assert c.stat_to_maximize in c.constrained_categories


def test_build_plan_configs_covers_multiple_shapes():
    shapes = {c.shape for c in build_plan_configs(10)}
    # the portfolio must not be all one shape — that's the whole point
    assert {BALANCED, PUNT_ONE} <= shapes
    assert len(shapes) >= 4


def test_build_plan_configs_respects_smaller_n():
    assert len(build_plan_configs(3)) == 3


def test_build_plan_configs_rejects_zero():
    with pytest.raises(ValueError):
        build_plan_configs(0)


# --- diversity enforcement (generate_portfolio, with a fake solver) -------------

def _roster(*names):
    return list(names)


def test_generate_portfolio_keeps_distinct_rosters():
    configs = build_plan_configs(3)
    rosters = {
        configs[0].label: _roster(*[f"a{i}" for i in range(13)]),
        configs[1].label: _roster(*[f"b{i}" for i in range(13)]),
        configs[2].label: _roster(*[f"c{i}" for i in range(13)]),
    }
    plans = generate_portfolio(configs, lambda c: rosters[c.label])
    assert len(plans) == 3
    assert all(isinstance(p, Plan) for p in plans)


def test_generate_portfolio_drops_near_duplicate():
    configs = build_plan_configs(2)
    base = _roster(*[f"p{i}" for i in range(13)])
    # second shares 9 of 13 with the first -> exceeds max_shared=8 -> dropped
    near_dup = _roster(*[f"p{i}" for i in range(9)], "x9", "x10", "x11", "x12")
    rosters = {configs[0].label: base, configs[1].label: near_dup}
    plans = generate_portfolio(configs, lambda c: rosters[c.label], max_shared=8)
    assert len(plans) == 1


def test_generate_portfolio_keeps_at_exactly_max_shared():
    configs = build_plan_configs(2)
    base = _roster(*[f"p{i}" for i in range(13)])
    # shares exactly 8 -> not greater than max_shared -> kept
    boundary = _roster(*[f"p{i}" for i in range(8)], "y8", "y9", "y10", "y11", "y12")
    rosters = {configs[0].label: base, configs[1].label: boundary}
    plans = generate_portfolio(configs, lambda c: rosters[c.label], max_shared=8)
    assert len(plans) == 2


def test_generate_portfolio_skips_infeasible():
    configs = build_plan_configs(2)
    rosters = {
        configs[0].label: None,  # infeasible
        configs[1].label: _roster(*[f"q{i}" for i in range(13)]),
    }
    plans = generate_portfolio(configs, lambda c: rosters[c.label])
    assert len(plans) == 1
    assert plans[0].config.label == configs[1].label


def test_generate_portfolio_respects_limit():
    configs = build_plan_configs(10)
    plans = generate_portfolio(
        configs,
        lambda c: _roster(*[f"{c.label}-{i}" for i in range(13)]),
        limit=4,
    )
    assert len(plans) == 4


# --- user-facing knobs: target_categories, base_percentile, stat_to_maximize ---


def test_target_categories_excludes_a_category_from_every_generated_plan():
    # User wants to never compete in FT% at all -- it must not appear in any
    # plan's constrained_categories, and "Punt FT%" (redundant given the
    # exclusion) must not be generated.
    configs = build_plan_configs(10, target_categories=[c for c in CATEGORIES if c != "FT%"])
    for cfg in configs:
        assert "FT%" not in cfg.constrained_categories
        assert "FT%" not in cfg.punts  # a punt of an already-excluded cat is redundant, not generated


def test_target_categories_rejects_unknown_category():
    with pytest.raises(ValueError):
        build_plan_configs(5, target_categories=["PTS", "NOT_A_CATEGORY"])


def test_target_categories_rejects_empty_selection():
    with pytest.raises(ValueError):
        build_plan_configs(5, target_categories=[])


def test_stat_to_maximize_override_applies_to_every_plan():
    configs = build_plan_configs(10, stat_to_maximize="STL")
    assert configs  # sanity: still produced plans
    assert all(cfg.stat_to_maximize == "STL" for cfg in configs)


def test_stat_to_maximize_must_be_within_target_categories():
    with pytest.raises(ValueError):
        build_plan_configs(5, target_categories=["REB", "AST"], stat_to_maximize="PTS")


def test_stat_to_maximize_must_be_a_counting_category():
    with pytest.raises(ValueError):
        build_plan_configs(5, stat_to_maximize="FG%")


def test_base_percentile_recenters_every_shape_while_preserving_order():
    low = {c.shape: c.percentile for c in build_plan_configs(10, base_percentile=0.55)}
    high = {c.shape: c.percentile for c in build_plan_configs(10, base_percentile=0.85)}
    # Every shape actually moved with the base.
    for shape in low:
        assert high[shape] > low[shape]
    # Relative aggressiveness across shapes is preserved at both levels: a
    # punt build still asks for more than balanced; stars & scrubs still less.
    for percentiles in (low, high):
        assert percentiles[PUNT_ONE] > percentiles[BALANCED]
        assert percentiles[STARS_AND_SCRUBS] < percentiles[BALANCED]


def test_base_percentile_is_clamped_to_valid_range():
    configs = build_plan_configs(10, base_percentile=0.99)
    assert all(0.50 <= c.percentile <= 0.95 for c in configs)
    configs = build_plan_configs(10, base_percentile=0.01)
    assert all(0.50 <= c.percentile <= 0.95 for c in configs)


def test_stat_to_maximize_override_skips_punt_entries_that_would_punt_it():
    # AST is punted by one of the default recipe's punt entries. Forcing
    # stat_to_maximize="AST" must silently skip that one entry (invalid: can't
    # maximize what you're punting) rather than let it fall through to
    # punt_config() and raise.
    configs = build_plan_configs(10, stat_to_maximize="AST")
    for cfg in configs:
        assert "AST" not in cfg.punts


def test_no_overrides_matches_unrestricted_default_behavior():
    # None/None/None must be byte-identical to the pre-existing call shape,
    # so this is a strictly additive change for every current caller.
    assert build_plan_configs(10) == build_plan_configs(10, None, None, None)
