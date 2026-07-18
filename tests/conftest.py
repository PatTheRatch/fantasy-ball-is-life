"""Shared fixtures for P-4 multi-league tests.

P-4 removes the global ``config.LEAGUE_ID/SWID/ESPN_S2/SEASON`` constants
and resolves credentials from the DB via ``resolve_league_context()``. This
fixture pushes a stub ``LeagueContext`` onto the ContextVar so tests don't
hit Supabase.
"""

import pytest

from backend.league.credentials import LeagueContext, _LEAGUE_CTX


@pytest.fixture(autouse=True)
def _mock_league_context():
    """Push a stub LeagueContext onto the ContextVar for all tests.

    ``_require_context()`` and ``get_league_context()`` will return this
    stub instead of hitting Supabase.
    """
    ctx = LeagueContext(
        league_id="test-league-uuid",
        slug="test-league",
        name="Test League",
        espn_league_id=123456,
        espn_season=2026,
        swid="test-swid",
        espn_s2="test-s2",
        timezone="America/New_York",
    )
    token = _LEAGUE_CTX.set(ctx)
    yield
    _LEAGUE_CTX.reset(token)
