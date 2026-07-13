"""PR D — GET /rosters/current inverted date-window fix.

The old hardcoded defaults put week_start_date (2026-10-15) AFTER week_end_date
(2026-04-30), so count_games_in_range() was always false and every player showed
zero games left when the optional dates were omitted. These tests cover the
window resolver and the router's 400 on an explicitly inverted range.
"""
import pandas as pd
import pytest
from fastapi import HTTPException

from backend.api.routers.league import _validate_week_range, rosters_current
from backend.league.data_feed import (
    MATCHUP_WEEKS_2025_26,
    resolve_roster_week_window,
)


# --- resolve_roster_week_window -------------------------------------------

def test_explicit_dates_pass_through():
    start, end = resolve_roster_week_window("2025-11-10", "2025-11-16")
    assert start == pd.Timestamp("2025-11-10")
    assert end == pd.Timestamp("2025-11-16")


def test_derives_window_from_matchup_period_when_dates_missing():
    period = 4
    meta = MATCHUP_WEEKS_2025_26[period]
    start, end = resolve_roster_week_window(None, None, current_matchup_period=period)
    assert start == pd.Timestamp(meta["start"])
    assert end == pd.Timestamp(meta["end"])
    # The core bug regression: the resolved default is a FORWARD window.
    assert start <= end


def test_falls_back_to_league_current_week():
    period = 7
    meta = MATCHUP_WEEKS_2025_26[period]
    start, end = resolve_roster_week_window(
        None, None, current_matchup_period=None, league_current_week=period
    )
    assert start == pd.Timestamp(meta["start"])
    assert end == pd.Timestamp(meta["end"])
    assert start <= end


def test_explicit_period_beats_league_week():
    start, end = resolve_roster_week_window(
        None, None, current_matchup_period=3, league_current_week=10
    )
    assert start == pd.Timestamp(MATCHUP_WEEKS_2025_26[3]["start"])


def test_partial_dates_fill_only_missing_bound():
    # Explicit start, derived end.
    start, end = resolve_roster_week_window("2025-12-01", None, current_matchup_period=8)
    assert start == pd.Timestamp("2025-12-01")
    assert end == pd.Timestamp(MATCHUP_WEEKS_2025_26[8]["end"])


def test_old_inverted_default_is_gone():
    # With a valid period, the window is never the old inverted Oct15..Apr30.
    start, end = resolve_roster_week_window(None, None, league_current_week=1)
    assert not (start == pd.Timestamp("2026-10-15") and end == pd.Timestamp("2026-04-30"))
    assert start <= end


# --- router validation -----------------------------------------------------

def test_validate_week_range_rejects_inverted():
    with pytest.raises(HTTPException) as exc:
        _validate_week_range("2026-03-22", "2026-03-16")
    assert exc.value.status_code == 400


def test_validate_week_range_allows_forward_and_partial():
    # Forward range and any partial/omitted range must not raise.
    _validate_week_range("2026-03-16", "2026-03-22")
    _validate_week_range(None, None)
    _validate_week_range("2026-03-16", None)
    _validate_week_range(None, "2026-03-22")


def test_rosters_current_endpoint_400s_on_inverted_before_touching_espn():
    # Validation runs before _handles(), so this raises without any ESPN call.
    with pytest.raises(HTTPException) as exc:
        rosters_current(week_start_date="2026-03-22", week_end_date="2026-03-16")
    assert exc.value.status_code == 400
