"""Periods endpoint: auth, membership, tenancy, envelope (Postgres).

Covers the HTTP layer of the new ``LEAGUE_SCOPED`` periods route: 401 anonymous,
404 unknown season, 403 non-member, 200 member (all periods, ordinal-ordered,
no provider identifier / finality fields), tenancy isolation across seasons, and
the empty-season case. Statuses are seeded explicitly — nothing writes period
finality yet (H-07), so no date-based fallback exists here.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, datetime

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
    MatchupPeriod,
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
    """A year that won't collide across tests (``nba_seasons.season_year`` is
    unique and the migrated factory doesn't truncate it)."""
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
    factory: sessionmaker[Session],
    *,
    sub: str,
    email: str,
    as_member: bool = True,
    periods: tuple[dict, ...] = (),
) -> uuid.UUID:
    """Seed a user + league_season (+ membership) and the given periods. Returns
    the league_season id. ``periods`` are ``MatchupPeriod`` kwargs with explicit
    statuses — finality is never inferred from dates here."""
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

        for spec in periods:
            session.add(MatchupPeriod(league_season_id=season.id, **spec))

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


def _period_ids(
    factory: sessionmaker[Session], season_id: uuid.UUID
) -> set[uuid.UUID]:
    with factory() as session:
        return {
            p.id
            for p in session.query(MatchupPeriod)
            .filter(MatchupPeriod.league_season_id == season_id)
            .all()
        }


def _period(
    ordinal: int, *, label: str, status: str, provider_period_id: str
) -> dict:
    spec = {
        "ordinal": ordinal,
        "label": label,
        "status": status,
        "start_date": date(2026, 1, 5 + 7 * (ordinal - 1)),
        "end_date": date(2026, 1, 11 + 7 * (ordinal - 1)),
        "provider_period_id": provider_period_id,
    }
    if status == "final":
        # The finality constraint ties status to finalized_at (H-05a); seed it.
        spec["finalized_at"] = datetime(2026, 1, 11 + 7 * (ordinal - 1), 12, 0, 0)
    return spec


def test_401_anonymous(client) -> None:
    test_client, _, _ = client
    resp = test_client.get(f"/api/v1/leagues/{uuid.uuid4()}/periods")
    assert resp.status_code == 401


def test_404_unknown_season(client) -> None:
    test_client, private, _ = client
    token = sign_token(private, kid=KID, sub="known-user", email="u@x.com")
    resp = test_client.get(
        f"/api/v1/leagues/{uuid.uuid4()}/periods", headers=_auth(token)
    )
    assert resp.status_code == 404


def test_403_non_member(client) -> None:
    test_client, private, factory = client
    _seed_member(factory, sub="member-owner", email="owner@x.com")
    token = sign_token(private, kid=KID, sub="outsider", email="out@x.com")

    with factory() as session:
        season_id = session.query(LeagueSeason).one().id

    resp = test_client.get(
        f"/api/v1/leagues/{season_id}/periods", headers=_auth(token)
    )
    assert resp.status_code == 403


def test_200_member_gets_all_periods_ordinal_ordered(client) -> None:
    test_client, private, factory = client
    season_id = _seed_member(
        factory,
        sub="member-1",
        email="m1@x.com",
        periods=(
            # Seeded out of order to prove the endpoint sorts by ordinal.
            _period(2, label="Week 2", status="scheduled", provider_period_id="espn-2"),
            _period(1, label="Week 1", status="final", provider_period_id="espn-1"),
        ),
    )
    token = sign_token(private, kid=KID, sub="member-1", email="m1@x.com")

    resp = test_client.get(
        f"/api/v1/leagues/{season_id}/periods", headers=_auth(token)
    )
    assert resp.status_code == 200
    body = resp.json()

    assert [p["ordinal"] for p in body["data"]] == [1, 2]
    assert [p["label"] for p in body["data"]] == ["Week 1", "Week 2"]
    assert [p["status"] for p in body["data"]] == ["final", "scheduled"]
    assert [p["type"] for p in body["data"]] == ["regular", "regular"]
    assert [p["start_date"] for p in body["data"]] == ["2026-01-05", "2026-01-12"]
    assert [p["end_date"] for p in body["data"]] == ["2026-01-11", "2026-01-18"]
    # Provider identifiers (D19) and the always-null finality field (H-07) must
    # not escape to the wire.
    for p in body["data"]:
        assert "provider_period_id" not in p
        assert "finalized_at" not in p
    assert set(body) == {"data"}  # no as_of/freshness/stale envelope


def test_periods_do_not_leak_across_seasons(client) -> None:
    test_client, private, factory = client
    season_a = _seed_member(
        factory,
        sub="member-a",
        email="a@x.com",
        periods=(
            _period(1, label="Week 1", status="final", provider_period_id="a-1"),
            _period(2, label="Week 2", status="scheduled", provider_period_id="a-2"),
        ),
    )
    season_b = _seed_member(
        factory,
        sub="member-b",
        email="b@x.com",
        periods=(_period(1, label="Other Week", status="final", provider_period_id="b-1"),),
    )
    token = sign_token(private, kid=KID, sub="member-a", email="a@x.com")

    resp = test_client.get(
        f"/api/v1/leagues/{season_a}/periods", headers=_auth(token)
    )
    assert resp.status_code == 200
    returned_ids = {uuid.UUID(p["id"]) for p in resp.json()["data"]}
    assert returned_ids == _period_ids(factory, season_a)
    assert returned_ids.isdisjoint(_period_ids(factory, season_b))


def test_empty_season_returns_empty_list(client) -> None:
    test_client, private, factory = client
    season_id = _seed_member(factory, sub="member-2", email="m2@x.com")
    token = sign_token(private, kid=KID, sub="member-2", email="m2@x.com")

    resp = test_client.get(
        f"/api/v1/leagues/{season_id}/periods", headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json() == {"data": []}
