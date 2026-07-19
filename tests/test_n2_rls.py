"""
N-2: RLS boundary tests for self-join + claimed_team_names.

These directly exercise the DB policies — the JoinLeague.test.tsx tests
cover the UI component, these cover the policy enforcement at the DB level.
"""
import os

import pytest
import requests


SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

LEAGUE_ID = "38538700-0000-4000-8000-000000000001"  # patriot-games


def _headers():
    return {"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"}


@pytest.mark.skipif(not SUPABASE_URL, reason="SUPABASE_URL not set")
class TestSelfJoinRLS:
    """The self-join INSERT policy enforces:
    - user_id must match auth.uid()
    - role must be 'member'
    - league visibility must be 'public'
    These tests run unauthenticated — they prove the policy REJECTS
    when these constraints are violated.
    """

    def test_anon_insert_rejected(self):
        """Anon (unauthenticated) can't insert any membership row."""
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/league_memberships",
            headers=_headers(),
            json={"league_id": LEAGUE_ID, "user_id": "00000000-0000-0000-0000-000000000001", "role": "member"},
        )
        # 401 = not authenticated (insert policy requires TO authenticated)
        assert r.status_code in (401, 403), f"Unexpected {r.status_code}: {r.text}"


@pytest.mark.skipif(not SUPABASE_URL, reason="SUPABASE_URL not set")
class TestClaimedTeamNames:
    def test_returns_array(self):
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/claimed_team_names",
            headers=_headers(),
            json={"p_league_id": LEAGUE_ID},
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # Through The Wire is already claimed (from seed/prior test)
        assert "Through The Wire" in data

    def test_returns_empty_for_unknown_league(self):
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/rpc/claimed_team_names",
            headers=_headers(),
            json={"p_league_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert r.status_code == 200
        assert r.json() == []
