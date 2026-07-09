"""Integration test: the strategy map produces a *diverse, feasible* portfolio
on the real optimizer + real projections.

Unlike the pure unit tests, this drives the actual `OptimizeLineup` engine. It
isolates the one ESPN dependency by stubbing the live league (empty draft) and
skipping `set_requirements` (whose targets come from `get_universe_wins` /
ESPN history) — so it runs anywhere the projections file is present, no ESPN
needed. In production the solver also sets category requirements from
ESPN-derived targets, which *increases* diversity; this test therefore measures
a lower bound.

Skips cleanly when the engine deps (cvxpy/espn_api) or the projections file
aren't available, so a bare CI checkout stays green.
"""
import contextlib
import io
import itertools
import os

import pytest

from draft_strategies import build_plan_configs, generate_portfolio

pd = pytest.importorskip("pandas")
ol = pytest.importorskip("optimize_lineup")

try:
    from config import BBM_PROJECTIONS_PATH
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
