"""Shared fixtures for P-4 multi-league tests.

P-4 removes the global ``config.LEAGUE_ID/SWID/ESPN_S2/SEASON`` constants
and resolves credentials from the DB via ``get_league_context()``. Every
test that needs ESPN handles must mock this function to avoid hitting
Supabase.
"""

from unittest.mock import Mock, patch

import pytest

from backend.league.credentials import LeagueContext


@pytest.fixture(autouse=True)
def _mock_league_context():
    """Mock get_league_context() for all tests.

    Returns a stub LeagueContext so ``connect()`` and other ESPN-dependent
    code paths don't try to reach Supabase.
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
    with patch("backend.league.credentials.get_league_context", return_value=ctx):
        # Also patch the cached-reference in deps.py
        with patch("backend.api.deps._CTX", ctx):
            yield
