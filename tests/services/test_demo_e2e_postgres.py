"""The demo path, end to end: bootstrap → finalize → standings.

Postgres-backed (``TEST_DATABASE_URL``). The one test that proves the demo works:
D-01's bootstrap creates the league, D-02's finalize produces finality, and
``StandingsReadService`` folds it into a populated table — no "not synced".
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.domain.dto import (
    LeagueSettingsDTO,
    MatchupPeriodDTO,
    PeriodType,
    ScoreboardDTO,
    TeamDTO,
    TeamOwnerDTO,
)
from backend.models.fantasy import LeagueSeason
from backend.repos.matchups import LeagueSeasonRepository, MatchupRepository
from backend.repos.scope import LeagueSeasonScope
from backend.services.standings_read import StandingsReadService
from tests.services.test_league_bootstrap_postgres import (
    _seed_nba_season,
)
from tests.services.test_league_bootstrap_postgres import (
    _service as _bootstrap_service,
)
from tests.services.test_matchups_sync_postgres import (
    _FakeAdapter,
    _matchup,
)
from tests.services.test_matchups_sync_postgres import (
    _service as _matchup_service,
)


class _BootstrapAdapter:
    def fetch_settings(self, connection, season_year):
        return LeagueSettingsDTO(
            provider_league_id="3853870",
            name="Patriot Games",
            season_year=season_year,
            scoring_type="h2h_categories",
            timezone="UTC",
            categories=("PTS", "FG_PCT"),
        )

    def fetch_teams(self, connection, season_year):
        return [
            TeamDTO(
                provider_team_id="1", name="Ballers",
                owners=(TeamOwnerDTO("{GUID-1}", "Patrick"),),
            ),
            TeamDTO(
                provider_team_id="2", name="Scorers",
                owners=(TeamOwnerDTO("{GUID-2}", "Mike"),),
            ),
        ]

    def fetch_periods(self, connection, season_year):
        return [
            MatchupPeriodDTO(
                ordinal=1, type=PeriodType.REGULAR, provider_period_id="1",
                start_date=date(2025, 10, 21), end_date=date(2025, 10, 27),
            ),
        ]


def test_bootstrap_finalize_standings_populated(db_session: Session) -> None:
    _seed_nba_season(db_session, season_year=2026)

    # D-01: bootstrap creates the league (periods scheduled, managers unclaimed).
    bootstrap = _bootstrap_service(db_session, _BootstrapAdapter())
    bootstrap.bootstrap(object(), 2026)

    season_id = db_session.scalar(select(LeagueSeason.id))
    assert season_id is not None

    # D-02: finalize flips the period final and persists its matchups.
    finalize = _matchup_service(db_session, season_id)
    finalize.finalize_eligible_periods(
        connection=object(),
        adapter=_FakeAdapter([
            ScoreboardDTO(
                provider_period_id="1",
                matchups=(
                    _matchup(
                        "1", "2",
                        {"PTS": 110.0, "fgm": 40.0, "fga": 80.0},
                        {"PTS": 100.0, "fgm": 38.0, "fga": 80.0}, "home",
                    ),
                ),
            )
        ]),
        now=datetime(2025, 11, 1, tzinfo=UTC),
    )

    # The standings fold now returns a real table, not "not synced".
    scope = LeagueSeasonScope(season_id)
    read = StandingsReadService(
        LeagueSeasonRepository(scope, db_session), MatchupRepository(scope, db_session)
    )
    out = read.standings()

    assert out.rows  # populated, not empty
    assert out.freshness == "final"
    assert out.complete is True
    by_name = {r.team_name: r for r in out.rows}
    assert by_name["Ballers"].rank == 1
    assert (by_name["Ballers"].wins, by_name["Ballers"].losses) == (2, 0)
    assert by_name["Scorers"].rank == 2
    assert (by_name["Scorers"].wins, by_name["Scorers"].losses) == (0, 2)
