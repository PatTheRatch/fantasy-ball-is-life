"""Standings endpoint: auth, membership, envelope (Postgres).

Covers the HTTP layer of the ``LEAGUE_SCOPED`` route: 401 anonymous, 404 unknown
season, 403 non-member, 200 member (envelope shape), and 422 on a bad
``through_period``. The fold itself is tested in the service + read-path tests;
here the season is seeded with no matchups, so the member gets an honest empty
table.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from backend.api.app import create_app
from backend.models.fantasy import (
    FantasyTeam,
    FantasyTeamSeason,
    League,
    LeagueSeason,
)
from backend.models.identity import (
    FantasyTeamSeasonManager,
    Manager,
    ManagerUserLink,
    User,
)
from backend.models.nba import NbaSeason
from tests.api.jwt_helpers import (
    DEFAULT_AUDIENCE,
    DEFAULT_ISSUER,
    generate_rsa_keypair,
    keyset,
    sign_token,
)

KID = "k1"


def _fresh_season_year() -> int:
    """A year that won't collide across tests: ``nba_seasons.season_year`` is
    unique and the ``migrated_session_factory`` doesn't truncate it (no user FK).
    UUID-derived so it's independent of test ordering."""
    return 2000 + (uuid.uuid4().int % 8000)


@pytest.fixture
def client(
    monkeypatch: pytest.MonkeyPatch,
    migrated_session_factory: sessionmaker[Session],
) -> Iterator[tuple[TestClient, RSAPrivateKey, sessionmaker[Session]]]:
    monkeypatch.setenv("SUPABASE_JWT_ISSUER", DEFAULT_ISSUER)
    monkeypatch.setenv("SUPABASE_JWT_AUDIENCE", DEFAULT_AUDIENCE)
    private, public = generate_rsa_keypair()
    app = create_app(keyset=keyset(public, KID), session_factory=migrated_session_factory)
    with TestClient(app) as test_client:
        yield test_client, private, migrated_session_factory


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_member(
    factory: sessionmaker[Session], *, sub: str, email: str, as_member: bool = True
) -> uuid.UUID:
    """Seed a user + league_season; link them if ``as_member``. Returns the
    league_season id."""
    year = _fresh_season_year()

    with factory() as session:
        user = User(auth_subject=sub, email=email, display_name=email)
        nba = NbaSeason(
            season_year=year, label=f"test {year}",
            start_date=date(year - 1, 10, 1), end_date=date(year, 6, 1),
        )
        league = League(slug=f"test-{uuid.uuid4().hex[:8]}", name="Test League")
        session.add_all([user, nba, league])
        session.flush()

        season = LeagueSeason(
            league_id=league.id, nba_season_id=nba.id, season_year=year,
            provider_key="espn", provider_league_id="999",
            scoring_type="h2h_categories",
        )
        team = FantasyTeam(league_id=league.id)
        session.add_all([season, team])
        session.flush()

        fts = FantasyTeamSeason(
            fantasy_team_id=team.id, league_season_id=season.id,
            name="Team A", provider_team_id="1",
        )
        session.add(fts)
        session.flush()

        if as_member:
            manager = Manager(display_name="Manager")
            session.add(manager)
            session.flush()
            session.add(ManagerUserLink(manager_id=manager.id, user_id=user.id))
            session.add(
                FantasyTeamSeasonManager(
                    fantasy_team_season_id=fts.id, manager_id=manager.id
                )
            )

        session.commit()
        return season.id


def test_401_anonymous(client) -> None:
    test_client, _, _ = client
    resp = test_client.get(f"/api/v1/leagues/{uuid.uuid4()}/standings")
    assert resp.status_code == 401


def test_404_unknown_season(client) -> None:
    test_client, private, _ = client
    token = sign_token(private, kid=KID, sub="known-user", email="u@x.com")
    resp = test_client.get(
        f"/api/v1/leagues/{uuid.uuid4()}/standings", headers=_auth(token)
    )
    assert resp.status_code == 404


def test_403_non_member(client) -> None:
    test_client, private, factory = client
    _seed_member(factory, sub="member-owner", email="owner@x.com")
    # A different user, no manager link to the league.
    token = sign_token(private, kid=KID, sub="outsider", email="out@x.com")

    # Re-open the session to read the seeded season id.
    with factory() as session:
        season_id = session.query(LeagueSeason).one().id

    resp = test_client.get(
        f"/api/v1/leagues/{season_id}/standings", headers=_auth(token)
    )
    assert resp.status_code == 403


def test_200_member_gets_envelope(client) -> None:
    test_client, private, factory = client
    season_id = _seed_member(factory, sub="member-1", email="m1@x.com")
    token = sign_token(private, kid=KID, sub="member-1", email="m1@x.com")

    resp = test_client.get(
        f"/api/v1/leagues/{season_id}/standings", headers=_auth(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["freshness"] == "final"
    assert body["stale"] is False
    assert body["as_of"] is None  # no final periods seeded
    assert body["data"] == []


def test_422_invalid_through_period(client) -> None:
    test_client, private, factory = client
    season_id = _seed_member(factory, sub="member-2", email="m2@x.com")
    token = sign_token(private, kid=KID, sub="member-2", email="m2@x.com")

    resp = test_client.get(
        f"/api/v1/leagues/{season_id}/standings?through_period=0",
        headers=_auth(token),
    )
    assert resp.status_code == 422
