"""End-to-end integration test for POST /draft/plans, POST /draft/pick,
POST /draft/triage, and POST /draft/relax, through the real FastAPI app +
real optimizer + real BBM projections.

Same isolation pattern as tests/test_plan_diversity_integration.py: ESPN is
stubbed (a fake empty-draft league) so this runs without network access, and
`set_requirements` is consequently skipped inside the stubbed solve path in
api.py's own error handling is NOT bypassed here — we're driving the actual
production code path (api.draft_plans / api.draft_pick), not a copy of it.

Skips cleanly when the engine deps or the projections file aren't available.
"""
import os

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("fastapi")
ol = pytest.importorskip("optimize_lineup")

try:
    from config import BBM_PROJECTIONS_PATH
except Exception:  # pragma: no cover
    BBM_PROJECTIONS_PATH = "player_rankings/BBM_Projections.xls"

pytestmark = pytest.mark.integration

_HAS_PROJECTIONS = os.path.exists(BBM_PROJECTIONS_PATH)


class _FakeLeague:
    """Stands in for the live ESPN league so OptimizeLineup constructs offline.
    Real `set_requirements` calls (which need get_universe_wins/ESPN history)
    are monkeypatched to a no-op below, mirroring the existing integration
    test's isolation boundary."""

    def __init__(self, *args, **kwargs):
        self.draft = []
        self.stat_categories = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_draft_plans_then_pick_round_trip(monkeypatch):
    import api

    monkeypatch.setattr(ol, "MyLeague", _FakeLeague)
    # set_requirements needs live ESPN history; stub it to a no-op so the
    # solve proceeds unconstrained by category targets (same lower-bound
    # caveat as test_plan_diversity_integration.py — real category targets
    # would only *increase* diversity, not create false passes here).
    monkeypatch.setattr(ol.OptimizeLineup, "set_requirements", lambda self, cats, percentile=0.75: None)

    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.post("/draft/plans", json={"n_plans": 6, "picks": []})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert len(data["plans"]) >= 2, "expected a genuinely diverse portfolio, not 0-1 survivors"
    assert all(p["health"] == "alive" for p in data["plans"])
    assert data["fallback_next"] is not None
    assert len(data["value_board"]) > 0
    # criterion 2: the recommendation surface is never empty, and it names an
    # actual player + bid, not just a plan id.
    assert data["fallback_next"]["plan_id"] in {p["plan_id"] for p in data["plans"]}
    assert data["fallback_next"]["player_key"]
    assert data["fallback_next"]["max_bid"] > 0

    # Every alive plan with an unowned player must carry a next_target with a
    # positive max_bid (the thing the "on the block" UI reads).
    for p in data["plans"]:
        if p["roster"]:
            assert p["next_target"] is not None
            assert p["next_target"]["max_bid"] > 0

    # D5 (spec §0): every roster row must carry the full per-player data —
    # $ value, position, and all 9 category contributions — not just a bare
    # name. `players` is the enriched parallel to the bare `roster` list.
    first_alive = next(p for p in data["plans"] if p["roster"])
    assert len(first_alive["players"]) == len(first_alive["roster"])
    sample_player = first_alive["players"][0]
    for field in ("player_key", "pos", "team", "value", "pts", "reb", "ast", "stl", "blk", "tpm", "fg_pct", "ft_pct", "to"):
        assert field in sample_player, f"missing {field} on roster row"
    assert sample_player["pos"]
    assert sample_player["to"] >= 0  # re-negated back to a normal positive display value

    # Value board entries carry the same enrichment (used for the rail's
    # best-available list, not just plan rosters).
    vb_entry = data["value_board"][0]
    assert vb_entry["pos"]
    assert vb_entry["value"] > 0

    # --- log a pick: draft away the first plan's next_target and confirm the
    # server does a *targeted* recompute, not a blind full re-solve ---
    target_plan = data["plans"][0]
    sniped = target_plan["next_target"]["player_key"]

    pick_resp = client.post(
        "/draft/pick",
        json={
            "n_plans": 6,
            "picks": [{"player_key": sniped, "price": 10, "team_id": "rival_1", "is_user": False}],
            "new_pick": {"player_key": sniped, "price": 10, "team_id": "rival_1", "is_user": False},
            "prior_plans": data["plans"],
        },
    )
    assert pick_resp.status_code == 200, pick_resp.text
    updated = pick_resp.json()

    # The sniped plan must no longer offer the drafted player as its target.
    updated_target_plan = next(p for p in updated["plans"] if p["plan_id"] == target_plan["plan_id"])
    if updated_target_plan["next_target"] is not None:
        assert updated_target_plan["next_target"]["player_key"] != sniped
    assert sniped not in updated_target_plan["roster"]

    # Plans that never had the sniped player must be byte-for-byte untouched
    # (the O(1) health check, not a full re-solve of everything).
    for prior_p, new_p in zip(data["plans"], updated["plans"]):
        if sniped not in prior_p["roster"]:
            assert prior_p == new_p

    # criterion 2 still holds after a pick lands, and the sniped player is off
    # the value board (drafted-by-anyone is excluded from the floor too).
    assert updated["fallback_next"] is not None
    assert sniped not in {pl["player_key"] for pl in updated["value_board"]}

    # --- triage: someone new gets nominated ---
    # A player who's still a live target in some plan -> Relevant.
    still_wanted = next(
        p for p in updated["plans"]
        if p["health"] == "alive" and p["next_target"]
    )["next_target"]["player_key"]
    triage_relevant = client.post(
        "/draft/triage",
        json={"n_plans": 6, "picks": [], "prior_plans": updated["plans"], "player_key": still_wanted},
    )
    assert triage_relevant.status_code == 200, triage_relevant.text
    t = triage_relevant.json()
    assert t["relevant"] is True
    assert t["reason"] == "in_plan"
    assert len(t["in_plans"]) > 0
    assert t["max_bid"] > 0

    # A name that's in no plan and not on the value board -> Safe to pass.
    triage_pass = client.post(
        "/draft/triage",
        json={
            "n_plans": 6,
            "picks": [],
            "prior_plans": updated["plans"],
            "player_key": "definitely_not_a_real_player_xyz",
        },
    )
    assert triage_pass.status_code == 200, triage_pass.text
    p = triage_pass.json()
    assert p["relevant"] is False
    assert p["reason"] == "safe_to_pass"
    assert p["max_bid"] is None


