"""The draft path when NO season projections exist from any source.

This is the fresh-deploy / preseason state: nothing uploaded to the store
yet, and no legacy BBM workbook on disk (it is paid data, gitignored, and
absent from every deploy).

The existing draft integration tests are all guarded by
``@pytest.mark.skipif(not _HAS_PROJECTIONS)``, so they silently skip in CI
and never exercise this branch. These tests do the opposite: they force the
"no projections anywhere" state so it is always exercised, and pin the
contract that the user gets an actionable 422 rather than a 500 carrying the
server's filesystem path.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pandas")
ol = pytest.importorskip("backend.draft.optimizer")

from backend.league import cache
from backend.league.credentials import LeagueContext
from backend.projections.errors import MissingProjectionsError


class _FakeLeague:
    """Stands in for the live ESPN league so OptimizeLineup constructs offline."""

    def __init__(self, *args, **kwargs):
        self.draft = []
        self.stat_categories = [
            "PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO",
        ]


_CTX = LeagueContext(
    league_id="00000000-0000-0000-0000-000000000000",
    slug="test-league",
    name="Test League",
    espn_league_id=123456,
    espn_season=2026,
    swid="",
    espn_s2="",
    timezone="America/New_York",
)


@pytest.fixture
def no_projections_anywhere(monkeypatch, tmp_path):
    """Force the fresh-deploy state regardless of the dev machine's files."""
    monkeypatch.setattr(cache, "MyLeague", _FakeLeague)
    monkeypatch.setattr(ol, "_require_context", lambda *a, **k: _CTX)
    monkeypatch.setattr(
        ol.OptimizeLineup, "set_requirements",
        lambda self, cats, percentile=0.75: None,
    )
    # Point the legacy workbook at a path guaranteed not to exist, so this
    # test is deterministic even on a machine that happens to have the file.
    monkeypatch.setattr(ol, "BBM_PROJECTIONS_PATH", str(tmp_path / "absent.xls"))
    # And make the store report no active season set.
    import backend.projections as projections
    monkeypatch.setattr(projections, "get_active_projections", lambda *a, **k: [])


def test_optimizer_raises_typed_error_not_filenotfound(no_projections_anywhere):
    """The optimizer names the remedy instead of leaking a filesystem path."""
    with pytest.raises(MissingProjectionsError) as exc:
        ol.OptimizeLineup(year=2026)

    message = str(exc.value)
    assert "No season projections are active" in message
    # The whole point: no absolute path / filename in the user-facing text.
    assert ".xls" not in message
    assert "/" not in message


def test_missing_projections_is_a_value_error():
    """Subclassing ValueError keeps the routers' existing ValueError → 422
    mapping working even without the app-wide handler."""
    assert issubclass(MissingProjectionsError, ValueError)


@pytest.mark.parametrize(
    "endpoint,payload",
    [
        ("/draft/plans", {"n_plans": 4, "picks": []}),
        ("/draft/plans/custom", {
            "picks": [],
            "label": "test plan",
            "constrained_categories": ["PTS", "REB"],
            "percentile": 0.75,
            "stat_to_maximize": "PTS",
        }),
        ("/draft/pick", {
            "picks": [],
            "new_pick": {"player_key": "nikola jokic", "price": 60, "is_user": True},
            "prior_plans": [],
        }),
    ],
)
def test_draft_endpoints_return_422_not_500(no_projections_anywhere, endpoint, payload):
    """Every draft entry point reports the same actionable error.

    /draft/pick in particular only has a generic `except Exception` → 500,
    so this passes only because of the app-wide MissingProjectionsError
    handler registered in backend.api.main.
    """
    from fastapi.testclient import TestClient
    import backend.api.main as api

    client = TestClient(api.app, raise_server_exceptions=False)
    resp = client.post(endpoint, json=payload)

    assert resp.status_code == 422, (
        f"{endpoint} returned {resp.status_code}, expected 422. Body: {resp.text}"
    )
    detail = resp.json().get("detail", "")
    assert "No season projections are active" in str(detail)
    # Regression guard: the old behavior leaked the server's absolute path.
    assert "player_rankings" not in resp.text
    assert ".xls" not in resp.text
