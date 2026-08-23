"""Matchups sync against Postgres: supersession ordering + ratio rounding.

Postgres-backed (``TEST_DATABASE_URL``). Regression tests for the S1-10a review
blockers that the hermetic suite masked:

1. Supersession must mark the old row superseded *before* inserting the new live
   row — otherwise the partial unique index ``uq_matchups_live_slot`` rejects the
   insert (a transient two-live-rows state).
2. Ratio values must be rounded to the ``Numeric(10,3)`` column precision — else
   an identical resync of a league with FG%/FT% spuriously supersedes forever.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.dto import (
    ScoreboardDTO,
    ScoreboardMatchupDTO,
    ScoreboardTeamStatsDTO,
)
from backend.models.fantasy import (
    Category,
    FantasyTeam,
    FantasyTeamSeason,
    League,
    LeagueSeason,
    LeagueSeasonCategory,
    Matchup,
    MatchupCategoryResult,
    MatchupPeriod,
)
from backend.models.ingestion import IngestionRun, RawPayload
from backend.models.nba import NbaSeason
from backend.repos.ingestion import (
    IngestionRunRepository,
    ProviderRepository,
    RawPayloadRepository,
)
from backend.repos.matchups import LeagueSeasonRepository, MatchupRepository
from backend.repos.scope import LeagueSeasonScope
from backend.services.ingestion import IngestionService
from backend.services.matchups import MatchupSyncService


class _FakeAdapter:
    def __init__(self, scoreboards) -> None:
        self._scoreboards = list(scoreboards)

    def fetch_scoreboard(self, connection, season_year, provider_period_id):
        return self._scoreboards.pop(0)


def _fresh_season_year() -> int:
    """A year that won't collide: ``nba_seasons.season_year`` is unique and the
    ``db_session`` fixture does not truncate it (no user FK). Deriving from a
    UUID keeps it import-order-independent (this module is also imported by the
    standings read test, so a shared module counter would double-mint)."""
    return 2000 + (uuid.uuid4().int % 7000)


def _matchup(home: str, away: str, home_stats: dict, away_stats: dict, result: str):
    return ScoreboardMatchupDTO(
        home=ScoreboardTeamStatsDTO(provider_team_id=home, stats=home_stats),
        away=ScoreboardTeamStatsDTO(provider_team_id=away, stats=away_stats),
        provider_result=result,
    )


def _seed(db_session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a minimal league_season with two teams, one final period, and two
    scoring categories (PTS counting + FG_PCT ratio)."""
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
        scoring_type="h2h_categories",
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

    period = MatchupPeriod(
        league_season_id=season.id, ordinal=1, status="final",
        start_date=date(2098, 10, 1), end_date=date(2098, 10, 7),
        provider_period_id="1",
        finalized_at=datetime(2098, 10, 7, 12, 0, 0),
    )
    db_session.add(period)
    db_session.commit()
    return season.id, fts_a.id


def _service(db_session: Session, league_season_id: uuid.UUID) -> MatchupSyncService:
    scope = LeagueSeasonScope(league_season_id)
    ingestion = IngestionService(
        ProviderRepository(db_session),
        IngestionRunRepository(db_session),
        RawPayloadRepository(db_session),
    )
    return MatchupSyncService(
        ingestion,
        LeagueSeasonRepository(scope, db_session),
        MatchupRepository(scope, db_session),
    )


def test_differing_resync_supersedes_without_unique_violation(db_session: Session) -> None:
    season_id, _home_id = _seed(db_session)

    sb1 = ScoreboardDTO(provider_period_id="1", matchups=(
        _matchup("1", "2", {"PTS": 110.0, "fgm": 40.0, "fga": 80.0},
                 {"PTS": 100.0, "fgm": 38.0, "fga": 80.0}, "home"),
    ))
    sb2 = ScoreboardDTO(provider_period_id="1", matchups=(
        _matchup("1", "2", {"PTS": 95.0, "fgm": 36.0, "fga": 80.0},
                 {"PTS": 105.0, "fgm": 40.0, "fga": 80.0}, "away"),
    ))

    svc = _service(db_session, season_id)
    first = svc.resync_final_periods(
        connection=object(), adapter=_FakeAdapter([sb1])
    )
    second = svc.resync_final_periods(
        connection=object(), adapter=_FakeAdapter([sb2])
    )
    db_session.commit()

    assert first.created == 1
    assert second.superseded == 1

    repo = MatchupRepository(LeagueSeasonScope(season_id), db_session)
    live = repo.find_live(db_session.scalars(select(MatchupPeriod)).one().id, _home_id)
    assert live is not None
    assert live.computed_result == "away"
    assert live.superseded_at is None


