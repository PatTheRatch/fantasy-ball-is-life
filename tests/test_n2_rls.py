"""
N-2: RLS boundary tests against a local Supabase instance.

Requires: supabase start (spins up full local stack with migrations applied
and fixture seeded). Run with: ANON_KEY=<local-anon> SERVICE_KEY=<local-service> pytest tests/test_n2_rls.py -v

These tests create real authenticated users and exercise the DB policies
through PostgREST — auth.uid() resolves, with check applies, the boundary
is genuinely tested.

No prod project is touched. The test database is ephemeral.
"""

import os
import uuid

import pytest
import requests

LOCAL_API = os.environ.get("SUPABASE_TEST_URL", "http://localhost:54321")
ANON_KEY = os.environ.get("SUPABASE_TEST_ANON_KEY", "")
SERVICE_KEY = os.environ.get("SUPABASE_TEST_SERVICE_KEY", "")

MISSING = not ANON_KEY or not SERVICE_KEY


def _admin_headers():
    return {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}", "Content-Type": "application/json"}


def _anon_headers(token: str | None = None):
    h = {"apikey": ANON_KEY, "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _create_user(email: str, password: str) -> dict:
    """Create a confirmed user via Admin API, return {id, email, access_token}."""
    user_id = str(uuid.uuid4())
    r = requests.post(
        f"{LOCAL_API}/auth/v1/admin/users",
        headers=_admin_headers(),
        json={
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"display_name": email.split("@")[0]},
        },
    )
    assert r.status_code in (200, 201), f"Create user failed: {r.text}"
    uid = r.json()["id"]

    # Sign in to get an access token
    r2 = requests.post(
        f"{LOCAL_API}/auth/v1/token?grant_type=password",
        headers=_anon_headers(),
        json={"email": email, "password": password},
    )
    assert r2.status_code == 200, f"Sign in failed: {r2.text}"
    return {"id": uid, "email": email, "access_token": r2.json()["access_token"]}


# ── Fixture: seed a public and private league ───────────────────────────

PUBLIC_LEAGUE_ID: str | None = None
PRIVATE_LEAGUE_ID: str | None = None


def _seed_leagues():
    global PUBLIC_LEAGUE_ID, PRIVATE_LEAGUE_ID
    if PUBLIC_LEAGUE_ID:
        return

    # Create public league
    r = requests.post(
        f"{LOCAL_API}/rest/v1/leagues",
        headers=_admin_headers(),
        json={"slug": "test-public", "name": "Test Public", "visibility": "public", "espn_league_id": "1"},
    )
    if r.status_code == 409:
        r2 = requests.get(
            f"{LOCAL_API}/rest/v1/leagues?slug=eq.test-public&select=id",
            headers=_admin_headers(),
        )
        PUBLIC_LEAGUE_ID = r2.json()[0]["id"] if r2.json() else None
    else:
        PUBLIC_LEAGUE_ID = r.json()[0]["id"] if isinstance(r.json(), list) else r.json()["id"]

    # Create private league
    r = requests.post(
        f"{LOCAL_API}/rest/v1/leagues",
        headers=_admin_headers(),
        json={"slug": "test-private", "name": "Test Private", "visibility": "private", "espn_league_id": "2"},
    )
    if r.status_code == 409:
        r2 = requests.get(
            f"{LOCAL_API}/rest/v1/leagues?slug=eq.test-private&select=id",
            headers=_admin_headers(),
        )
        PRIVATE_LEAGUE_ID = r2.json()[0]["id"] if r2.json() else None
    else:
        PRIVATE_LEAGUE_ID = r.json()[0]["id"] if isinstance(r.json(), list) else r.json()["id"]

    assert PUBLIC_LEAGUE_ID, "Failed to seed public league"
    assert PRIVATE_LEAGUE_ID, "Failed to seed private league"


# ── Tests ───────────────────────────────────────────────────────────────

