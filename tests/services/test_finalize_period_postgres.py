"""D-02 period finality producer: finalize + resync against Postgres.

Postgres-backed (``TEST_DATABASE_URL``). The finalize path is the only code path
that writes ``status='final'``; these tests pin grace, timezone, the
commit-per-period resumability, the break/no-partial rule, and the already-final
no-refetch guarantee.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.dto import ScoreboardDTO
from backend.models.fantasy import (
    Category,
    FantasyTeam,
    FantasyTeamSeason,
    League,
    LeagueSeason,
    LeagueSeasonCategory,
    Matchup,
    MatchupPeriod,
)
from backend.models.ingestion import IngestionRun
from backend.models.nba import NbaSeason
from tests.services.test_matchups_sync_postgres import (
    _FakeAdapter,
    _fresh_season_year,
    _matchup,
    _service,
)

# A scoring period's start_date is a week before its end_date (dates_ordered).
_WEEK = timedelta(days=6)


def _seed_season(
    db_session: Session,
    *,
    timezone: str = "UTC",
    periods: list[tuple[int, date, str, str]],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a league_season with two teams, two categories, and *scheduled*
    periods. Returns ``(season_id, home_team_season_id)``.

    ``periods`` is ``(ordinal, end_date, provider_period_id, type)`` — status is
    always ``scheduled`` so the finalize path has something to do.
    """
    season_year = _fresh_season_year()
    nba = NbaSeason(
        season_year=season_year, label=f"test {season_year}",
        start_date=date(season_year - 1, 10, 1), end_date=date(season_year, 6, 1),
    )
    league = League(slug=f"test-{uuid.uuid4().hex[:8]}", name="Test League")
    db_session.add_all([nba, league])
    db_session.flush()

    season = LeagueSeason(
        league_id=league.id, nba_season_id=nba.id, season_year=season_year,
        status="active", provider_key="espn", provider_league_id="999",
        scoring_type="h2h_categories", timezone=timezone,
    )
    db_session.add(season)
    db_session.flush()

    cats = {
        c.key: c
        for c in db_session.scalars(
            select(Category).where(Category.key.in_(["PTS", "FG_PCT"]))
        )
    }
    db_session.add_all([
        LeagueSeasonCategory(
            league_season_id=season.id, category_id=cats["PTS"].id, ordinal=0
        ),
        LeagueSeasonCategory(
            league_season_id=season.id, category_id=cats["FG_PCT"].id, ordinal=1
        ),
    ])

    team_a = FantasyTeam(league_id=league.id)
    team_b = FantasyTeam(league_id=league.id)
    db_session.add_all([team_a, team_b])
    db_session.flush()

    fts_a = FantasyTeamSeason(
        fantasy_team_id=team_a.id, league_season_id=season.id,
        name="A", provider_team_id="1",
    )
    fts_b = FantasyTeamSeason(
        fantasy_team_id=team_b.id, league_season_id=season.id,
        name="B", provider_team_id="2",
    )
    db_session.add_all([fts_a, fts_b])
    db_session.flush()

    for ordinal, end_date, provider_period_id, ptype in periods:
        db_session.add(
            MatchupPeriod(
                league_season_id=season.id, ordinal=ordinal, status="scheduled",
                type=ptype, start_date=end_date - _WEEK, end_date=end_date,
                provider_period_id=provider_period_id,
            )
        )
    db_session.commit()
    return season.id, fts_a.id


def _scoreboard(home_stats: dict, away_stats: dict, result: str) -> ScoreboardDTO:
    return ScoreboardDTO(
        provider_period_id="1",
        matchups=(_matchup("1", "2", home_stats, away_stats, result),),
    )


# --- the happy path ----------------------------------------------------------


def test_eligible_period_finalizes(db_session: Session) -> None:
    end = date(2025, 10, 28)
    season_id, _ = _seed_season(db_session, periods=[(1, end, "1", "regular")])
    adapter = _FakeAdapter([
        _scoreboard({"PTS": 110.0, "fgm": 40.0, "fga": 80.0},
                    {"PTS": 100.0, "fgm": 38.0, "fga": 80.0}, "home"),
    ])
    svc = _service(db_session, season_id)

    summary = svc.finalize_eligible_periods(
        connection=object(), adapter=adapter,
        now=datetime(2025, 11, 1, 0, 0, tzinfo=UTC),
    )

    assert summary.finalized == 1
    period = db_session.scalars(
        select(MatchupPeriod).where(MatchupPeriod.league_season_id == season_id)
    ).one()
    assert period.status == "final"
    assert period.finalized_at is not None
    assert db_session.scalars(
        select(Matchup).where(Matchup.league_season_id == season_id)
    ).one().computed_result == "home"


