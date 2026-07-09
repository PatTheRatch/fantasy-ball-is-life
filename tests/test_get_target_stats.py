"""Unit tests for OptimizeLineup.get_target_stats — the week-sampling loop that
feeds set_requirements() and therefore every draft plan's category targets.

Bug fixed here (found by an ESPN-integration audit, 2026-07): the old loop was
`for i in range(16): if i not in [7, 8, 17, 18, 19, 20])`, which (a) made
indices 17-20 unreachable dead code since range(16) only yields 0-15, and
(b) excluded weeks 8-9 based on a stale assumption about which weeks those
were, while never actually excluding playoff weeks or unplayed future weeks.
That silently skewed the stats `set_requirements()` uses for every strategy,
undermining the plan-diversity work in draft_strategies.py.

These tests use a lightweight duck-typed stand-in for `MyLeague` (a real
`espn_api.basketball.League` + ESPN network access isn't available here) and
call the unbound method directly, since `get_target_stats` only touches
`self.league` — no need to construct a full `OptimizeLineup`.
"""
import pandas as pd
import pytest

ol = pytest.importorskip("optimize_lineup")

CATS = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]


class _Settings:
    def __init__(self, reg_season_count):
        self.reg_season_count = reg_season_count


class _FakeLeague:
    """Stands in for MyLeague. `get_universe_wins` raises ValueError for weeks
    listed in `missing_weeks`, mirroring MyLeague.get_wins's real behavior for
    weeks with no matchup data (bye weeks, unscheduled weeks, etc.)."""

    def __init__(self, reg_season_count, effective_current_week, length_of_schedule,
                 missing_weeks=(), value_by_week=None):
        self.settings = _Settings(reg_season_count)
        self.effective_current_week = effective_current_week
        self.length_of_schedule = length_of_schedule
        self.stat_categories = CATS
        self.missing_weeks = set(missing_weeks)
        self.calls = []
        # Distinct, deterministic PTS-per-week so tests can assert on *which*
        # weeks were actually sampled.
        self.value_by_week = value_by_week or {}

    def get_universe_wins(self, weeks):
        week = weeks[0]
        self.calls.append(week)
        if week in self.missing_weeks:
            raise ValueError(f"No matchup data for week {week}.")
        pts = self.value_by_week.get(week, float(week))
        return pd.DataFrame({cat: [pts, pts, pts] for cat in CATS})


def _call(fake_league, percentile=0.75):
    stand_in = type("StandIn", (), {"league": fake_league})()
    return ol.OptimizeLineup.get_target_stats(stand_in, percentile=percentile)


def test_only_samples_regular_season_weeks_played_so_far():
    # 10-week regular season, currently in week 6 -> only weeks 1-6 sampled,
    # even though the schedule (incl. playoffs) runs to week 13.
    league = _FakeLeague(reg_season_count=10, effective_current_week=6, length_of_schedule=13)
    _call(league)
    assert league.calls == [1, 2, 3, 4, 5, 6]


def test_stops_at_regular_season_even_if_current_week_is_later():
    # Season is over (currentMatchupPeriod is in the playoffs, week 12), but
    # only the 10 regular-season weeks should feed the category targets.
    league = _FakeLeague(reg_season_count=10, effective_current_week=12, length_of_schedule=13)
    _call(league)
    assert league.calls == list(range(1, 11))


def test_skips_weeks_with_no_matchup_data_instead_of_crashing():
    # A bye/All-Star week (week 4) has no scheduled matchup -> ValueError from
    # get_universe_wins. The old code either mis-excluded the wrong weeks or
    # would have propagated a crash here; the fix must skip it gracefully and
    # keep going.
    league = _FakeLeague(
        reg_season_count=6, effective_current_week=6, length_of_schedule=8,
        missing_weeks={4},
    )
    result = _call(league)
    assert league.calls == [1, 2, 3, 4, 5, 6]  # week 4 attempted, then skipped
    # Only 5 real weeks contributed (1,2,3,5,6) -> mean PTS is their average.
    assert result["PTS"] == pytest.approx((1 + 2 + 3 + 5 + 6) / 5)


def test_falls_back_to_length_of_schedule_when_reg_season_count_unavailable():
    league = _FakeLeague(reg_season_count=0, effective_current_week=4, length_of_schedule=9)
    _call(league)
    assert league.calls == [1, 2, 3, 4]


def test_dead_exclusion_indices_no_longer_apply():
    # Regression guard for the specific bug: weeks 8 and 9 (previously always
    # excluded by the stale magic-number list) must now be sampled normally
    # when they're valid, played, regular-season weeks.
    league = _FakeLeague(reg_season_count=12, effective_current_week=12, length_of_schedule=12)
    _call(league)
    assert 8 in league.calls
    assert 9 in league.calls
    assert league.calls == list(range(1, 13))
