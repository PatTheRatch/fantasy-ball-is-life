"""Shared fixtures for P-4 multi-league tests.

P-4 removes the global ``config.LEAGUE_ID/SWID/ESPN_S2/SEASON`` constants
and resolves credentials from the DB via ``resolve_league_context()``. This
fixture pushes a stub ``LeagueContext`` onto the ContextVar so tests don't
hit Supabase.
"""

import pytest

from backend.league.credentials import LeagueContext, _LEAGUE_CTX


# Deployment secrets that hermetic tests must NEVER read from the ambient
# shell. They are scrubbed before every test so a local run matches the
# clean CI env (the `backend` / `test-backend` jobs set none of these). A
# test that needs one must set it explicitly via its own fixture
# (e.g. ``monkeypatch.setenv``). This makes "passes locally, fails in CI"
# from a leaked env var impossible: the dependency now fails everywhere,
# so it's caught before push instead of only in CI.
#
# SUPABASE_* is intentionally NOT scrubbed — the RLS job (test_n2_rls.py)
# runs against a real local Supabase via SUPABASE_TEST_* and must keep
# whatever it configures.
_SCRUBBED_SECRETS = (
    "CRED_ENCRYPTION_KEY",
    "WORKER_SECRET",
    "ESPN_SWID",
    "ESPN_S2",
    "ESPN_LEAGUE_ID",
    "ESPN_SEASON",
    "RESEND_API_KEY",
)


@pytest.fixture(autouse=True)
def _scrub_ambient_secrets(monkeypatch):
    """Remove deployment secrets from the environment for every test.

    Runs before test-requested fixtures (pytest orders autouse first at the
    same scope), so a fixture that legitimately needs a value can still set
    it afterwards and win. See ``_SCRUBBED_SECRETS`` for the rationale.
    """
    for name in _SCRUBBED_SECRETS:
        monkeypatch.delenv(name, raising=False)
    yield


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
