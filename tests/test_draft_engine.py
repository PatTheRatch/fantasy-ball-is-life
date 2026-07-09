"""Unit tests for draft_engine — the O(1) health check + targeted re-solve loop
that makes the Draft Room's "never freeze" guarantee (spec §2 criterion 2/5)
actually cheap. Pure: a fake solve_fn stands in for the real optimizer."""
import re

import pytest

from draft_engine import apply_pick, build_initial_snapshot, pick_fallback, plan_id_for
from draft_strategies import Plan, balanced_config, punt_config


def _plan(config, roster):
    return Plan(config=config, roster=list(roster))


def test_build_initial_snapshot_starts_all_alive():
    cfg_a = balanced_config()
    cfg_b = punt_config(["FT%"])
    snaps = build_initial_snapshot([_plan(cfg_a, ["jokic", "curry"]), _plan(cfg_b, ["tatum", "brown"])])
    assert [s.health for s in snaps] == ["alive", "alive"]
    assert snaps[0].plan_id == plan_id_for(cfg_a)
    assert snaps[1].roster == ("tatum", "brown")


def test_apply_pick_leaves_unaffected_plans_untouched_and_uncalled():
    cfg_a = balanced_config()
    cfg_b = punt_config(["FT%"])
    snaps = build_initial_snapshot([_plan(cfg_a, ["jokic", "curry"]), _plan(cfg_b, ["tatum", "brown"])])

    calls = []

    def solve_fn(cfg):
        calls.append(cfg.label)
        return ["should", "not", "be", "used"]

    # "durant" is in neither plan's roster -> both plans are unaffected, and the
    # solver must not be invoked at all (the O(1)-then-targeted-resolve promise).
    updated = apply_pick(snaps, "durant", solve_fn)
    assert calls == []
    assert updated == snaps


def test_apply_pick_resolves_only_the_broken_plan():
    cfg_a = balanced_config()
    cfg_b = punt_config(["FT%"])
    snaps = build_initial_snapshot([_plan(cfg_a, ["jokic", "curry"]), _plan(cfg_b, ["tatum", "brown"])])

    calls = []

    def solve_fn(cfg):
        calls.append(cfg.label)
        return ["jokic", "new_guy"]  # replacement roster for the broken plan

    updated = apply_pick(snaps, "curry", solve_fn)
    assert calls == [cfg_a.label]  # only the plan that had curry was re-solved
    a, b = updated
    assert a.health == "alive"
    assert a.roster == ("jokic", "new_guy")
    assert b == snaps[1]  # plan B untouched


def test_apply_pick_marks_plan_broken_when_no_replacement_is_feasible():
    cfg_a = balanced_config()
    snaps = build_initial_snapshot([_plan(cfg_a, ["jokic", "curry"])])

    updated = apply_pick(snaps, "curry", solve_fn=lambda cfg: None)
    assert updated[0].health == "broken"
    assert "curry" in updated[0].health_reason
    assert updated[0].roster == ()


def test_pick_fallback_returns_first_alive_plan_in_order():
    cfg_a = balanced_config()
    cfg_b = punt_config(["FT%"])
    cfg_c = punt_config(["BLK"])
    snaps = build_initial_snapshot([_plan(cfg_a, ["a"]), _plan(cfg_b, ["b"]), _plan(cfg_c, ["c"])])
    # Break plan A only.
    snaps = apply_pick(snaps, "a", solve_fn=lambda cfg: None)

    fallback = pick_fallback(snaps)
    assert fallback is not None
    assert fallback.plan_id == plan_id_for(cfg_b)  # first still-alive plan


def test_pick_fallback_is_none_when_every_plan_is_broken():
    cfg_a = balanced_config()
    snaps = build_initial_snapshot([_plan(cfg_a, ["a"])])
    snaps = apply_pick(snaps, "a", solve_fn=lambda cfg: None)

    assert pick_fallback(snaps) is None  # this is exactly when §4's relax path kicks in


def test_plan_id_is_a_clean_deterministic_slug():
    cfg = punt_config(["FG%", "TO"])
    plan_id = plan_id_for(cfg)
    assert plan_id == "punt_fg_and_to"
    assert plan_id == plan_id_for(cfg)  # deterministic across calls
    assert re.fullmatch(r"[a-z0-9_]+", plan_id)  # safe as a JSON key / future URL segment