# --- grace + timezone (the trap tests) ---------------------------------------


def test_inside_grace_window_does_not_finalize(db_session: Session) -> None:
    end = date(2025, 10, 28)
    season_id, _ = _seed_season(db_session, periods=[(1, end, "1", "regular")])
    adapter = _FakeAdapter([])
    svc = _service(db_session, season_id)

    # 12h past end-of-day, inside the 48h grace → not eligible.
    summary = svc.finalize_eligible_periods(
        connection=object(), adapter=adapter,
        now=datetime(2025, 10, 29, 12, 0, tzinfo=UTC), grace_hours=48,
    )

    assert summary.finalized == 0
    assert summary.skipped_ineligible == 1
    assert adapter._scoreboards == []  # never fetched


def test_timezone_boundary_does_not_finalize(db_session: Session) -> None:
    # end_date has passed in UTC but not in America/Los_Angeles (UTC-8).
    end = date(2025, 10, 28)
    season_id, _ = _seed_season(
        db_session, timezone="America/Los_Angeles", periods=[(1, end, "1", "regular")]
    )
    adapter = _FakeAdapter([])
    svc = _service(db_session, season_id)

    # 2025-10-29 06:00 UTC == 2025-10-28 22:00 in LA — the period's end-of-day
    # (10-29 00:00 LA == 10-29 08:00 UTC) has not arrived yet in league time.
    summary = svc.finalize_eligible_periods(
        connection=object(), adapter=adapter,
        now=datetime(2025, 10, 29, 6, 0, tzinfo=UTC), grace_hours=0,
    )

    assert summary.finalized == 0
    assert summary.skipped_ineligible == 1


# --- already-final is never refetched ----------------------------------------


def test_already_final_is_not_refetched(db_session: Session) -> None:
    end = date(2025, 10, 28)
    season_id, _ = _seed_season(db_session, periods=[(1, end, "1", "regular")])

    period = db_session.scalars(
        select(MatchupPeriod).where(MatchupPeriod.league_season_id == season_id)
    ).one()
    period.status = "final"
    period.finalized_at = datetime(2025, 10, 29, tzinfo=UTC)
    db_session.commit()

    adapter = _FakeAdapter([])
    svc = _service(db_session, season_id)
    summary = svc.finalize_eligible_periods(
        connection=object(), adapter=adapter,
        now=datetime(2025, 11, 1, tzinfo=UTC),
    )

    assert summary.finalized == 0
    assert summary.skipped_final == 1
    assert adapter._scoreboards == []  # fetch_scoreboard never called


# --- break + missing categories ----------------------------------------------


def test_break_period_finalizes_with_zero_matchups_not_partial(db_session: Session) -> None:
    end = date(2025, 2, 20)  # All-Star break
    season_id, _ = _seed_season(db_session, periods=[(1, end, "10", "break")])
    adapter = _FakeAdapter([ScoreboardDTO(provider_period_id="10", matchups=())])
    svc = _service(db_session, season_id)

    summary = svc.finalize_eligible_periods(
        connection=object(), adapter=adapter,
        now=datetime(2025, 2, 25, tzinfo=UTC),
    )

    assert summary.finalized == 1
    assert summary.unknowns == 0
    period = db_session.scalars(
        select(MatchupPeriod).where(MatchupPeriod.league_season_id == season_id)
    ).one()
    assert period.status == "final"
    run = db_session.scalars(
        select(IngestionRun).where(IngestionRun.league_season_id == season_id)
    ).one()
    assert run.status == "succeeded"  # an empty break is complete, not partial


