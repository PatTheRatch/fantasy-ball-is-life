"""Shared fixtures.

The secret-scrubbing fixture is ported verbatim in spirit from V1, where it
was the single best piece of test infrastructure: it removes deployment
secrets from the environment before every test, so a local run is structurally
identical to a clean CI run. "Passes locally, fails in CI" caused by a leaked
env var becomes impossible — the dependency fails everywhere, so it is caught
before push.
"""

from __future__ import annotations

import pytest

SCRUBBED_SECRETS = (
    "DATABASE_URL",
    "SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_JWKS_URL",
    "CRED_ENCRYPTION_KEY",
    "WORKER_SECRET",
    "ESPN_SWID",
    "ESPN_S2",
    "ESPN_LEAGUE_ID",
    "ESPN_SEASON",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "RESEND_API_KEY",
)


@pytest.fixture(autouse=True)
def _scrub_ambient_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove deployment secrets from the environment for every test.

    Autouse fixtures run before test-requested ones at the same scope, so a
    fixture that legitimately needs a value can still set it afterwards.
    """
    for name in SCRUBBED_SECRETS:
        monkeypatch.delenv(name, raising=False)
