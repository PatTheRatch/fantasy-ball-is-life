"""End-to-end integration test for POST /draft/plans, POST /draft/pick,
POST /draft/triage, and POST /draft/relax, through the real FastAPI app +
real optimizer + real BBM projections.

Same isolation pattern as tests/test_plan_diversity_integration.py: ESPN is
stubbed (a fake empty-draft league) so this runs without network access, and
`set_requirements` is consequently skipped inside the stubbed solve path in
backend/api/main.py's own error handling is NOT bypassed here — we're
driving the actual production code path (api.draft_plans / api.draft_pick,
imported from backend.api.main), not a copy of it.

Skips cleanly when the engine deps or the projections file aren't available.
"""
import os

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("fastapi")
ol = pytest.importorskip("backend.draft.optimizer")

try:
    from backend.config import BBM_PROJECTIONS_PATH
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
    import backend.api.main as api

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
    import backend.api.main as api

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
    import backend.api.main as api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    plans = [_synthetic_plan("a", health="broken"), _synthetic_plan("b", health="alive", roster=["someone"])]
    resp = client.post("/draft/relax", json={"n_plans": 1, "picks": [], "prior_plans": plans})
    assert resp.status_code == 409


def test_draft_relax_requires_prior_plans():
    import backend.api.main as api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.post("/draft/relax", json={"n_plans": 1, "picks": [], "prior_plans": []})
    assert resp.status_code == 422


