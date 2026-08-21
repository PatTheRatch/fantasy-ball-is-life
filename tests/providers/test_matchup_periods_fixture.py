"""S1-03 live check: the real ``matchupPeriods`` shape, locked as a fixture.

Captured against the live Patriot Games league (ESPN 3853870) on both the
completed 2025 season and the upcoming 2026 season. This resolves the open
question at the end of the provider-ingestion design's "headline finding":
`matchupPeriods` is populated, and — contrary to the design's example payload —
this league uses ``matchupPeriodLength: 1``, so the mapping is 1:1, not
many-to-one.

See docs/v2/S1-03_LIVE_CHECK_FINDINGS.md for the full write-up.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "espn_schedule_settings.json"


def _load() -> dict[str, dict[str, object]]:
    return json.loads(FIXTURE.read_text())


# --- shape: keys are strings, values are int lists --------------------------


def test_matchup_periods_is_a_string_keyed_dict() -> None:
    for settings in _load().values():
        periods = settings["matchupPeriods"]
        assert isinstance(periods, dict)
        assert all(isinstance(k, str) for k in periods), "keys must be strings"


def test_matchup_period_values_are_int_lists() -> None:
    for settings in _load().values():
        periods = settings["matchupPeriods"]
        assert all(isinstance(v, list) for v in periods.values())
        assert all(
            isinstance(x, int) for v in periods.values() for x in v
        ), "scoring-period ids must be ints"


# --- the finding that differs from the design doc's example -----------------


def test_matchup_period_length_is_one() -> None:
    """This league maps each matchup period to exactly one scoring period.

    The design doc's representative payload was ``{'1': [1,2,3,4,5,6], …}``
    (a weekly league). Live data shows ``matchupPeriodLength: 1`` — 1:1.
    """
    for season, settings in _load().items():
        assert settings["matchupPeriodLength"] == 1, f"season {season}"


def test_matchup_periods_is_identity_mapping() -> None:
    """With length 1, period N maps to [N] — an identity mapping."""
    for settings in _load().values():
        periods = settings["matchupPeriods"]
        for key, scoring_periods in periods.items():
            assert scoring_periods == [int(key)], f"period {key}"


# --- playoff periods are included -------------------------------------------


def test_playoff_periods_are_present() -> None:
    """Playoff/championship periods are part of the mapping, not separate."""
    for season, settings in _load().items():
        count = settings["matchupPeriodCount"]
        total = len(settings["matchupPeriods"])
        assert total > count, (
            f"season {season}: expected playoff periods beyond the "
            f"{count} regular-season matchups, got {total} total"
        )


def test_regular_and_playoff_periods_partition_cleanly() -> None:
    """Regular periods are 1..matchupPeriodCount; the rest are playoff.

    This is the split S1-06 needs to derive ``kind`` from: index <=
    ``matchupPeriodCount`` is regular, index > it is playoff.
    """
    for season, settings in _load().items():
        count = settings["matchupPeriodCount"]
        periods = settings["matchupPeriods"]
        total = len(periods)
        keys = {int(k) for k in periods}
        assert keys == set(range(1, total + 1)), f"season {season} keys not 1..N"
        regular = {int(k) for k in periods if int(k) <= count}
        playoff = {int(k) for k in periods if int(k) > count}
        assert regular == set(range(1, count + 1)), f"season {season} regular"
        assert playoff == set(range(count + 1, total + 1)), f"season {season} playoff"


# --- field presence (what S1-06 schema will consume) ------------------------


def test_schedule_settings_has_required_fields() -> None:
    required = {
        "matchupPeriodCount",
        "matchupPeriodLength",
        "matchupPeriods",
        "periodTypeId",
        "playoffMatchupPeriodLength",
        "playoffTeamCount",
    }
    for season, settings in _load().items():
        assert required <= set(settings), f"season {season} missing fields"


# --- pro schedule: the All-Star break is absent ids, not a period ------------


def _load_break_window() -> dict[str, list[str] | None]:
    path = Path(__file__).parent / "fixtures" / "espn_pro_schedule_break_window.json"
    return json.loads(path.read_text())


def test_all_star_break_is_absent_scoring_period_ids() -> None:
    """The break (Feb 2025) skips scoring-period ids 116–120.

    ``proGamesByScoringPeriod`` has no entry for those ids because no NBA
    games are played — days with no games consume no scoring-period id.
    """
    window = _load_break_window()
    assert window["115"] is not None, "last game day before the break"
    assert window["121"] is not None, "first game day after the break"
    for missing in ("116", "117", "118", "119", "120"):
        assert window[missing] is None, f"scoring period {missing} should be absent"


def test_all_star_break_dates_are_not_contiguous() -> None:
    """The last pre-break date and first post-break date are days apart,
    proving the gap is real and not a date-labelling artifact."""
    window = _load_break_window()
    last_pre_break = window["115"][0]   # 2025-02-14
    first_post_break = window["121"][0]  # 2025-02-20
    assert last_pre_break == "2025-02-14"
    assert first_post_break == "2025-02-20"

