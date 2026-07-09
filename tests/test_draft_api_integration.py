"""End-to-end integration test for POST /draft/plans and POST /draft/pick,
through the real FastAPI app + real optimizer + real BBM projections.

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
