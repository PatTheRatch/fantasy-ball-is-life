"""Matchups sync: normalization, supersession, idempotency (hermetic).

No database — the service is driven with in-memory fakes for the repos and a
fake adapter, so the normalization (category values incl. ratio components,
computed-vs-provider result) and the supersession/no-op decisions are tested
without Postgres.
"""

from __future__ import annotations

import uuid
from unittest.mock import Mock

from backend.domain.categories import NINE_CAT
from backend.domain.dto import (
    ScoreboardDTO,
    ScoreboardMatchupDTO,
    ScoreboardTeamStatsDTO,
)
from backend.models.fantasy import Category as ModelCategory
from backend.models.fantasy import Matchup, MatchupCategoryResult
from backend.repos.matchups import LeagueSeasonRepository
from backend.services.ingestion import IngestionService
from backend.services.matchups import MatchupSyncService


class _InMemoryMatchups:
    """A tiny in-memory MatchupRepository double."""

    def __init__(self) -> None:
        self.added: list[Matchup] = []
        self.added_results: list[MatchupCategoryResult] = []
        self._results: dict[uuid.UUID, list[MatchupCategoryResult]] = {}

    def add(self, matchup: Matchup) -> None:
        self.added.append(matchup)

    def add_category_result(self, result: MatchupCategoryResult) -> None:
        self.added_results.append(result)
        self._results.setdefault(result.matchup_id, []).append(result)

    def find_live(self, matchup_period_id: uuid.UUID, home_team_season_id: uuid.UUID):
        for m in reversed(self.added):
            if (
                m.matchup_period_id == matchup_period_id
                and m.home_team_season_id == home_team_season_id
                and m.superseded_at is None
            ):
                return m
        return None

    def category_results(self, matchup_id: uuid.UUID) -> list[MatchupCategoryResult]:
        return self._results.get(matchup_id, [])

    def flush(self) -> None:
        pass


def _model_cats():
    cats = []
    for dc in NINE_CAT:
        cats.append(
            ModelCategory(
                id=uuid.uuid4(),
                key=dc.key,
                display_name=dc.key,
                short_name=dc.short_name,
                kind=dc.kind.value,
                higher_is_better=dc.higher_is_better,
                numerator_stat=dc.numerator,
                denominator_stat=dc.denominator,
            )
        )
    return cats


def _service(cats, teams, periods, matchups, scoreboards):
    league_seasons = Mock(spec=LeagueSeasonRepository)
    season = Mock()
    season.provider_key = "espn"
    season.season_year = 2026
    league_seasons.get.return_value = season
    league_seasons.scoring_categories.return_value = cats
    league_seasons.teams_by_provider.return_value = teams
    league_seasons.final_periods.return_value = periods

    ingestion = Mock(spec=IngestionService)
    ingestion.start_run.return_value = Mock(id=uuid.uuid4(), provider_id=uuid.uuid4())

    adapter = Mock()
    adapter.fetch_scoreboard.side_effect = scoreboards

    svc = MatchupSyncService(ingestion, league_seasons, matchups)
    return svc, ingestion, adapter


def _team(team_id: str) -> Mock:
    return Mock(id=uuid.uuid4())


def _period(period_id: str, provider_id: str) -> Mock:
    return Mock(id=uuid.uuid4(), provider_period_id=provider_id)


def _matchup(home: str, away: str | None, home_stats: dict, away_stats: dict, result):
    return ScoreboardMatchupDTO(
        home=ScoreboardTeamStatsDTO(provider_team_id=home, stats=home_stats),
        away=ScoreboardTeamStatsDTO(provider_team_id=away, stats=away_stats)
        if away is not None
        else None,
        provider_result=result,
    )


def test_normalizes_matchup_and_category_results() -> None:
    cats = _model_cats()
    teams = {"1": _team("1"), "2": _team("2")}
    periods = [_period("p1", "7")]
    matchups = _InMemoryMatchups()

    home = {"PTS": 110.0, "REB": 50.0, "AST": 25.0, "STL": 8.0, "BLK": 6.0,
            "TPM": 13.0, "TO": 10.0, "fgm": 40.0, "fga": 80.0, "ftm": 20.0, "fta": 22.0}
    away = {"PTS": 100.0, "REB": 45.0, "AST": 20.0, "STL": 6.0, "BLK": 4.0,
            "TPM": 10.0, "TO": 12.0, "fgm": 38.0, "fga": 80.0, "ftm": 18.0, "fta": 22.0}
    sb = ScoreboardDTO(
        provider_period_id="7",
        matchups=(_matchup("1", "2", home, away, "home"),),
    )

    svc, ingestion, adapter = _service(cats, teams, periods, matchups, [sb])
    summary = svc.sync_league_final_periods(uuid.uuid4(), connection=Mock(), adapter=adapter)

    assert summary.matchups == 1
    assert summary.created == 1
    (m,) = matchups.added
    assert m.computed_result == "home"  # home wins 7 of 9 (TO counts against)
    assert m.provider_result == "home"
    assert m.result_source == "computed"
    assert len(matchups.added_results) == 9

    # A ratio category keeps its components so aggregation stays correct.
    by_key = {c.key: c for c in cats}
    fg = next(r for r in matchups.added_results if r.category_id == by_key["FG_PCT"].id)
    assert fg.home_numerator == 40.0
    assert fg.home_denominator == 80.0
    assert fg.home_value == 0.5

    ingestion.finish_run.assert_called_once()


