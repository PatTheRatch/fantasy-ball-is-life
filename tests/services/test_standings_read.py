"""Standings read path (hermetic): fold, byes, empty season, as-of, through.

No database — the service is driven with ``Mock`` repos returning plain data
objects, so the fold (counting stored category ``result`` rows, byes, ``as_of``
scoping) is tested without Postgres.
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

from backend.repos.matchups import LeagueSeasonRepository, MatchupRepository
from backend.services.standings_read import StandingsReadService


def _period(ordinal: int, end_date: date) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), ordinal=ordinal, end_date=end_date)


def _team(team_id: uuid.UUID, name: str, abbrev: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=team_id, name=name, abbreviation=abbrev)


def _matchup(home_id: uuid.UUID, away_id: uuid.UUID | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), home_team_season_id=home_id, away_team_season_id=away_id
    )


def _cat_result(matchup_id: uuid.UUID, result: str) -> SimpleNamespace:
    return SimpleNamespace(matchup_id=matchup_id, result=result)


def _service(periods, teams, matchups, category_results) -> StandingsReadService:
    league_seasons = Mock(spec=LeagueSeasonRepository)
    league_seasons.final_periods.return_value = periods
    league_seasons.teams.return_value = teams

    matchups_repo = Mock(spec=MatchupRepository)
    matchups_repo.live_for_season.return_value = matchups
    matchups_repo.category_results_for.return_value = category_results

    return StandingsReadService(league_seasons, matchups_repo)


def test_folds_category_records_into_ranked_table() -> None:
    a = uuid.uuid4()
    b = uuid.uuid4()
    period = _period(1, date(2026, 1, 11))
    m = _matchup(a, b)
    # 9 categories: 6 home wins, 2 away wins, 1 tie.
    results = (
        [_cat_result(m.id, "home")] * 6
        + [_cat_result(m.id, "away")] * 2
        + [_cat_result(m.id, "tie")]
    )

    svc = _service([period], [_team(a, "A", "TA"), _team(b, "B", "TB")], [m], results)
    out = svc.standings(uuid.uuid4())

    assert out.freshness == "final"
    assert out.stale is False
    assert out.as_of == date(2026, 1, 11)
    first, second = out.rows
    assert first.team_id == a
    assert first.rank == 1
    assert (first.wins, first.losses, first.ties) == (6, 2, 1)
    assert first.win_pct == 72.2
    assert first.played == 9
    assert first.team_name == "A"
    assert second.team_id == b
    assert (second.wins, second.losses, second.ties) == (2, 6, 1)


def test_bye_team_still_appears_with_zero_record() -> None:
    a = uuid.uuid4()
    b = uuid.uuid4()
    period = _period(1, date(2026, 1, 11))
    bye = _matchup(a, None)  # A has a bye — no opponent, no category rows

    svc = _service(
        [period],
        [_team(a, "A"), _team(b, "B")],
        [bye],
        [],  # no category results for a bye
    )
    out = svc.standings(uuid.uuid4())

    (row,) = out.rows  # only A appears; B never played and is absent
    assert row.team_id == a
    assert (row.wins, row.losses, row.ties) == (0, 0, 0)
    assert row.win_pct == 0.0


def test_empty_season_returns_empty_table_and_null_as_of() -> None:
    svc = _service([], [], [], [])
    out = svc.standings(uuid.uuid4())

    assert out.rows == ()
    assert out.as_of is None
    assert out.freshness == "final"
    assert out.stale is False


def test_through_period_filters_periods_and_scopes_as_of() -> None:
    a = uuid.uuid4()
    b = uuid.uuid4()
    p1 = _period(1, date(2026, 1, 11))
    p2 = _period(2, date(2026, 1, 18))
    m = _matchup(a, b)

    league_seasons = Mock(spec=LeagueSeasonRepository)
    league_seasons.final_periods.return_value = [p1, p2]
    league_seasons.teams.return_value = [_team(a, "A"), _team(b, "B")]

    matchups_repo = Mock(spec=MatchupRepository)
    matchups_repo.live_for_season.return_value = [m]
    matchups_repo.category_results_for.return_value = [_cat_result(m.id, "home")]

    svc = StandingsReadService(league_seasons, matchups_repo)
    out = svc.standings(uuid.uuid4(), through_period=1)

    # as_of scoped to the *included* period (p1), not the global latest (p2).
    assert out.as_of == date(2026, 1, 11)
    # the service delegates the period filter to the repo as a period_ids set.
    _, kwargs = matchups_repo.live_for_season.call_args
    assert kwargs["period_ids"] == [p1.id]