def test_missing_categories_finalizes_and_marks_partial(db_session: Session) -> None:
    end = date(2025, 10, 28)
    season_id, _ = _seed_season(db_session, periods=[(1, end, "1", "regular")])
    adapter = _FakeAdapter([
        _scoreboard({"PTS": 110.0}, {"PTS": 100.0}, "home"),  # FG_PCT missing
    ])
    svc = _service(db_session, season_id)

    summary = svc.finalize_eligible_periods(
        connection=object(), adapter=adapter,
        now=datetime(2025, 11, 1, tzinfo=UTC),
    )

    assert summary.finalized == 1
    assert summary.unknowns == 1
    period = db_session.scalars(
        select(MatchupPeriod).where(MatchupPeriod.league_season_id == season_id)
    ).one()
    assert period.status == "final"
    run = db_session.scalars(
        select(IngestionRun).where(IngestionRun.league_season_id == season_id)
    ).one()
    assert run.status == "partial"


# --- resumability (commit per period) ----------------------------------------


class _RaisingOnPeriod:
    """Fails on the Nth fetch, serves scoreboards before that."""

    def __init__(self, fail_on: str) -> None:
        self.fail_on = fail_on

    def fetch_scoreboard(self, connection, season_year, provider_period_id):
        if provider_period_id == self.fail_on:
            raise RuntimeError("adapter timeout")
        return _scoreboard(
            {"PTS": 110.0, "fgm": 40.0, "fga": 80.0},
            {"PTS": 100.0, "fgm": 38.0, "fga": 80.0}, "home",
        )


def test_mid_run_failure_is_resumable(db_session: Session) -> None:
    end = date(2025, 10, 28)
    periods = [(i, end + timedelta(days=i - 1), str(i), "regular") for i in range(1, 6)]
    season_id, _ = _seed_season(db_session, periods=periods)
    svc = _service(db_session, season_id)

    with pytest.raises(RuntimeError, match="adapter timeout"):
        svc.finalize_eligible_periods(
            connection=object(), adapter=_RaisingOnPeriod("3"),
            now=datetime(2025, 11, 10, tzinfo=UTC),
        )

    # Periods 1-2 are final and committed; 3-5 are still scheduled.
    statuses = {
        p.ordinal: p.status
        for p in db_session.scalars(
            select(MatchupPeriod).where(MatchupPeriod.league_season_id == season_id)
        )
    }
    assert statuses == {1: "final", 2: "final", 3: "scheduled", 4: "scheduled", 5: "scheduled"}

    run = db_session.scalars(
        select(IngestionRun).where(IngestionRun.league_season_id == season_id)
    ).one()
    assert run.status == "failed"

    # A re-run (adapter recovered) completes the rest.
    recovered = _FakeAdapter([
        _scoreboard({"PTS": 110.0, "fgm": 40.0, "fga": 80.0},
                    {"PTS": 100.0, "fgm": 38.0, "fga": 80.0}, "home")
        for _ in range(3)
    ])
    summary = svc.finalize_eligible_periods(
        connection=object(), adapter=recovered, now=datetime(2025, 11, 10, tzinfo=UTC)
    )
    assert summary.finalized == 3  # periods 3, 4, 5
    remaining = {
        p.ordinal: p.status
        for p in db_session.scalars(
            select(MatchupPeriod).where(MatchupPeriod.league_season_id == season_id)
        )
    }
    assert all(s == "final" for s in remaining.values())


# --- resync never touches status ---------------------------------------------


def test_resync_does_not_change_status(db_session: Session) -> None:
    end = date(2025, 10, 28)
    season_id, _ = _seed_season(db_session, periods=[(1, end, "1", "regular")])
    svc = _service(db_session, season_id)

    # Finalize it first (via the one allowed path), then resync it.
    svc.finalize_eligible_periods(
        connection=object(), adapter=_FakeAdapter([
            _scoreboard({"PTS": 110.0, "fgm": 40.0, "fga": 80.0},
                        {"PTS": 100.0, "fgm": 38.0, "fga": 80.0}, "home"),
        ]),
        now=datetime(2025, 11, 1, tzinfo=UTC),
    )
    before = db_session.scalars(
        select(MatchupPeriod).where(MatchupPeriod.league_season_id == season_id)
    ).one()
    assert before.status == "final"

    svc.resync_final_periods(connection=object(), adapter=_FakeAdapter([
        _scoreboard({"PTS": 95.0, "fgm": 36.0, "fga": 80.0},
                    {"PTS": 105.0, "fgm": 40.0, "fga": 80.0}, "away"),
    ]))

    after = db_session.scalars(
        select(MatchupPeriod).where(MatchupPeriod.league_season_id == season_id)
    ).one()
    assert after.status == "final"  # unchanged
    assert after.finalized_at == before.finalized_at  # resync did not re-stamp
