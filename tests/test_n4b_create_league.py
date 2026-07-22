"""N-4b: POST /leagues endpoint tests — hermetic, no live ESPN or DB."""

from unittest.mock import MagicMock, patch

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
    """
    store = MagicMock()
    store._request = MagicMock(return_value={})
    monkeypatch.setattr("backend.api.routers.create_league.RecapStore", lambda **kw: store)
    return store


_TEST_USER = {"sub": "user-123", "email": "test@example.com", "role": "authenticated"}


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


def _happy_side_effect(team_conflict=False):
    """Return a side_effect sequence for a valid create-league flow.

    The handler calls _request seven times:
      1) _count_user_leagues GET leagues where owner_user_id → count
      2) _unique_slug GET leagues where slug=eq.<base>
      3) _encrypt(swid)  POST rpc/pgp_sym_encrypt
      4) _encrypt(s2)    POST rpc/pgp_sym_encrypt
      5) INSERT league  POST leagues
      6) INSERT membership POST league_memberships
      7) team_name check  GET league_memberships (if team_name given)
      8) claim team       PATCH league_memberships (if team_name given)
    """
    base = [
        [],          # 1) count = 0 owned
        [],          # 2) slug available
        {},          # 3) encrypt swid
        {},          # 4) encrypt s2
        None,        # 5) insert league
        None,        # 6) insert membership
    ]
    if team_conflict:
        base.append([{"id": "other"}])  # 7) team already claimed
    else:
        base.append([])   # 7) team available
        base.append(None) # 8) patch membership
    return base


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestCreateLeagueHappyPath:
    def test_creates_league_and_membership(self, mock_store, mock_auth, mock_validate):
        """Happy path: creates league + owner membership, response omits creds."""
        mock_store._request.side_effect = _happy_side_effect()

        client = TestClient(app)
        resp = client.post("/leagues", json={
            "espn_league_id": 12345,
            "season": 2026,
            "name": "Test League",
            "swid": "swid-value",
            "espn_s2": "s2-value",
        })

        assert resp.status_code == 201
        body = resp.json()
        assert body["slug"] == "test-league"
        assert body["name"] == "Test League"
        assert body["espn_league_id"] == 12345
        assert body["espn_season"] == 2026
        assert "swid" not in body
        assert "espn_s2" not in body

    def test_team_claim_succeeds(self, mock_store, mock_auth, mock_validate):
        """Claiming an available team succeeds."""
        mock_store._request.side_effect = _happy_side_effect(team_conflict=False)

        client = TestClient(app)
        resp = client.post("/leagues", json={
            "espn_league_id": 12345,
            "season": 2026,
            "name": "Test League",
            "swid": "swid-value",
            "espn_s2": "s2-value",
            "team_name": "Team A",
        })

        assert resp.status_code == 201
        assert resp.json()["team_name"] == "Team A"


class TestCapEnforcement:
    def test_cap_reached_returns_409(self, mock_store, mock_auth):
        """User with 2 owned leagues → 409."""
        mock_store._request.return_value = [{"id": "1"}, {"id": "2"}]

        client = TestClient(app)
        resp = client.post("/leagues", json={
            "espn_league_id": 12345,
            "season": 2026,
            "name": "Cap Test",
        })

        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "league_cap_reached"


class TestSlugCollision:
    def test_slug_dedup_on_collision(self, mock_store, mock_auth, mock_validate):
        """Collision appends -2 to slug."""
        # Handler calls _request in this order:
        # 1) count -> 0, 2) slug check (taken), 3) slug check (-2, OK),
        # 4) encrypt, 5) encrypt, 6) insert league, 7) insert membership
        mock_store._request.side_effect = [
            [],                          # 1) 0 owned
            [{"id": "existing"}],        # 2) "test-league" taken
            [],                          # 3) "test-league-2" available
            {},                          # 4) encrypt
            {},                          # 5) encrypt
            None,                        # 6) insert league
            None,                        # 7) insert membership
        ]

        client = TestClient(app)
        resp = client.post("/leagues", json={
            "espn_league_id": 12345,
            "season": 2026,
            "name": "Test League",
        })

        assert resp.status_code == 201
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
        resp = client.post("/leagues", json={
            "espn_league_id": 99999,
            "season": 2026,
            "name": "Bad League",
        })

        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "not_found"

    def test_private_league_returns_422(self, mock_store, mock_auth, monkeypatch):
        from backend.league.create import LeagueValidation

        monkeypatch.setattr(
            "backend.api.routers.create_league.validate_espn_league",
            lambda **kw: LeagueValidation(valid=False, error_code="private_league", error_message="Private"),
        )

        mock_store._request.return_value = []

        client = TestClient(app)
        resp = client.post("/leagues", json={
            "espn_league_id": 12345,
            "season": 2026,
            "name": "Private",
        })

        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "private_league"

    def test_espn_unavailable_returns_503(self, mock_store, mock_auth, monkeypatch):
        from backend.league.create import LeagueValidation

        monkeypatch.setattr(
            "backend.api.routers.create_league.validate_espn_league",
            lambda **kw: LeagueValidation(valid=False, error_code="espn_unavailable", error_message="Down"),
        )

        mock_store._request.return_value = []

        client = TestClient(app)
        resp = client.post("/leagues", json={
            "espn_league_id": 12345,
            "season": 2026,
            "name": "Test",
        })

        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "espn_unavailable"


class TestTeamConflict:
    def test_team_name_conflict_returns_409(self, mock_store, mock_auth, mock_validate):
        """Claimed team → 409."""
        mock_store._request.side_effect = _happy_side_effect(team_conflict=True)

        client = TestClient(app)
        resp = client.post("/leagues", json={
            "espn_league_id": 12345,
            "season": 2026,
            "name": "Test League",
            "swid": "swid-value",
            "espn_s2": "s2-value",
            "team_name": "Team A",
        })

        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "team_taken"


class TestAuth:
    def test_unauthenticated_returns_401(self):
        """No auth token → 401."""
        client = TestClient(app)
        resp = client.post("/leagues", json={
            "espn_league_id": 12345,
            "season": 2026,
            "name": "Test",
        })
        assert resp.status_code == 401