def test_identical_resync_noops_with_ratio_rounding(db_session: Session) -> None:
    season_id, _home_id = _seed(db_session)

    # fgm/fga = 40/82 → 0.4878…, which rounds to 0.488 in Numeric(10,3).
    sb = ScoreboardDTO(provider_period_id="1", matchups=(
        _matchup("1", "2", {"PTS": 110.0, "fgm": 40.0, "fga": 82.0},
                 {"PTS": 100.0, "fgm": 38.0, "fga": 82.0}, "home"),
    ))

    svc = _service(db_session, season_id)
    first = svc.resync_final_periods(
        connection=object(), adapter=_FakeAdapter([sb])
    )
    second = svc.resync_final_periods(
        connection=object(), adapter=_FakeAdapter([sb])
    )
    db_session.commit()

    assert first.created == 1
    assert second.unchanged == 1
    assert second.superseded == 0


class _RaisingAdapter:
    """An adapter that fails on fetch — the triage's adapter-timeout example."""

    def fetch_scoreboard(self, connection, season_year, provider_period_id):
        raise RuntimeError("adapter timeout")


def test_failing_sync_leaves_durable_failed_run_and_no_orphans(
    db_session: Session,
) -> None:
    # charter D28: a failed job is a queryable row, not a rolled-away nothing.
    season_id, _home_id = _seed(db_session)

    svc = _service(db_session, season_id)
    with pytest.raises(RuntimeError, match="adapter timeout"):
        svc.resync_final_periods(
            connection=object(), adapter=_RaisingAdapter()
        )

    runs = db_session.scalars(
        select(IngestionRun).where(IngestionRun.league_season_id == season_id)
    ).all()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].finished_at is not None
    assert "adapter timeout" in (runs[0].error or "")

    # The work rolled back; the run did not.
    assert (
        db_session.scalars(
            select(Matchup).where(Matchup.league_season_id == season_id)
        ).all()
        == []
    )
    assert (
        db_session.scalars(
            select(RawPayload).where(RawPayload.ingestion_run_id == runs[0].id)
        ).all()
        == []
    )


def test_partial_sync_marks_run_partial_without_losing_result(db_session: Session) -> None:
    # charter D28: partial is a first-class outcome, not a silent success.
    season_id, _home_id = _seed(db_session)

    # PTS present, FG_PCT missing on both sides → one unknown category outcome.
    sb = ScoreboardDTO(provider_period_id="1", matchups=(
        _matchup("1", "2", {"PTS": 110.0}, {"PTS": 100.0}, "home"),
    ))

    svc = _service(db_session, season_id)
    summary = svc.resync_final_periods(
        connection=object(), adapter=_FakeAdapter([sb])
    )

    assert summary.unknown_categories == 1

    runs = db_session.scalars(
        select(IngestionRun).where(IngestionRun.league_season_id == season_id)
    ).all()
    assert len(runs) == 1
    assert runs[0].status == "partial"

    # The matchup and its category rows survive; the missing one is stored NULL.
    matchups = db_session.scalars(
        select(Matchup).where(Matchup.league_season_id == season_id)
    ).all()
    assert len(matchups) == 1
    null_results = db_session.scalars(
        select(MatchupCategoryResult)
        .join(Matchup, MatchupCategoryResult.matchup_id == Matchup.id)
        .where(
            Matchup.league_season_id == season_id,
            MatchupCategoryResult.result.is_(None),
        )
    ).all()
    assert len(null_results) == 1  # FG_PCT unknown; PTS intact


def test_clean_sync_commits_succeeded_durably(db_session: Session) -> None:
    # No explicit db_session.commit() here — run_scope owns the commit.
    season_id, _home_id = _seed(db_session)

    sb = ScoreboardDTO(provider_period_id="1", matchups=(
        _matchup("1", "2", {"PTS": 110.0, "fgm": 40.0, "fga": 80.0},
                 {"PTS": 100.0, "fgm": 38.0, "fga": 80.0}, "home"),
    ))

    svc = _service(db_session, season_id)
    svc.resync_final_periods(
        connection=object(), adapter=_FakeAdapter([sb])
    )

    runs = db_session.scalars(
        select(IngestionRun).where(IngestionRun.league_season_id == season_id)
    ).all()
    assert len(runs) == 1
    assert runs[0].status == "succeeded"
    assert runs[0].finished_at is not None
