"""ESPN adapter: map espn_api-shaped data into FCP DTOs (hermetic).

No live ESPN, no SDK import in the mapping paths. The mapping functions take a
duck-typed league-like object (built here from ``SimpleNamespace`` and the S1-03
fixtures), so the real payload shape is locked without a network.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from backend.domain.dto import PeriodType
from backend.providers.espn.adapter import (
    EspnConnection,
    _construct_league,
    _scoring_period_dates,
    map_periods,
    map_settings,
    map_teams,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load_schedule_settings() -> dict[str, dict[str, object]]:
    return json.loads((FIXTURES / "espn_schedule_settings.json").read_text())


def _load_break_window() -> dict[str, list[str] | None]:
    return json.loads((FIXTURES / "espn_pro_schedule_break_window.json").read_text())


def _fake_settings(**overrides: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = dict(
        scoring_type="H2H_CAT",
        team_count=12,
        playoff_team_count=6,
        reg_season_count=17,
        acquisition_budget=0,
        faab=False,
        matchup_periods={"1": [1], "2": [2], "18": [18]},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_team(team_id: int, name: str, abbrev: str, logo: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(team_id=team_id, team_name=name, team_abbrev=abbrev, logo_url=logo or "")


def _fake_league(
    settings: SimpleNamespace | None = None,
    teams: list[SimpleNamespace] | None = None,
    pro_schedule: dict[str, Any] | None = None,
) -> SimpleNamespace:
    league = SimpleNamespace(settings=settings or _fake_settings())
    league.teams = teams if teams is not None else []
    league._get_all_pro_schedule = lambda: pro_schedule or {}  # type: ignore[attr-defined]
    return league


CONN = EspnConnection(league_id="3853870", swid="swid", espn_s2="s2")


# --- map_settings -----------------------------------------------------------


def test_map_settings_maps_espn_surface() -> None:
    dto = map_settings(
        _fake_league(
            settings=_fake_settings(
                team_count=12, playoff_team_count=6, reg_season_count=17,
                faab=True, acquisition_budget=100,
            )
        ),
        CONN,
        2026,
    )
    assert dto.provider_league_id == "3853870"
    assert dto.season_year == 2026
    assert dto.scoring_type == "H2H_CAT"
    assert dto.team_count == 12
    assert dto.playoff_team_count == 6
    assert dto.regular_season_periods == 17
    assert dto.uses_faab is True
    assert dto.acquisition_budget == 100
    assert dto.timezone == "America/New_York"
    assert dto.roster_size is None
    assert dto.roster_slots is None


def test_map_settings_maps_zero_budget_and_no_faab_to_none() -> None:
    dto = map_settings(
        _fake_league(settings=_fake_settings(faab=False, acquisition_budget=0)),
        CONN,
        2026,
    )
    assert dto.uses_faab is False
    assert dto.acquisition_budget is None


# --- map_teams --------------------------------------------------------------


def test_map_teams_sorts_by_provider_id() -> None:
    teams = [
        _fake_team(3, "Team C", "TC"),
        _fake_team(1, "Team A", "TA", logo="http://logo/a.png"),
        _fake_team(2, "Team B", "TB"),
    ]
    dtos = map_teams(_fake_league(teams=teams))
    assert [d.provider_team_id for d in dtos] == ["1", "2", "3"]
    assert dtos[0].name == "Team A"
    assert dtos[0].abbreviation == "TA"
    assert dtos[0].logo_url == "http://logo/a.png"
    assert dtos[1].logo_url is None  # empty logo -> None
    assert dtos[0].draft_position is None


# --- map_periods ------------------------------------------------------------


def test_map_periods_derives_type_and_dates() -> None:
    pro_schedule = {
        1: {  # one team's schedule; a second team duplicates dates (deduped)
            "1": [{"date": "2025-10-21", "homeProTeamId": 1, "awayProTeamId": 2}],
            "2": [{"date": "2025-10-28"}, {"date": "2025-10-30"}],
            "18": [{"date": "2026-03-15"}],
        },
        2: {
            "1": [{"date": "2025-10-21"}],
            "2": [{"date": "2025-10-28"}],
        },
    }
    settings = _fake_settings(matchup_periods={"1": [1], "2": [2], "18": [18]}, reg_season_count=2)
    periods = map_periods(_fake_league(settings=settings, pro_schedule=pro_schedule))

    assert [p.ordinal for p in periods] == [1, 2, 18]
    assert [p.type for p in periods] == [PeriodType.REGULAR, PeriodType.REGULAR, PeriodType.PLAYOFF]
    assert (periods[0].start_date, periods[0].end_date) == (date(2025, 10, 21), date(2025, 10, 21))
    assert (periods[1].start_date, periods[1].end_date) == (date(2025, 10, 28), date(2025, 10, 30))
    assert periods[2].provider_period_id == "18"


def test_map_periods_with_no_games_has_none_dates() -> None:
    pro_schedule = {1: {"1": [{"date": "2025-10-21"}]}}
    settings = _fake_settings(matchup_periods={"1": [1], "2": [2]}, reg_season_count=2)
    periods = map_periods(_fake_league(settings=settings, pro_schedule=pro_schedule))

    assert periods[0].start_date is not None
    assert periods[1].start_date is None
    assert periods[1].end_date is None


def test_map_periods_matches_s1_03_fixture_shape() -> None:
    """The live Patriot Games mapping produces 17+3 (2025) / 19+3 (2026) periods."""
    for raw in _load_schedule_settings().values():
        regular_count = raw["matchupPeriodCount"]
        settings = _fake_settings(
            matchup_periods=raw["matchupPeriods"],  # type: ignore[arg-type]
            reg_season_count=regular_count,  # type: ignore[arg-type]
        )
        periods = map_periods(_fake_league(settings=settings, pro_schedule={}))

        total = len(raw["matchupPeriods"])  # type: ignore[arg-type]
        assert len(periods) == total
        assert [p.ordinal for p in periods] == list(range(1, total + 1))
        regular = [p for p in periods if p.type is PeriodType.REGULAR]
        playoff = [p for p in periods if p.type is PeriodType.PLAYOFF]
        assert len(regular) == regular_count
        assert len(playoff) == total - regular_count
        assert all(p.start_date is None for p in periods)  # no pro schedule supplied


# --- pro schedule / break window -------------------------------------------


def test_scoring_period_dates_handles_break_window() -> None:
    """All-Star break scoring-period ids (116–120) have no games → no dates."""
    window = _load_break_window()
    per_team = {
        "0": {
            pid: ([{"date": d} for d in dates] if dates else None)
            for pid, dates in window.items()
        }
    }
    dates = _scoring_period_dates(_fake_league(pro_schedule=per_team))

    assert dates[115] == {"2025-02-14"}
    assert dates[121] == {"2025-02-20"}
    for missing in (116, 117, 118, 119, 120):
        assert missing not in dates


# --- composition (no subclassing) ------------------------------------------


def test_construct_league_uses_composition(monkeypatch) -> None:
    import espn_api.basketball as basketball

    calls: list[tuple[int, int, str, str]] = []

    class _FakeLeague:
        def __init__(
            self,
            league_id: int,
            year: int,
            espn_s2: str | None = None,
            swid: str | None = None,
        ) -> None:
            calls.append((league_id, year, espn_s2 or "", swid or ""))

    monkeypatch.setattr(basketball, "League", _FakeLeague)
    _construct_league(CONN, 2026)

    assert calls == [(3853870, 2026, "s2", "swid")]
