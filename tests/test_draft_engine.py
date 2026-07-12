"""Unit tests for draft_engine — the O(1) health check + targeted re-solve loop
that makes the Draft Room's "never freeze" guarantee (spec §2 criterion 2/5)
actually cheap. Pure: a fake solve_fn stands in for the real optimizer."""
import re

import pytest

from backend.draft.engine import apply_pick, build_initial_snapshot, pick_fallback, plan_id_for, relax_plan, triage_player
from backend.draft.strategies import CATEGORIES, Plan, balanced_config, punt_config


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


def test_triage_relevant_when_player_is_an_unowned_target_in_an_alive_plan():
    cfg = balanced_config()
    snaps = build_initial_snapshot([_plan(cfg, ["jokic", "curry"])])
    result = triage_player("curry", snaps, owned_keys=frozenset(), value_lookup={"curry": 13.4})
    assert result.relevant is True
    assert result.reason == "in_plan"
    assert result.in_plans == (plan_id_for(cfg),)
    assert result.max_bid == 13  # rounded


def test_triage_ignores_broken_plans_and_already_owned_players():
    cfg_a = balanced_config()
    cfg_b = punt_config(["FT%"])
    snaps = build_initial_snapshot([_plan(cfg_a, ["curry"]), _plan(cfg_b, ["curry", "tatum"])])
    # Break plan A specifically (no feasible replacement) so it no longer
    # counts as a live target for "curry"; plan B is untouched.
    broken_a = apply_pick([snaps[0]], "curry", solve_fn=lambda cfg: None)
    snaps = broken_a + [snaps[1]]

    # Not in a live plan (A is broken) but not yet owned -> still flagged via
    # plan B, which does have curry.
    result = triage_player("curry", snaps, owned_keys=frozenset(), value_lookup={"curry": 13.0})
    assert result.in_plans == (plan_id_for(cfg_b),)

    # Now simulate curry already being on the user's own roster: even though
    # cfg_b's cached roster still lists them, they're not a "target" anymore.
    result_owned = triage_player("curry", snaps, owned_keys=frozenset({"curry"}), value_lookup={"curry": 13.0})
    assert result_owned.in_plans == ()


def test_triage_value_target_when_not_in_any_plan_but_high_value():
    cfg = balanced_config()
    snaps = build_initial_snapshot([_plan(cfg, ["jokic"])])
    result = triage_player(
        "sleeper_pick", snaps, owned_keys=frozenset(), value_lookup={"sleeper_pick": 9.0},
        value_target_keys=frozenset({"sleeper_pick"}),
    )
    assert result.relevant is True
    assert result.reason == "value_target"
    assert result.in_plans == ()
    assert result.max_bid == 9


def test_triage_safe_to_pass_when_neither():
    cfg = balanced_config()
    snaps = build_initial_snapshot([_plan(cfg, ["jokic"])])
    result = triage_player("nobody_cares", snaps, owned_keys=frozenset(), value_lookup={})
    assert result.relevant is False
    assert result.reason == "safe_to_pass"
    assert result.max_bid is None


def test_relax_picks_the_candidate_with_the_best_objective():
    cfg = balanced_config()  # all 9 categories constrained

    # Only dropping BLK is feasible; the rest stay infeasible (None). Its
    # score is what should come back.
    def solve_with_score(candidate_cfg):
        if "BLK" not in candidate_cfg.constrained_categories:
            return (["a", "b", "c"], 42.0)
        return None

    proposal = relax_plan(cfg, solve_with_score)
    assert proposal is not None
    assert proposal.dropped_category == "BLK"
    assert proposal.objective_score == 42.0
    assert proposal.roster == ("a", "b", "c")
    assert "BLK" not in proposal.config.constrained_categories
    assert "BLK" in proposal.config.punts


def test_relax_prefers_the_highest_scoring_feasible_candidate():
    cfg = balanced_config()
    scores = {"PTS": 10.0, "REB": 5.0, "AST": 99.0, "STL": 1.0}

    def solve_with_score(candidate_cfg):
        dropped = (set(cfg.constrained_categories) - set(candidate_cfg.constrained_categories)).pop()
        if dropped in scores:
            return ([dropped], scores[dropped])
        return None

    proposal = relax_plan(cfg, solve_with_score)
    assert proposal is not None
    assert proposal.dropped_category == "AST"  # highest score
    assert proposal.objective_score == 99.0


def test_relax_sweeps_every_category_when_needed():
    cfg = balanced_config()
    seen = []

    def solve_with_score(candidate_cfg):
        seen.append((set(cfg.constrained_categories) - set(candidate_cfg.constrained_categories)).pop())
        return None  # nothing feasible

    proposal = relax_plan(cfg, solve_with_score)
    assert proposal is None
    assert set(seen) == set(cfg.constrained_categories)  # every category was tried
    assert len(seen) == len(CATEGORIES)  # exactly the 9-category sweep the spec describes
