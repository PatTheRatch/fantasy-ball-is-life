"""N-4a: Hermetic tests for POST /leagues/preview + validate_espn_league."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.league.create import LeagueValidation
from backend.recaps.auth import require_supabase_user


# ---------------------------------------------------------------------------
# Router-level tests (mocking validate_espn_league — no ESPN calls)
# ---------------------------------------------------------------------------

_AUTH_HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _stub_auth():
    """Replace require_supabase_user via FastAPI's dependency overrides."""
    def _fake_user(authorization: str | None = None):
        return {"id": "test-user-id", "email": "test@example.com"}

    app.dependency_overrides[require_supabase_user] = _fake_user
    yield
    app.dependency_overrides.clear()


def _mock_validate(monkeypatch, result: LeagueValidation):
    """Replace ``validate_espn_league`` with a stub returning *result*."""
    monkeypatch.setattr(
        "backend.api.routers.create.validate_espn_league",
        lambda **kwargs: result,
    )


class TestLeaguePreviewSuccess:
    def test_public_league_returns_200(self, monkeypatch):
        """Validating a public league returns the expected metadata."""
        _mock_validate(
            monkeypatch,
            LeagueValidation(
                valid=True,
                name="Test Hoops League",
                teams=12,
                scoring_type="H2H_CAT",
                season=2026,
                team_names=["Team A", "Team B", "Team C"],
            ),
        )
        client = TestClient(app)
        resp = client.post(
            "/leagues/preview",
            json={"espn_league_id": 12345, "season": 2026},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Test Hoops League"
        assert body["teams"] == 12
        assert body["scoring_type"] == "H2H_CAT"
        assert body["season"] == 2026
        assert body["team_names"] == ["Team A", "Team B", "Team C"]

    def test_response_includes_all_team_names(self, monkeypatch):
        """The response contains every team name from ESPN."""
        names = [f"Team {i}" for i in range(14)]
        _mock_validate(
            monkeypatch,
            LeagueValidation(
                valid=True,
                name="Big League",
                teams=14,
                scoring_type="H2H_PTS",
                season=2026,
                team_names=names,
            ),
        )
        client = TestClient(app)
        resp = client.post(
            "/leagues/preview",
            json={"espn_league_id": 99999, "season": 2026},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 200
        assert len(resp.json()["team_names"]) == 14


class TestLeaguePreviewErrors:
    def test_private_league_without_cookies_returns_422(self, monkeypatch):
        """A private league with no cookies → 422 {code: 'private_league'}."""
        _mock_validate(
            monkeypatch,
            LeagueValidation(
                valid=False,
                error_code="private_league",
                error_message="This league is private.",
            ),
        )
        client = TestClient(app)
        resp = client.post(
            "/leagues/preview",
            json={"espn_league_id": 12345, "season": 2026},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["code"] == "private_league"

    def test_bad_cookies_returns_422(self, monkeypatch):
        """Rejected cookies → 422 {code: 'bad_cookies'}."""
        _mock_validate(
            monkeypatch,
            LeagueValidation(
                valid=False,
                error_code="bad_cookies",
                error_message="ESPN rejected the provided credentials.",
            ),
        )
        client = TestClient(app)
        resp = client.post(
            "/leagues/preview",
            json={
                "espn_league_id": 12345,
                "season": 2026,
                "swid": "bad-swid",
                "espn_s2": "bad-s2",
            },
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "bad_cookies"

    def test_unknown_league_id_returns_404(self, monkeypatch):
        """An unknown ESPN league ID → 404 {code: 'not_found'}."""
        _mock_validate(
            monkeypatch,
            LeagueValidation(
                valid=False,
                error_code="not_found",
                error_message="League 99999 does not exist",
            ),
        )
        client = TestClient(app)
        resp = client.post(
            "/leagues/preview",
            json={"espn_league_id": 99999, "season": 2026},
            headers=_AUTH_HEADERS,
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "not_found"


class TestAuthentication:
    def test_unauthenticated_returns_401(self):
        """No Bearer token → 401 (dependency_overrides are cleared by
        autouse fixture's teardown but re-applied — we explicitly clear
        them here so the real require_supabase_user runs)."""
        # Clear the override so the real auth runs
        app.dependency_overrides.clear()
        try:
            client = TestClient(app)
            resp = client.post(
                "/leagues/preview",
                json={"espn_league_id": 12345, "season": 2026},
                # No Authorization header — expect 401
            )
            assert resp.status_code == 401
        finally:
            # Don't leave the overrides cleared for other tests
            pass


# ---------------------------------------------------------------------------
# Unit tests for validate_espn_league (mocking the League constructor)
# ---------------------------------------------------------------------------

class TestValidateEspnLeagueUnit:
    def test_public_league_success(self, monkeypatch):
        """A public league returns valid=True with metadata."""
        fake_league = type(
            "FakeLeague",
            (),
            {
                "teams": [
                    type("T", (), {"team_name": "Alpha"})(),
                    type("T", (), {"team_name": "Beta"})(),
                ],
            },
        )()

        monkeypatch.setattr(
            "backend.league.create.League",
            lambda **kwargs: fake_league,
        )
        monkeypatch.setattr(
            "backend.league.create.pull_league_meta",
            lambda h: {
                "league_name": "Public Hoops",
                "teams": 8,
                "scoring_type": "H2H_CAT",
                "season": 2026,
            },
        )
        monkeypatch.setattr(
            "backend.league.create.ESPNHandles",
            lambda *, league: type(
                "FakeHandles", (), {"league": league}
            )(),
        )

        from backend.league.create import validate_espn_league

        result = validate_espn_league(espn_league_id=123, season=2026)
        assert result.valid is True
        assert result.name == "Public Hoops"
        assert result.teams == 8
        assert result.scoring_type == "H2H_CAT"
        assert result.season == 2026
        assert result.team_names == ["Alpha", "Beta"]

    def test_private_league_no_cookies(self, monkeypatch):
        """ESPNAccessDenied with 'swid required' → private_league."""
        from espn_api.requests.espn_requests import ESPNAccessDenied

        def _raise(*args, **kwargs):
            raise ESPNAccessDenied("espn_s2 and swid are required")

        monkeypatch.setattr("backend.league.create.League", _raise)

        from backend.league.create import validate_espn_league

        result = validate_espn_league(espn_league_id=123, season=2026)
        assert result.valid is False
        assert result.error_code == "private_league"

    def test_bad_cookies(self, monkeypatch):
        """ESPNAccessDenied with 'cannot be accessed' → bad_cookies."""
        from espn_api.requests.espn_requests import ESPNAccessDenied

        def _raise(*args, **kwargs):
            raise ESPNAccessDenied(
                "League 123 cannot be accessed with the provided credentials"
            )

        monkeypatch.setattr("backend.league.create.League", _raise)

        from backend.league.create import validate_espn_league

        result = validate_espn_league(
            espn_league_id=123, season=2026, swid="x", espn_s2="y"
        )
        assert result.valid is False
        assert result.error_code == "bad_cookies"

    def test_not_found(self, monkeypatch):
        """ESPNInvalidLeague → not_found."""
        from espn_api.requests.espn_requests import ESPNInvalidLeague

        def _raise(*args, **kwargs):
            raise ESPNInvalidLeague("League 99999 does not exist")

        monkeypatch.setattr("backend.league.create.League", _raise)

        from backend.league.create import validate_espn_league

        result = validate_espn_league(espn_league_id=99999, season=2026)
        assert result.valid is False
        assert result.error_code == "not_found"