@pytest.mark.skipif(MISSING, reason="SUPABASE_TEST_ANON_KEY/SERVICE_KEY not set")
class TestSelfJoinPolicy:
    """The self-join INSERT policy on league_memberships."""

    def test_insert_self_member_public_succeeds(self):
        _seed_leagues()
        user = _create_user(f"join-ok-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")
        r = requests.post(
            f"{LOCAL_API}/rest/v1/league_memberships",
            headers=_anon_headers(user["access_token"]),
            json={"league_id": PUBLIC_LEAGUE_ID, "user_id": user["id"], "role": "member", "team_name": "Alpha"},
        )
        assert r.status_code == 201, f"Self-join should succeed: {r.status_code} {r.text}"

    def test_self_promotion_to_admin_rejected(self):
        _seed_leagues()
        user = _create_user(f"nopromo-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")
        r = requests.post(
            f"{LOCAL_API}/rest/v1/league_memberships",
            headers=_anon_headers(user["access_token"]),
            json={"league_id": PUBLIC_LEAGUE_ID, "user_id": user["id"], "role": "admin", "team_name": "Beta"},
        )
        assert r.status_code != 201, f"Self-promotion to admin must be rejected: {r.status_code}"

    def test_insert_for_other_user_rejected(self):
        _seed_leagues()
        user = _create_user(f"cross-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")
        other_id = "00000000-0000-0000-0000-000000000099"
        r = requests.post(
            f"{LOCAL_API}/rest/v1/league_memberships",
            headers=_anon_headers(user["access_token"]),
            json={"league_id": PUBLIC_LEAGUE_ID, "user_id": other_id, "role": "member", "team_name": "Gamma"},
        )
        assert r.status_code != 201, f"Cross-user insert must be rejected: {r.status_code}"

    def test_private_league_self_join_rejected(self):
        _seed_leagues()
        user = _create_user(f"nopriv-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")
        r = requests.post(
            f"{LOCAL_API}/rest/v1/league_memberships",
            headers=_anon_headers(user["access_token"]),
            json={"league_id": PRIVATE_LEAGUE_ID, "user_id": user["id"], "role": "member", "team_name": "Delta"},
        )
        assert r.status_code != 201, f"Private-league self-join must be rejected: {r.status_code}"

    def test_anon_insert_rejected(self):
        _seed_leagues()
        r = requests.post(
            f"{LOCAL_API}/rest/v1/league_memberships",
            headers=_anon_headers(),
            json={"league_id": PUBLIC_LEAGUE_ID, "user_id": "00000000-0000-0000-0000-000000000001", "role": "member"},
        )
        assert r.status_code in (401, 403), f"Anon insert must be rejected: {r.status_code}"


@pytest.mark.skipif(MISSING, reason="SUPABASE_TEST_ANON_KEY/SERVICE_KEY not set")
class TestTeamClaimUniqueness:
    def test_first_claim_wins_second_rejected(self):
        _seed_leagues()
        u1 = _create_user(f"claim1-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")
        u2 = _create_user(f"claim2-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")

        team = f"Eagles-{uuid.uuid4().hex[:4]}"
        r1 = requests.post(
            f"{LOCAL_API}/rest/v1/league_memberships",
            headers=_anon_headers(u1["access_token"]),
            json={"league_id": PUBLIC_LEAGUE_ID, "user_id": u1["id"], "role": "member", "team_name": team},
        )
        assert r1.status_code == 201, f"First claim should succeed: {r1.status_code}"

        r2 = requests.post(
            f"{LOCAL_API}/rest/v1/league_memberships",
            headers=_anon_headers(u2["access_token"]),
            json={"league_id": PUBLIC_LEAGUE_ID, "user_id": u2["id"], "role": "member", "team_name": team},
        )
        assert r2.status_code != 201, f"Second claim on same team must be rejected: {r2.status_code}"

    def test_case_insensitive_claim_rejected(self):
        _seed_leagues()
        u1 = _create_user(f"case1-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")
        u2 = _create_user(f"case2-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")

        team = f"HAWKS-{uuid.uuid4().hex[:4]}"
        r1 = requests.post(
            f"{LOCAL_API}/rest/v1/league_memberships",
            headers=_anon_headers(u1["access_token"]),
            json={"league_id": PUBLIC_LEAGUE_ID, "user_id": u1["id"], "role": "member", "team_name": team},
        )
        assert r1.status_code == 201

        r2 = requests.post(
            f"{LOCAL_API}/rest/v1/league_memberships",
            headers=_anon_headers(u2["access_token"]),
            json={"league_id": PUBLIC_LEAGUE_ID, "user_id": u2["id"], "role": "member", "team_name": team.lower()},
        )
        assert r2.status_code != 201, f"Case-variant claim must be rejected (lower(team_name) unique): {r2.status_code}"


