"""D-03 claim + CLI end-to-end, against Postgres (fake adapter, no ESPN).

Runs only when ``TEST_DATABASE_URL`` is set. The claim's invariants are the ones
that bite in the dark: a user is never created, the link is idempotent, the
membership chain closes, and the CLI lists teams (rather than requiring a DB
query) when it cannot proceed.
"""

from __future__ import annotations

import io

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.domain.dto import ScoreboardDTO
from backend.models.fantasy import LeagueSeason
from backend.models.identity import ManagerUserLink, User
from backend.providers.espn.adapter import EspnConnection
from backend.repos.claim import ClaimRepository
from backend.repos.membership import LeagueMembershipRepository
from backend.services.claim import LeagueClaimService, UnknownUserError
from scripts.sync_league import run
from tests.services.test_league_bootstrap_postgres import (
    _clean,
    _periods,
    _seed_nba_season,
    _settings,
    _teams,
)
from tests.services.test_league_bootstrap_postgres import (
    _FakeAdapter as _BootstrapFakeAdapter,
)
from tests.services.test_league_bootstrap_postgres import (
    _service as _bootstrap_service,
)
from tests.services.test_matchups_sync_postgres import _matchup

SEASON_YEAR = 2026


def _count(db_session: Session, model: type) -> int:
    return db_session.scalar(select(func.count()).select_from(model)) or 0


def _conn() -> EspnConnection:
    return EspnConnection(league_id="3853870", swid="{SWID}", espn_s2="{S2}")


class _CombinedAdapter:
    """One adapter for the whole pipeline (settings/teams/periods + scoreboards)."""

    def fetch_settings(self, connection, season_year):
        return _settings(categories=("PTS", "FG_PCT"))

    def fetch_teams(self, connection, season_year):
        return _teams()

    def fetch_periods(self, connection, season_year):
        return _periods()

    def fetch_scoreboard(self, connection, season_year, provider_period_id):
        return ScoreboardDTO(
            provider_period_id=provider_period_id,
            matchups=(
                _matchup(
                    "1", "2",
                    {"PTS": 110.0, "fgm": 40.0, "fga": 80.0},
                    {"PTS": 100.0, "fgm": 38.0, "fga": 80.0}, "home",
                ),
            ),
        )


def _bootstrap(db_session: Session):
    _clean(db_session)
    _seed_nba_season(db_session)
    adapter = _BootstrapFakeAdapter(_settings(), _teams(), _periods())
    _bootstrap_service(db_session, adapter).bootstrap(object(), SEASON_YEAR)
    return db_session.scalar(select(LeagueSeason.id))


def _make_user(db_session: Session, email: str = "patrick@example.com") -> User:
    user = User(auth_subject=f"auth-{email}", email=email, display_name="Patrick")
    db_session.add(user)
    db_session.commit()
    return user


# --- the claim service -------------------------------------------------------


def test_claim_creates_one_link_and_is_idempotent(db_session: Session) -> None:
    season_id = _bootstrap(db_session)
    user = _make_user(db_session)
    svc = LeagueClaimService(ClaimRepository(db_session))

    first = svc.claim(season_id, user.email, "1")
    assert first.created is True
    assert first.team_name == "Ballers"
    assert _count(db_session, ManagerUserLink) == 1

    second = svc.claim(season_id, user.email, "1")
    assert second.created is False
    assert _count(db_session, ManagerUserLink) == 1  # no second row, no crash


def test_claim_makes_the_user_a_member(db_session: Session) -> None:
    season_id = _bootstrap(db_session)
    user = _make_user(db_session)
    LeagueClaimService(ClaimRepository(db_session)).claim(season_id, user.email, "1")

    assert LeagueMembershipRepository(db_session).is_member(season_id, user.id) is True


def test_claim_unknown_email_fails_and_creates_no_user(db_session: Session) -> None:
    season_id = _bootstrap(db_session)
    before = _count(db_session, User)

    with pytest.raises(UnknownUserError, match="sign in once"):
        LeagueClaimService(ClaimRepository(db_session)).claim(
            season_id, "nobody@example.com", "1"
        )

    assert _count(db_session, User) == before  # the CLI never creates a user


# --- the CLI end-to-end ------------------------------------------------------


def test_run_end_to_end_claims_and_prints_the_url(db_session: Session) -> None:
    _clean(db_session)
    _seed_nba_season(db_session)
    user = _make_user(db_session)

    out, err = io.StringIO(), io.StringIO()
    code = run(
        db_session, _conn(), SEASON_YEAR,
        adapter=_CombinedAdapter(),
        claim_email=user.email, claim_team="1",
        out=out, err=err,
    )

    assert code == 0
    season_id = db_session.scalar(select(LeagueSeason.id))
    assert f"/leagues/{season_id}" in out.getvalue()  # the URL is the deliverable
    assert "Ballers" in out.getvalue()
    assert "Runs        league_bootstrap succeeded · finalize succeeded" in out.getvalue()
    assert LeagueMembershipRepository(db_session).is_member(season_id, user.id) is True


def test_run_with_claim_email_but_no_team_lists_teams(db_session: Session) -> None:
    _clean(db_session)
    _seed_nba_season(db_session)

    out, err = io.StringIO(), io.StringIO()
    code = run(
        db_session, _conn(), SEASON_YEAR,
        adapter=_CombinedAdapter(),
        claim_email="patrick@example.com", claim_team=None,
        out=out, err=err,
    )

    assert code == 2  # non-zero: the CLI is self-describing, not silently stuck
    assert "Ballers" in err.getvalue()
    assert "Scorers" in err.getvalue()
    assert "--claim-team" in err.getvalue()


def test_run_rerunning_the_whole_command_changes_nothing(db_session: Session) -> None:
    _clean(db_session)
    _seed_nba_season(db_session)
    user = _make_user(db_session)

    first = run(
        db_session, _conn(), SEASON_YEAR,
        adapter=_CombinedAdapter(),
        claim_email=user.email, claim_team="1",
        out=io.StringIO(), err=io.StringIO(),
    )
    links_after_first = _count(db_session, ManagerUserLink)

    second = run(
        db_session, _conn(), SEASON_YEAR,
        adapter=_CombinedAdapter(),
        claim_email=user.email, claim_team="1",
        out=io.StringIO(), err=io.StringIO(),
    )

    assert first == 0
    assert second == 0
    assert _count(db_session, ManagerUserLink) == links_after_first == 1
