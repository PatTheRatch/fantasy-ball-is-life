"""Unit test for the favorite-team feasibility check in
OptimizeLineup._validate_pool_feasibility.

Found while wiring favorite_team/favorite_team_representation through the
Draft Room API: a representation count higher than the number of that team's
players actually remaining in the filtered pool produced cvxpy's opaque
"infeasible" status instead of a clear, actionable error — exactly the class
of bug _validate_pool_feasibility (PR #1) exists to prevent for every other
constraint, but this one wasn't covered yet.
"""
import os

import pytest

ol = pytest.importorskip("backend.draft.optimizer")
from backend.league import cache

try:
    from backend.config import BBM_PROJECTIONS_PATH
except Exception:  # pragma: no cover
    BBM_PROJECTIONS_PATH = "player_rankings/BBM_Projections.xls"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.path.exists(BBM_PROJECTIONS_PATH), reason="projections file not present"),
]


class _FakeLeague:
    def __init__(self, *a, **k):
        self.draft = []
        self.stat_categories = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]


@pytest.fixture(autouse=True)
def _isolate_espn(monkeypatch):
    monkeypatch.setattr(cache, "MyLeague", _FakeLeague)
    monkeypatch.setattr(ol.OptimizeLineup, "set_requirements", lambda self, cats, percentile=0.75: None)


def test_favorite_team_representation_beyond_pool_raises_clear_error():
    opt = ol.OptimizeLineup(
        minimum_game_threshold=20,
        value_col="Value",
        favorite_team="OKC",
        favorite_team_representation=999,  # far beyond any real team's roster
    )
    with pytest.raises(ValueError, match=r"favorite_team_representation=999.*OKC"):
        opt.optimize_roster("PTS")


def test_favorite_team_representation_within_pool_is_unaffected():
    available = int(
        (ol.OptimizeLineup(minimum_game_threshold=20, value_col="Value").player_data_df["Team"] == "OKC").sum()
    )
    opt = ol.OptimizeLineup(
        minimum_game_threshold=20,
        value_col="Value",
        favorite_team="OKC",
        favorite_team_representation=available,  # exactly satisfiable
    )
    result = opt.optimize_roster("PTS")
    assert (result["Team"] == "OKC").sum() >= available
