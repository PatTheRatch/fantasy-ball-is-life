"""Standings read path against Postgres: fold + superseded exclusion.

Postgres-backed (``TEST_DATABASE_URL``). Reuses the S1-10a sync seeding to
create real ``matchups`` + ``matchup_category_results`` rows, then folds them
through ``StandingsReadService`` and asserts the *live* rows win — a superseded
row must not leak into the table.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from backend.domain.dto import ScoreboardDTO
from backend.repos.matchups import LeagueSeasonRepository, MatchupRepository
from backend.services.standings_read import StandingsReadService
from tests.services.test_matchups_sync_postgres import (
    _FakeAdapter,
    _matchup,
    _seed,
    _service,
)


def test_folds_live_matchups_and_excludes_superseded(db_session: Session) -> None:
    season_id, home_id = _seed(db_session)

    # sb1: home (team 1) wins both categories. sb2: away (team 2) wins both.
    sb1 = ScoreboardDTO(provider_period_id="1", matchups=(
        _matchup("1", "2", {"PTS": 110.0, "fgm": 40.0, "fga": 80.0},
                 {"PTS": 100.0, "fgm": 38.0, "fga": 80.0}, "home"),
    ))
    sb2 = ScoreboardDTO(provider_period_id="1", matchups=(
        _matchup("1", "2", {"PTS": 95.0, "fgm": 36.0, "fga": 80.0},
                 {"PTS": 105.0, "fgm": 40.0, "fga": 80.0}, "away"),
    ))

    sync = _service(db_session)
    sync.sync_league_final_periods(season_id, connection=object(), adapter=_FakeAdapter([sb1]))
    sync.sync_league_final_periods(season_id, connection=object(), adapter=_FakeAdapter([sb2]))
    db_session.commit()

    read = StandingsReadService(
        LeagueSeasonRepository(db_session), MatchupRepository(db_session)
    )
    out = read.standings(season_id)

    assert out.as_of == date(2098, 10, 7)  # the seeded final period's end_date
    assert out.freshness == "final"
    assert out.stale is False

    by_id = {r.team_id: r for r in out.rows}
    assert len(out.rows) == 2
    # The live (sb2) result: home lost both categories. If the superseded sb1
    # row leaked in, home would have picked up wins and this would be 2-2.
    home_row = by_id[home_id]
    assert (home_row.wins, home_row.losses) == (0, 2)
    assert home_row.rank == 2

    away_row = next(r for r in out.rows if r.team_id != home_id)
    assert (away_row.wins, away_row.losses) == (2, 0)
    assert away_row.rank == 1