@pytest.mark.skipif(MISSING, reason="SUPABASE_TEST_ANON_KEY/SERVICE_KEY not set")
class TestClaimedTeamNames:
    def test_returns_only_name_strings(self):
        _seed_leagues()
        r = requests.post(
            f"{LOCAL_API}/rest/v1/rpc/claimed_team_names",
            headers=_anon_headers(),
            json={"p_league_id": PUBLIC_LEAGUE_ID},
        )
        assert r.status_code == 200
        names = r.json()
        assert isinstance(names, list)
        for name in names:
            assert isinstance(name, str), f"All entries must be strings, got {type(name)}"

    def test_empty_for_unknown_league(self):
        r = requests.post(
            f"{LOCAL_API}/rest/v1/rpc/claimed_team_names",
            headers=_anon_headers(),
            json={"p_league_id": "00000000-0000-0000-0000-000000000000"},
        )
        assert r.status_code == 200
        assert r.json() == []

    def test_callable_by_anon(self):
        _seed_leagues()
        r = requests.post(
            f"{LOCAL_API}/rest/v1/rpc/claimed_team_names",
            headers=_anon_headers(),
            json={"p_league_id": PUBLIC_LEAGUE_ID},
        )
        assert r.status_code == 200

    def test_callable_by_authenticated(self):
        _seed_leagues()
        user = _create_user(f"ctn-auth-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")
        r = requests.post(
            f"{LOCAL_API}/rest/v1/rpc/claimed_team_names",
            headers=_anon_headers(user["access_token"]),
            json={"p_league_id": PUBLIC_LEAGUE_ID},
        )
        assert r.status_code == 200


@pytest.mark.skipif(MISSING, reason="SUPABASE_TEST_ANON_KEY/SERVICE_KEY not set")
class TestDeletePolicy:
    def test_member_removes_self(self):
        _seed_leagues()
        user = _create_user(f"del-self-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")

        # Join first
        r = requests.post(
            f"{LOCAL_API}/rest/v1/league_memberships",
            headers=_anon_headers(user["access_token"]),
            json={"league_id": PUBLIC_LEAGUE_ID, "user_id": user["id"], "role": "member", "team_name": f"Del-{uuid.uuid4().hex[:4]}"},
        )
        assert r.status_code == 201

        # Remove self
        r2 = requests.delete(
            f"{LOCAL_API}/rest/v1/league_memberships?league_id=eq.{PUBLIC_LEAGUE_ID}&user_id=eq.{user['id']}",
            headers=_anon_headers(user["access_token"]),
        )
        assert r2.status_code in (200, 204), f"Self-removal should succeed: {r2.status_code}"

    def test_non_admin_cannot_remove_other(self):
        _seed_leagues()
        u1 = _create_user(f"rem-1-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")
        u2 = _create_user(f"rem-2-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")

        # Both join
        for u, team in [(u1, f"T1-{uuid.uuid4().hex[:4]}"), (u2, f"T2-{uuid.uuid4().hex[:4]}")]:
            r = requests.post(
                f"{LOCAL_API}/rest/v1/league_memberships",
                headers=_anon_headers(u["access_token"]),
                json={"league_id": PUBLIC_LEAGUE_ID, "user_id": u["id"], "role": "member", "team_name": team},
            )
            assert r.status_code == 201, f"Join failed for {u['email']}"

        # u1 tries to remove u2
        r = requests.delete(
            f"{LOCAL_API}/rest/v1/league_memberships?league_id=eq.{PUBLIC_LEAGUE_ID}&user_id=eq.{u2['id']}",
            headers=_anon_headers(u1["access_token"]),
        )
        assert r.status_code != 204, f"Non-admin removing another member must be rejected: {r.status_code}"