_ALL_CATS = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]


def _synthetic_plan(plan_id="balanced", health="broken", roster=None):
    """A hand-built plan snapshot in the API's public shape. /draft/relax only
    needs *a* Broken plan's config to sweep from -- driving a real draft down
    to genuine infeasibility would mean logging dozens of picks, so this
    exercises the endpoint (and the real solver underneath it) against a
    plan that's *declared* broken rather than one that got there organically."""
    return {
        "plan_id": plan_id,
        "label": "Balanced",
        "shape": "balanced",
        "config": {
            "label": "Balanced",
            "shape": "balanced",
            "constrained_categories": _ALL_CATS,
            "percentile": 0.70,
            "minimum_value_players": 3,
            "stat_to_maximize": "PTS",
            "ban_top_price": False,
            "punts": [],
        },
        "roster": roster or [],
        "health": health,
        "health_reason": "synthetic: forced for this test" if health == "broken" else None,
        "next_target": None,
    }


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_draft_relax_runs_the_sweep_and_returns_a_feasible_proposal(monkeypatch):
    import api

    monkeypatch.setattr(ol, "MyLeague", _FakeLeague)
    monkeypatch.setattr(ol.OptimizeLineup, "set_requirements", lambda self, cats, percentile=0.75: None)

    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.post("/draft/relax", json={"n_plans": 1, "picks": [], "prior_plans": [_synthetic_plan()]})
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["proposal"] is not None
    proposal = data["proposal"]
    assert proposal["health"] == "alive"
    assert proposal["dropped_category"] in _ALL_CATS
    assert proposal["relaxed_from_plan_id"] == "balanced"
    assert len(proposal["roster"]) > 0
    assert proposal["objective_score"] > 0
    assert data["value_board"]  # criterion 6's floor is present alongside the proposal


def test_draft_relax_rejects_when_a_plan_is_still_alive():
    import api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    plans = [_synthetic_plan("a", health="broken"), _synthetic_plan("b", health="alive", roster=["someone"])]
    resp = client.post("/draft/relax", json={"n_plans": 1, "picks": [], "prior_plans": plans})
    assert resp.status_code == 409


def test_draft_relax_requires_prior_plans():
    import api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.post("/draft/relax", json={"n_plans": 1, "picks": [], "prior_plans": []})
    assert resp.status_code == 422