# --- "how do I define what I'm optimizing for" (exclude / favorite team /
# target player / category+confidence picker) -----------------------------


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_exclude_players_never_appear_in_any_plan(monkeypatch):
    import backend.api.main as api

    monkeypatch.setattr(ol, "MyLeague", _FakeLeague)
    monkeypatch.setattr(ol.OptimizeLineup, "set_requirements", lambda self, cats, percentile=0.75: None)
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    proj = pd.read_excel(BBM_PROJECTIONS_PATH)
    avoid = proj.sort_values("$", ascending=False)["Name"].iloc[0].lower()

    resp = client.post("/draft/plans", json={"n_plans": 6, "picks": [], "exclude_players": [avoid]})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["plans"], "expected at least one plan"
    for p in data["plans"]:
        assert avoid not in p["roster"]
    assert avoid not in {v["player_key"] for v in data["value_board"]}


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_favorite_team_representation_is_respected(monkeypatch):
    import backend.api.main as api

    monkeypatch.setattr(ol, "MyLeague", _FakeLeague)
    monkeypatch.setattr(ol.OptimizeLineup, "set_requirements", lambda self, cats, percentile=0.75: None)
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    # Count against the *actually filtered* pool (same games/exclude filters
    # the solver sees), not the raw projections file — the raw file overcounts
    # a team's real availability (e.g. injured/limited players get filtered
    # out later), which previously picked an unsatisfiable representation
    # count here and masked a real gap (see test_validate_pool_feasibility.py).
    pool = ol.OptimizeLineup(minimum_game_threshold=20, value_col="Value").player_data_df
    team_counts = pool[pool["Team"] != "FA"]["Team"].value_counts()  # "FA" = free agent, not a real team
    fav_team = team_counts[team_counts >= 5].index[0]
    representation = 2  # comfortably below any qualifying team's real availability

    resp = client.post(
        "/draft/plans",
        json={
            "n_plans": 4,
            "picks": [],
            "favorite_team": fav_team,
            "favorite_team_representation": representation,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["plans"], "expected at least one plan"
    team_by_name = dict(zip(pool["Name"].str.lower(), pool["Team"]))
    for p in data["plans"]:
        fav_count = sum(1 for name in p["roster"] if team_by_name.get(name) == fav_team)
        assert fav_count >= representation, f"{p['label']} only has {fav_count} {fav_team} players"


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_target_player_is_pre_locked_onto_every_plan_at_projected_price(monkeypatch):
    import backend.api.main as api

    monkeypatch.setattr(ol, "MyLeague", _FakeLeague)
    monkeypatch.setattr(ol.OptimizeLineup, "set_requirements", lambda self, cats, percentile=0.75: None)
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    # Pick from the *actually filtered* pool (opt.player_data_df), not the raw
    # projections file — a handful of highly-projected players (e.g. injured,
    # limited-games-remaining) never make it past the engine's own filters, so
    # reading the raw file can name someone who'd legitimately land in
    # skipped_targets rather than get pre-locked.
    pool = ol.OptimizeLineup(minimum_game_threshold=20, value_col="Value").player_data_df
    row = pool.sort_values("$", ascending=False).iloc[10]
    favorite = row["Name"].lower()
    projected_price = round(float(row["$"]))

    resp = client.post(
        "/draft/plans",
        json={"n_plans": 4, "picks": [], "target_players": [{"player_key": favorite}]},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["plans"], "expected at least one plan"
    for p in data["plans"]:
        assert favorite in p["roster"]
        # a pre-locked target reads as "already owned" for planning purposes
        assert p["next_target"] is None or p["next_target"]["player_key"] != favorite

    # An explicit expected_price overrides the default projected price.
    resp2 = client.post(
        "/draft/plans",
        json={
            "n_plans": 2,
            "picks": [],
            "target_players": [{"player_key": favorite, "expected_price": projected_price + 15}],
        },
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["plans"], "expected at least one plan even at an inflated expected price"


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_target_categories_and_stat_to_maximize_are_respected(monkeypatch):
    import backend.api.main as api

    monkeypatch.setattr(ol, "MyLeague", _FakeLeague)
    monkeypatch.setattr(ol.OptimizeLineup, "set_requirements", lambda self, cats, percentile=0.75: None)
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.post(
        "/draft/plans",
        json={
            "n_plans": 6,
            "picks": [],
            "target_categories": ["PTS", "REB", "AST", "STL", "BLK", "3PM"],  # no FG%/FT%/TO
            "stat_to_maximize": "AST",
            "base_percentile": 0.6,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["plans"], "expected at least one plan"
    for p in data["plans"]:
        assert set(p["config"]["constrained_categories"]) <= {"PTS", "REB", "AST", "STL", "BLK", "3PM"}
        assert p["config"]["stat_to_maximize"] == "AST"


def test_target_categories_validation_error_returns_422():
    import backend.api.main as api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.post(
        "/draft/plans",
        json={"n_plans": 2, "picks": [], "target_categories": ["PTS"], "stat_to_maximize": "REB"},
    )
    assert resp.status_code == 422


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_draft_plans_custom_solves_one_hand_tuned_plan(monkeypatch):
    """POST /draft/plans/custom -- the "build your own, save it" flow. Unlike
    /draft/plans' fixed recipe, every knob here comes straight from the
    caller."""
    import backend.api.main as api

    monkeypatch.setattr(ol, "MyLeague", _FakeLeague)
    monkeypatch.setattr(ol.OptimizeLineup, "set_requirements", lambda self, cats, percentile=0.75: None)

    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.post(
        "/draft/plans/custom",
        json={
            "picks": [],
            "label": "My punt-AST build",
            "constrained_categories": ["PTS", "REB", "STL", "BLK", "3PM", "FG%", "FT%", "TO"],
            "percentile": 0.4,
            "stat_to_maximize": "PTS",
            "minimum_value_players": 4,
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["plan"]["label"] == "My punt-AST build"
    assert data["plan"]["config"]["shape"] == "custom"
    assert data["plan"]["config"]["percentile"] == 0.4
    assert data["plan"]["config"]["minimum_value_players"] == 4
    assert "AST" not in data["plan"]["config"]["constrained_categories"]
    assert data["plan"]["health"] == "alive"
    assert len(data["plan"]["roster"]) > 0
    assert len(data["value_board"]) > 0


def test_draft_plans_custom_rejects_maximizing_a_punted_category():
    import backend.api.main as api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.post(
        "/draft/plans/custom",
        json={
            "picks": [],
            "label": "Invalid",
            "constrained_categories": ["REB", "AST"],
            "percentile": 0.5,
            "stat_to_maximize": "PTS",
        },
    )
    assert resp.status_code == 422


def test_draft_plans_custom_rejects_out_of_range_percentile():
    import backend.api.main as api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.post(
        "/draft/plans/custom",
        json={
            "picks": [],
            "label": "Invalid",
            "constrained_categories": ["PTS", "REB"],
            "percentile": 1.5,
            "stat_to_maximize": "PTS",
        },
    )
    assert resp.status_code == 422


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_value_source_forge_prices_the_value_board_differently(monkeypatch):
    """value_source="forge" must actually change what the pool/value board is
    priced against -- Forge Value (player_values.calculate_player_values)
    instead of the uploaded projections' own $ column -- and must use the
    live league's real team count, not a hardcoded default."""
    import backend.api.main as api

    class _FakeLeagueWithSettings(_FakeLeague):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

            class _Settings:
                team_count = 8

            self.settings = _Settings()

    monkeypatch.setattr(ol, "MyLeague", _FakeLeagueWithSettings)
    monkeypatch.setattr(ol.OptimizeLineup, "set_requirements", lambda self, cats, percentile=0.75: None)

    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    bbm_resp = client.post("/draft/plans", json={"n_plans": 2, "picks": [], "value_source": "bbm"})
    forge_resp = client.post("/draft/plans", json={"n_plans": 2, "picks": [], "value_source": "forge"})
    assert bbm_resp.status_code == 200, bbm_resp.text
    assert forge_resp.status_code == 200, forge_resp.text

    bbm_board = {row["player_key"]: row["max_bid"] for row in bbm_resp.json()["value_board"]}
    forge_board = {row["player_key"]: row["max_bid"] for row in forge_resp.json()["value_board"]}
    common = set(bbm_board) & set(forge_board)
    assert len(common) > 0
    assert any(bbm_board[k] != forge_board[k] for k in common)


def test_value_source_rejects_unknown_value():
    import backend.api.main as api
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.post("/draft/plans", json={"n_plans": 1, "picks": [], "value_source": "yahoo"})
    assert resp.status_code == 422


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_draft_players_search_matches_by_substring(monkeypatch):
    import backend.api.main as api

    monkeypatch.setattr(ol, "MyLeague", _FakeLeague)
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.get("/draft/players", params={"q": "maxey"})
    assert resp.status_code == 200, resp.text
    results = resp.json()
    assert any(r["player_key"] == "tyrese maxey" for r in results)
    for r in results:
        assert set(r.keys()) == {"player_key", "pos", "team", "value"}


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_draft_players_search_requires_two_chars(monkeypatch):
    import backend.api.main as api

    monkeypatch.setattr(ol, "MyLeague", _FakeLeague)
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.get("/draft/players", params={"q": "m"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_draft_players_search_no_match_returns_empty(monkeypatch):
    import backend.api.main as api

    monkeypatch.setattr(ol, "MyLeague", _FakeLeague)
    from fastapi.testclient import TestClient

    client = TestClient(api.app)

    resp = client.get("/draft/players", params={"q": "zzzznotarealplayerzzzz"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