def test_provider_tiebreak_when_computed_ties() -> None:
    # Two categories, one apiece → computed tie; provider names home → tiebreak.
    cats = _model_cats()[:2]  # PTS, REB
    cats = cats  # keep two
    teams = {"1": _team("1"), "2": _team("2")}
    periods = [_period("p1", "7")]
    matchups = _InMemoryMatchups()

    home = {"PTS": 110.0, "REB": 40.0}
    away = {"PTS": 100.0, "REB": 50.0}
    sb = ScoreboardDTO(
        provider_period_id="7",
        matchups=(_matchup("1", "2", home, away, "home"),),
    )

    svc, _, adapter = _service(cats, teams, periods, matchups, [sb])
    svc.sync_league_final_periods(uuid.uuid4(), connection=Mock(), adapter=adapter)

    (m,) = matchups.added
    assert m.computed_result == "tie"  # home wins PTS, away wins REB
    assert m.provider_result == "home"
    assert m.result_source == "provider_tiebreak"


def test_bye_produces_matchup_without_category_results() -> None:
    cats = _model_cats()
    teams = {"1": _team("1")}
    periods = [_period("p1", "8")]
    matchups = _InMemoryMatchups()

    sb = ScoreboardDTO(
        provider_period_id="8",
        matchups=(_matchup("1", None, {"PTS": 90.0}, {}, "home"),),
    )

    svc, _, adapter = _service(cats, teams, periods, matchups, [sb])
    svc.sync_league_final_periods(uuid.uuid4(), connection=Mock(), adapter=adapter)

    (m,) = matchups.added
    assert m.away_team_season_id is None
    assert m.computed_result is None
    assert matchups.added_results == []


def test_identical_resync_is_unchanged() -> None:
    cats = _model_cats()[:2]
    teams = {"1": _team("1"), "2": _team("2")}
    periods = [_period("p1", "7")]
    matchups = _InMemoryMatchups()

    sb = ScoreboardDTO(
        provider_period_id="7",
        matchups=(_matchup("1", "2", {"PTS": 110.0, "REB": 50.0},
                            {"PTS": 100.0, "REB": 45.0}, "home"),),
    )

    league_id = uuid.uuid4()
    svc, _, adapter = _service(cats, teams, periods, matchups, [sb, sb])
    first = svc.sync_league_final_periods(league_id, connection=Mock(), adapter=adapter)
    assert first.created == 1

    second = svc.sync_league_final_periods(league_id, connection=Mock(), adapter=adapter)
    assert second.unchanged == 1
    assert second.created == 0
    assert len(matchups.added) == 1  # no new row


def test_differing_resync_supersedes() -> None:
    cats = _model_cats()[:2]
    teams = {"1": _team("1"), "2": _team("2")}
    periods = [_period("p1", "7")]
    matchups = _InMemoryMatchups()

    sb1 = ScoreboardDTO(
        provider_period_id="7",
        matchups=(_matchup("1", "2", {"PTS": 110.0, "REB": 50.0},
                            {"PTS": 100.0, "REB": 45.0}, "home"),),
    )
    sb2 = ScoreboardDTO(
        provider_period_id="7",
        matchups=(_matchup("1", "2", {"PTS": 95.0, "REB": 40.0},
                            {"PTS": 105.0, "REB": 55.0}, "away"),),
    )

    league_id = uuid.uuid4()
    svc, _, adapter = _service(cats, teams, periods, matchups, [sb1, sb2])
    svc.sync_league_final_periods(league_id, connection=Mock(), adapter=adapter)
    second = svc.sync_league_final_periods(league_id, connection=Mock(), adapter=adapter)

    assert second.superseded == 1
    assert len(matchups.added) == 2  # old superseded + new live
    old, new = matchups.added
    assert old.superseded_at is not None
    assert old.superseded_by_id == new.id
    assert new.computed_result == "away"


def test_ratio_rounding_keeps_result_and_category_consistent() -> None:
    # 0.500 (exact) vs 0.4996 → both round to 0.500 at Numeric(10,3), so this
    # must read as a tie. Pre-fix, tally() derived from raw values (home win)
    # while compare() saw rounded values (tie), so the category rows wouldn't
    # sum to computed_result.
    cats = [c for c in _model_cats() if c.key == "FG_PCT"]
    teams = {"1": _team("1"), "2": _team("2")}
    periods = [_period("p1", "7")]
    matchups = _InMemoryMatchups()

    sb = ScoreboardDTO(
        provider_period_id="7",
        matchups=(_matchup(
            "1", "2", {"fgm": 40.0, "fga": 80.0},
            {"fgm": 4996.0, "fga": 10000.0}, None,
        ),),
    )

    svc, _, adapter = _service(cats, teams, periods, matchups, [sb])
    svc.sync_league_final_periods(uuid.uuid4(), connection=Mock(), adapter=adapter)

    (m,) = matchups.added
    (r,) = matchups.added_results
    assert m.computed_result == "tie"
    assert r.result == "tie"  # compare() and tally() agree on the rounded value
    assert r.home_value == 0.5
    assert r.away_value == 0.5
