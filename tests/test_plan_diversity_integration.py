"""Integration test: the strategy map produces a *diverse, feasible* portfolio
on the real optimizer + real projections.

Unlike the pure unit tests, this drives the actual `OptimizeLineup` engine. It
isolates the one ESPN dependency by stubbing the live league (empty draft).
Most tests below also skip `set_requirements` (bypassing category targets
entirely) so they run as a fast lower-bound check independent of target method.

`test_default_recipe_solves_for_real_with_mc_targets_and_stays_bounded` below
is the exception: it calls the real `set_requirements` with no mock at all.
That's possible (and new) because Monte Carlo targets (the default since
docs/specs/MC_DRAFT_TARGETS.md) are history-independent — unlike the old
ESPN-backed method, MC needs no live league connection, so a real, unmocked,
fully-constrained solve is actually testable here. It wasn't run for real
anywhere in this suite until this test was added, which is how the two solver
issues fixed alongside it (unbounded solve time; percentile defaults tuned
without ever seeing a real constrained solve) went undetected.

Skips cleanly when the engine deps (cvxpy/espn_api) or the projections file
aren't available, so a bare CI checkout stays green.
"""
import contextlib
import io
import itertools
import os

import pytest

from backend.draft.strategies import build_plan_configs, generate_portfolio

pd = pytest.importorskip("pandas")
ol = pytest.importorskip("backend.draft.optimizer")

try:
    from backend.config import BBM_PROJECTIONS_PATH
except Exception:  # pragma: no cover
    BBM_PROJECTIONS_PATH = "player_rankings/BBM_Projections.xls"

pytestmark = pytest.mark.integration

_HAS_PROJECTIONS = os.path.exists(BBM_PROJECTIONS_PATH)


class _FakeLeague:
    """Stands in for the live ESPN league so the optimizer constructs offline."""

    def __init__(self, *args, **kwargs):
        self.draft = []
        self.stat_categories = [
            "PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO",
        ]


def _make_solver(projections_df, monkeypatch):
    monkeypatch.setattr(ol, "MyLeague", _FakeLeague)

    def solve(cfg):
        opt = ol.OptimizeLineup(
            initial_budget=200,
            roster_size=13,
            minimum_value_players=cfg.minimum_value_players,
            favorite_team=None,
            minimum_game_threshold=20,
            value_col="Value",
            projections_df=projections_df,
        )
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                res = opt.optimize_roster(cfg.stat_to_maximize)
        except ValueError:
            return None
        return list(res["Name"].str.lower())

    return solve


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_every_config_is_feasible_on_real_pool(monkeypatch):
    proj = pd.read_excel(BBM_PROJECTIONS_PATH)
    solve = _make_solver(proj, monkeypatch)
    configs = build_plan_configs(10)
    rosters = {c.label: solve(c) for c in configs}
    infeasible = [lbl for lbl, r in rosters.items() if not r]
    assert not infeasible, f"configs infeasible on the real pool: {infeasible}"
    assert all(len(r) == 13 for r in rosters.values())


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_portfolio_dedup_yields_a_diverse_saved_set(monkeypatch):
    proj = pd.read_excel(BBM_PROJECTIONS_PATH)
    solve = _make_solver(proj, monkeypatch)
    configs = build_plan_configs(10)

    plans = generate_portfolio(configs, solve, max_shared=8)

    # After dedup, no two saved plans may share more than the 8/13 bar — this is
    # the guarantee that survives even when some raw configs collapse to the same
    # roster (e.g. single-cat punts with category targets bypassed).
    for a, b in itertools.combinations(plans, 2):
        shared = len(set(a.roster) & set(b.roster))
        assert shared <= 8, f"{a.config.label} vs {b.config.label} share {shared}"

    # The engine + strategy map must still yield a genuinely varied set, not one
    # or two survivors.
    assert len(plans) >= 4


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_default_recipe_solves_for_real_with_mc_targets_and_stays_bounded(monkeypatch):
    """The default 10-plan recipe, solved with real (unmocked) set_requirements
    -- real Monte Carlo category targets against the real player pool, no
    shortcuts. Regression guard for the two issues found running this for the
    first time (2026-07-10): a config that's genuinely hard to solve must never
    hang (config.SOLVER_TIME_LIMIT_SECONDS bounds every call) or silently return
    a broken roster (optimize_lineup.optimize_roster validates the selected
    count before trusting a time-limited result) -- and with the retuned
    STRATEGY_PERCENTILE_BANDS, every default plan should actually solve."""
    import time

    from backend.config import SOLVER_TIME_LIMIT_SECONDS

    monkeypatch.setattr(ol, "MyLeague", _FakeLeague)

    configs = build_plan_configs(10)
    failures = []
    for cfg in configs:
        opt = ol.OptimizeLineup(
            initial_budget=200,
            roster_size=13,
            minimum_value_players=cfg.minimum_value_players,
            minimum_game_threshold=20,
            value_col="Value",
        )
        t0 = time.time()
        with contextlib.redirect_stdout(io.StringIO()):
            opt.set_requirements(list(cfg.constrained_categories), percentile=cfg.percentile)
            try:
                res = opt.optimize_roster(cfg.stat_to_maximize)
            except ValueError as e:
                failures.append((cfg.label, str(e)))
                continue
        elapsed = time.time() - t0
        # Every solve (target-setting + roster solve) is bounded by the solver
        # time limit plus a little slack for the target computation itself.
        assert elapsed <= SOLVER_TIME_LIMIT_SECONDS + 5, f"{cfg.label} took {elapsed:.1f}s"
        assert len(res) == 13, f"{cfg.label} returned {len(res)} players, not 13"

    assert not failures, f"default recipe configs failed against real MC targets: {failures}"
