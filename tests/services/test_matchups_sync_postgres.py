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
from datetime import date

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
    MatchupPeriod,
)
from backend.models.nba import NbaSeason
from backend.repos.ingestion import (
    IngestionRunRepository,
    ProviderRepository,
    RawPayloadRepository,
)
from backend.repos.matchups import LeagueSeasonRepository, MatchupRepository
from backend.services.ingestion import IngestionService
from backend.services.matchups import MatchupSyncService


class _FakeAdapter:
    def __init__(self, scoreboards) -> None:
        self._scoreboards = list(scoreboards)

    def fetch_scoreboard(self, connection, season_year, provider_period_id):
        return self._scoreboards.pop(0)


#: ``nba_seasons.season_year`` is unique and the ``db_session`` fixture does not
#: truncate it (no user FK), so each seed uses a fresh monotonically-increasing
#: year to avoid collisions across tests in the same run.
_next_season_year = 3000


def _matchup(home: str, away: str, home_stats: dict, away_stats: dict, result: str):
    return ScoreboardMatchupDTO(
        home=ScoreboardTeamStatsDTO(provider_team_id=home, stats=home_stats),
        away=ScoreboardTeamStatsDTO(provider_team_id=away, stats=away_stats),
        provider_result=result,
    )


def _seed(db_session: Session) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed a minimal league_season with two teams, one final period, and two
    scoring categories (PTS counting + FG_PCT ratio)."""
    global _next_season_year
    _next_season_year += 1
    season_year = _next_season_year
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
    )
    db_session.add(period)
    db_session.commit()
    return season.id, fts_a.id


def _service(db_session: Session) -> MatchupSyncService:
    ingestion = IngestionService(
        ProviderRepository(db_session),
        IngestionRunRepository(db_session),
        RawPayloadRepository(db_session),
    )
    return MatchupSyncService(
        ingestion,
        LeagueSeasonRepository(db_session),
        MatchupRepository(db_session),
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

    svc = _service(db_session)
    first = svc.sync_league_final_periods(
        season_id, connection=object(), adapter=_FakeAdapter([sb1])
    )
    second = svc.sync_league_final_periods(
        season_id, connection=object(), adapter=_FakeAdapter([sb2])
    )
    db_session.commit()

    assert first.created == 1
    assert second.superseded == 1

    repo = MatchupRepository(db_session)
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

    svc = _service(db_session)
    first = svc.sync_league_final_periods(
        season_id, connection=object(), adapter=_FakeAdapter([sb])
    )
    second = svc.sync_league_final_periods(
        season_id, connection=object(), adapter=_FakeAdapter([sb])
    )
    db_session.commit()

    assert first.created == 1
    assert second.unchanged == 1
    assert second.superseded == 0
