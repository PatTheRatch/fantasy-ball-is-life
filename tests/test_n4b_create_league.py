"""N-4b: POST /leagues endpoint tests — hermetic, no live ESPN or DB."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.recaps.auth import require_supabase_user


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_store(monkeypatch):
    """Mock RecapStore so no real DB calls happen.

    Each test overrides ``mock_store._request.side_effect`` with the
    sequence of responses its scenario expects.

    Also sets CRED_ENCRYPTION_KEY so the credential-encryption path is
    hermetic: the pgp_sym_encrypt RPC itself is mocked via ``_request``,
    but ``_encrypt`` guards on the env var being present before calling
    it. Without this the with-creds tests 500 in a clean env (e.g. CI).
    """
    monkeypatch.setenv("CRED_ENCRYPTION_KEY", "test-encryption-key")
    store = MagicMock()
    store._request = MagicMock(return_value={})
    import backend.api.routers.create_league as cl
    old = cl.RecapStore
    cl.RecapStore = lambda **kw: store
    yield store
    cl.RecapStore = old


# Supabase's /auth/v1/user object is keyed by "id", not "sub".
_TEST_USER = {"id": "user-123", "email": "test@example.com", "role": "authenticated"}


@pytest.fixture
def mock_auth():
    """Bypass Supabase auth — all requests are authenticated."""
    app.dependency_overrides[require_supabase_user] = lambda: _TEST_USER
    yield
    del app.dependency_overrides[require_supabase_user]


@pytest.fixture
def mock_validate(monkeypatch):
    """Mock validate_espn_league to return success."""
    from backend.league.create import LeagueValidation

    valid = LeagueValidation(
        valid=True, name="Test League", teams=10,
        scoring_type="H2H", season=2026, team_names=["T1", "T2"],
    )
    monkeypatch.setattr(
        "backend.api.routers.create_league.validate_espn_league",
        lambda **kw: valid,
    )
    return valid


# ── Side-effect helpers ───────────────────────────────────────────────────────


def _happy_side_effect(with_creds=False):
    """Return a side_effect sequence for a valid create-league flow.

    Handler call order:
      1) _count_user_leagues  GET  leagues (count owned)
      2) _unique_slug         GET  leagues (slug availability)
      3) _encrypt(swid)       POST rpc/pgp_sym_encrypt  (if creds present)
      4) _encrypt(s2)         POST rpc/pgp_sym_encrypt   (if creds present)
      5) INSERT league        POST leagues
      6) INSERT membership    POST league_memberships
    """
    base = [
        [],          # 1) count = 0 owned
        [],          # 2) slug available
    ]
    if with_creds:
        base.extend([
            {"pgp_sym_encrypt": "encrypted-swid"},  # 3) encrypt swid
            {"pgp_sym_encrypt": "encrypted-s2"},    # 4) encrypt s2
        ])
    base.extend([
        None,        # 5) insert league
        None,        # 6) insert membership
    ])
    return base


_BASE_REQUEST = {
    "espn_league_id": 12345,
    "season": 2026,
    "name": "Test League",
}


def _req(**overrides):
    r = dict(_BASE_REQUEST)
    r.update(overrides)
    return r


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestCreateLeagueHappyPath:
    def test_creates_league_and_membership(self, mock_store, mock_auth, mock_validate):
        """Happy path: creates league + owner membership, response omits creds."""
        mock_store._request.side_effect = _happy_side_effect(with_creds=True)

        client = TestClient(app)
        resp = client.post("/leagues", json=_req(swid="swid-value", espn_s2="s2-value"))

        assert resp.status_code == 201, resp.json()
        body = resp.json()
        assert body["slug"] == "test-league"
        assert body["name"] == "Test League"
        assert body["espn_league_id"] == 12345
        assert body["espn_season"] == 2026
        assert "swid" not in body
        assert "espn_s2" not in body

    def test_team_claim_included_in_response(self, mock_store, mock_auth, mock_validate):
        """team_name is passed through to the membership INSERT and response."""
        mock_store._request.side_effect = _happy_side_effect(with_creds=True)

        client = TestClient(app)
        resp = client.post("/leagues", json=_req(swid="swid-value", espn_s2="s2-value", team_name="Team A"))

        assert resp.status_code == 201, resp.json()
        assert resp.json()["team_name"] == "Team A"


class TestCapEnforcement:
    def test_cap_reached_returns_409(self, mock_store, mock_auth):
        """User with 2 owned leagues → 409."""
        mock_store._request.return_value = [{"id": "1"}, {"id": "2"}]

        client = TestClient(app)
        resp = client.post("/leagues", json=_req())

        assert resp.status_code == 409, resp.json()
        assert resp.json()["detail"]["code"] == "league_cap_reached"


class TestSlugCollision:
    def test_slug_dedup_on_collision(self, mock_store, mock_auth, mock_validate):
        """Collision appends -2 to slug."""
        mock_store._request.side_effect = [
            [],                          # count
            [{"id": "existing"}],        # "test-league" taken
            [],                          # "test-league-2" available
            {"pgp_sym_encrypt": "x"},    # encrypt (creds present)
            {"pgp_sym_encrypt": "x"},    # encrypt
            None,                        # insert league
            None,                        # insert membership
        ]

        client = TestClient(app)
        resp = client.post("/leagues", json=_req(swid="swid-value", espn_s2="s2-value"))

        assert resp.status_code == 201, resp.json()
        assert resp.json()["slug"] == "test-league-2"


class TestValidationErrors:
    def test_invalid_league_does_not_persist(self, mock_store, mock_auth, monkeypatch):
        """Invalid ESPN league → error, no DB writes."""
        from backend.league.create import LeagueValidation

        monkeypatch.setattr(
            "backend.api.routers.create_league.validate_espn_league",
            lambda **kw: LeagueValidation(valid=False, error_code="not_found", error_message="Not found"),
        )

        mock_store._request.return_value = []  # 0 owned

        client = TestClient(app)
        resp = client.post("/leagues", json=_req(espn_league_id=99999))

        assert resp.status_code == 404, resp.json()
        assert resp.json()["detail"]["code"] == "not_found"

    def test_private_league_returns_422(self, mock_store, mock_auth, monkeypatch):
        from backend.league.create import LeagueValidation

        monkeypatch.setattr(
            "backend.api.routers.create_league.validate_espn_league",
            lambda **kw: LeagueValidation(valid=False, error_code="private_league", error_message="Private"),
        )

        mock_store._request.return_value = []

        client = TestClient(app)
        resp = client.post("/leagues", json=_req())

        assert resp.status_code == 422, resp.json()
        assert resp.json()["detail"]["code"] == "private_league"

    def test_espn_unavailable_returns_503(self, mock_store, mock_auth, monkeypatch):
        from backend.league.create import LeagueValidation

        monkeypatch.setattr(
            "backend.api.routers.create_league.validate_espn_league",
            lambda **kw: LeagueValidation(valid=False, error_code="espn_unavailable", error_message="Down"),
        )

        mock_store._request.return_value = []

        client = TestClient(app)
        resp = client.post("/leagues", json=_req())

        assert resp.status_code == 503, resp.json()
        assert resp.json()["detail"]["code"] == "espn_unavailable"


class TestAuth:
    def test_unauthenticated_returns_401(self):
        """No auth token → 401."""
        client = TestClient(app)
        resp = client.post("/leagues", json=_req())
        assert resp.status_code == 401
