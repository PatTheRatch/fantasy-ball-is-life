"""N-4b + N-4c: POST /leagues endpoint tests — hermetic, no live ESPN or DB."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.recaps.auth import require_supabase_user


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_store(monkeypatch):
    """Mock RecapStore so no real DB calls happen.

    Also sets CRED_ENCRYPTION_KEY so the credential-encryption path is
    hermetic: the pgp_sym_encrypt RPC is mocked via ``_request``, but
    ``_encrypt`` guards on the env var before calling it. Without this the
    with-creds tests 500 in a clean env (e.g. CI).
    """
    monkeypatch.setenv("CRED_ENCRYPTION_KEY", "test-encryption-key")
    store = MagicMock()
    store._request = MagicMock(return_value={})
    import backend.api.routers.create_league as cl
    old = cl.RecapStore
    cl.RecapStore = lambda **kw: store
    yield store
    cl.RecapStore = old


@pytest.fixture
def mock_refresh(monkeypatch):
    """Mock _background_refresh so no real worker runs."""
    mock = MagicMock()
    monkeypatch.setattr(
        "backend.api.routers.create_league._background_refresh",
        mock,
    )
    return mock


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


_BASE_REQUEST = {
    "espn_league_id": 12345,
    "season": 2026,
    "name": "Test League",
    "swid": "swid-value",
    "espn_s2": "s2-value",
}


def _happy_side_effect():
    """Return a side_effect sequence matching the handler's _request calls."""
    return [
        [],          # _count_user_leagues → 0 owned
        [],          # _unique_slug → available
        {"pgp_sym_encrypt": "enc"},  # encrypt swid
        {"pgp_sym_encrypt": "enc"},  # encrypt s2
        None,        # INSERT league
        None,        # INSERT membership
    ]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestCreateLeagueHappyPath:
    def test_creates_league_and_membership(self, mock_store, mock_auth, mock_validate, mock_refresh):
        mock_store._request.side_effect = _happy_side_effect()

        client = TestClient(app)
        resp = client.post("/leagues", json=_BASE_REQUEST)

        assert resp.status_code == 201, resp.json()
        body = resp.json()
        assert body["slug"] == "test-league"
        assert body["name"] == "Test League"
        assert body["espn_league_id"] == 12345
        assert body["espn_season"] == 2026
        assert "swid" not in body

    def test_schedules_background_refresh(self, mock_store, mock_auth, mock_validate, mock_refresh):
        """N-4c: creating a league schedules _background_refresh with the slug."""
        mock_store._request.side_effect = _happy_side_effect()

        client = TestClient(app)
        resp = client.post("/leagues", json=_BASE_REQUEST)

        assert resp.status_code == 201
        # TestClient runs background tasks after the response, so the mocked
        # _background_refresh is invoked once with the new league's slug.
        mock_refresh.assert_called_once_with("test-league")

    def test_team_claim_included_in_response(self, mock_store, mock_auth, mock_validate, mock_refresh):
        mock_store._request.side_effect = _happy_side_effect()

        client = TestClient(app)
        resp = client.post("/leagues", json={**_BASE_REQUEST, "team_name": "Team A"})

        assert resp.status_code == 201, resp.json()
        assert resp.json()["team_name"] == "Team A"


class TestBackgroundRefreshFailure:
    def test_refresh_failure_does_not_fail_request(self, mock_store, mock_auth, mock_validate, monkeypatch):
        """N-4c: a refresh that raises does not break the 201."""
        mock_store._request.side_effect = _happy_side_effect()

        def _failing_worker(*args, **kwargs):
            raise RuntimeError("ESPN is down")

        monkeypatch.setattr(
            "backend.worker.refresh.refresh_league",
            _failing_worker,
        )

        client = TestClient(app)
        resp = client.post("/leagues", json=_BASE_REQUEST)

        assert resp.status_code == 201, resp.json()
        assert resp.json()["slug"] == "test-league"


class TestNoRefreshOnFailure:
    def test_no_refresh_on_cap_reached(self, mock_store, mock_auth, mock_refresh):
        """Precondition failure → no background refresh."""
        mock_store._request.return_value = [{"id": "1"}, {"id": "2"}]

        client = TestClient(app)
        resp = client.post("/leagues", json=_BASE_REQUEST)

        assert resp.status_code == 409
        mock_refresh.assert_not_called()

    def test_no_refresh_on_validation_failure(self, mock_store, mock_auth, mock_refresh, monkeypatch):
        """Validation failure → no background refresh."""
        from backend.league.create import LeagueValidation

        monkeypatch.setattr(
            "backend.api.routers.create_league.validate_espn_league",
            lambda **kw: LeagueValidation(valid=False, error_code="not_found", error_message="NF"),
        )
        mock_store._request.return_value = []

        client = TestClient(app)
        resp = client.post("/leagues", json=_BASE_REQUEST)

        assert resp.status_code == 404
        mock_refresh.assert_not_called()


class TestCapEnforcement:
    def test_cap_reached_returns_409(self, mock_store, mock_auth, mock_refresh):
        mock_store._request.return_value = [{"id": "1"}, {"id": "2"}]

        client = TestClient(app)
        resp = client.post("/leagues", json=_BASE_REQUEST)

        assert resp.status_code == 409, resp.json()
        assert resp.json()["detail"]["code"] == "league_cap_reached"


class TestSlugCollision:
    def test_slug_dedup_on_collision(self, mock_store, mock_auth, mock_validate, mock_refresh):
        mock_store._request.side_effect = [
            [],                          # count
            [{"id": "existing"}],        # slug taken
            [],                          # -2 available
            {"pgp_sym_encrypt": "x"}, {"pgp_sym_encrypt": "x"},
            None, None,
        ]

        client = TestClient(app)
        resp = client.post("/leagues", json=_BASE_REQUEST)

        assert resp.status_code == 201, resp.json()
        assert resp.json()["slug"] == "test-league-2"


class TestValidationErrors:
    def test_invalid_league_does_not_persist(self, mock_store, mock_auth, monkeypatch):
        from backend.league.create import LeagueValidation

        monkeypatch.setattr(
            "backend.api.routers.create_league.validate_espn_league",
            lambda **kw: LeagueValidation(valid=False, error_code="not_found", error_message="NF"),
        )
        mock_store._request.return_value = []

        client = TestClient(app)
        resp = client.post("/leagues", json={**_BASE_REQUEST, "espn_league_id": 99999})

        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "not_found"

    def test_private_league_returns_422(self, mock_store, mock_auth, monkeypatch):
        from backend.league.create import LeagueValidation

        monkeypatch.setattr(
            "backend.api.routers.create_league.validate_espn_league",
            lambda **kw: LeagueValidation(valid=False, error_code="private_league", error_message="P"),
        )
        mock_store._request.return_value = []

        client = TestClient(app)
        resp = client.post("/leagues", json=_BASE_REQUEST)

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
        resp = client.post("/leagues", json=_BASE_REQUEST)

        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "espn_unavailable"


class TestAuth:
    def test_unauthenticated_returns_401(self):
        client = TestClient(app)
        resp = client.post("/leagues", json=_BASE_REQUEST)
        assert resp.status_code == 401