@pytest.mark.skipif(MISSING, reason="SUPABASE_TEST_ANON_KEY/SERVICE_KEY not set")
class TestRedeemLeagueInvite:
    def test_redeem_creates_membership_and_marks_used(self):
        _seed_leagues()
        user = _create_user(f"redeem-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")
        token = str(uuid.uuid4())

        # Admin creates invite
        r = requests.post(
            f"{LOCAL_API}/rest/v1/league_invites",
            headers=_admin_headers(),
            json={"league_id": PUBLIC_LEAGUE_ID, "token": token, "role": "member", "created_by": user["id"]},
        )
        assert r.status_code == 201, f"Create invite failed: {r.text}"

        # Redeem
        r2 = requests.post(
            f"{LOCAL_API}/rest/v1/rpc/redeem_league_invite",
            headers=_anon_headers(user["access_token"]),
            json={"p_token": token},
        )
        assert r2.status_code == 200, f"Redeem failed: {r2.text}"

        # Verify membership exists
        r3 = requests.get(
            f"{LOCAL_API}/rest/v1/league_memberships?league_id=eq.{PUBLIC_LEAGUE_ID}&user_id=eq.{user['id']}&select=role",
            headers=_admin_headers(),
        )
        assert len(r3.json()) == 1
        assert r3.json()[0]["role"] == "member"

        # Verify invite marked used
        r4 = requests.get(
            f"{LOCAL_API}/rest/v1/league_invites?token=eq.{token}&select=used_at",
            headers=_admin_headers(),
        )
        assert r4.json()[0]["used_at"] is not None

    def test_double_redeem_rejected(self):
        _seed_leagues()
        user = _create_user(f"double-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")
        token = str(uuid.uuid4())

        requests.post(
            f"{LOCAL_API}/rest/v1/league_invites",
            headers=_admin_headers(),
            json={"league_id": PUBLIC_LEAGUE_ID, "token": token, "role": "member", "created_by": user["id"]},
        )
        # First redeem
        r1 = requests.post(
            f"{LOCAL_API}/rest/v1/rpc/redeem_league_invite",
            headers=_anon_headers(user["access_token"]),
            json={"p_token": token},
        )
        assert r1.status_code == 200

        # Second redeem
        r2 = requests.post(
            f"{LOCAL_API}/rest/v1/rpc/redeem_league_invite",
            headers=_anon_headers(user["access_token"]),
            json={"p_token": token},
        )
        assert r2.status_code != 200, f"Double redeem must be rejected: {r2.status_code}"

    def test_admin_invite_grants_admin_role(self):
        _seed_leagues()
        user = _create_user(f"admininv-{uuid.uuid4().hex[:6]}@test.dev", "pass1234")
        token = str(uuid.uuid4())

        requests.post(
            f"{LOCAL_API}/rest/v1/league_invites",
            headers=_admin_headers(),
            json={"league_id": PUBLIC_LEAGUE_ID, "token": token, "role": "admin", "created_by": user["id"]},
        )
        r = requests.post(
            f"{LOCAL_API}/rest/v1/rpc/redeem_league_invite",
            headers=_anon_headers(user["access_token"]),
            json={"p_token": token},
        )
        assert r.status_code == 200

        r2 = requests.get(
            f"{LOCAL_API}/rest/v1/league_memberships?league_id=eq.{PUBLIC_LEAGUE_ID}&user_id=eq.{user['id']}&select=role",
            headers=_admin_headers(),
        )
        assert r2.json()[0]["role"] == "admin", "Admin invite should grant admin membership"
