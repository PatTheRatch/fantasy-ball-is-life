"""Unit tests for EspnAdapter (P-1) — ESPN-native projections.

Tests assert that EspnAdapter correctly transforms ESPN rolling-stat
averages (Last 15 / Last 30) into canonical PlayerProjection rows,
matching the math in the existing get_current_rosters() implementation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from backend.league.data_feed import normalize_name
from backend.projections.adapter import (
    EspnAdapter,
    PlayerProjection,
    ProjectionAdapter,
    _count_games_in_range,
)
from backend.projections.registry import get_active_projections


# ---------------------------------------------------------------------------
# Helpers — minimal mock objects matching the ESPN player/team/league shape
# ---------------------------------------------------------------------------

def _mock_player(
    name: str = "LeBron James",
    pts: float = 25.0,
    blk: float = 0.6,
    ast: float = 8.0,
    stl: float = 1.2,
    tpm: float = 2.0,
    fta: float = 5.0,
    ftm: float = 4.0,
    fgm: float = 10.0,
    fga: float = 20.0,
    to: float = 3.0,
    oreb: float = 1.0,
    dreb: float = 6.0,
    injury: str = "ACTIVE",
    window: int = 15,
    games: int = 4,
) -> MagicMock:
    """Create a mock player with the specified rolling-average stats.

    Defaults represent a typical LeBron-ish stat line over Last 15 games.
    """
    p = MagicMock()
    p.name = name
    p.playerId = 1234
    p.injuryStatus = injury
    p.eligibleSlots = ["PG", "SF", "PF"]
    p.proTeam = "LAL"
    p.acquisitionType = "DRAFT"

    stats_key = f"2026_last_{window}"
    p.stats = {
        stats_key: {
            "avg": {
                "PTS": pts, "BLK": blk, "AST": ast, "STL": stl,
                "3PM": tpm, "FTA": fta, "FTM": ftm, "FGM": fgm,
                "FGA": fga, "TO": to, "OREB": oreb, "DREB": dreb,
            }
        },
        "2026_total": {"avg": {}},
    }

    # Mock schedule — generate `games` days in the future
    import datetime as dt
    base = dt.date.today()
    sched = {}
    for i in range(games):
        d = base + dt.timedelta(days=i + 1)
        sched[str(i)] = {"date": d.isoformat()}
    p.schedule = sched

    return p


def _mock_league(players: list[MagicMock]) -> MagicMock:
    """Create a mock league with one team containing the given players."""
    team = MagicMock()
    team.team_id = 1
    team.team_name = "Test Team"
    team.roster = players

    league = MagicMock()
    league.teams = [team]
    league.currentMatchupPeriod = 1
    return league


def _mock_handles(players: list[MagicMock]) -> MagicMock:
    """Create mock ESPNHandles."""
    from backend.league.data_feed import ESPNHandles
    return ESPNHandles(league=_mock_league(players))


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestProtocolConformance:
    def test_espn_adapter_is_projectable(self):
        """EspnAdapter satisfies ProjectionAdapter protocol."""
        a = EspnAdapter(window=15)
        assert isinstance(a, ProjectionAdapter)

    def test_source_id(self):
        assert EspnAdapter.source_id == "espn"

    def test_supported_horizons_week_only(self):
        assert EspnAdapter.supported_horizons == ["week"]

    def test_detect_always_high_confidence(self):
        a = EspnAdapter(window=15)
        assert a.detect() == 1.0
        assert a.detect(None) == 1.0  # not file-based, ignores arg

    def test_window_must_be_valid(self):
        with pytest.raises(ValueError):
            EspnAdapter(window=10)
        with pytest.raises(ValueError):
            EspnAdapter(window=7)


# ---------------------------------------------------------------------------
# parse() — single player, exact output
# ---------------------------------------------------------------------------

class TestParseSinglePlayer:
    def test_lebron_last15_all_stats(self):
        """Given a player with known Last-15 averages, assert exact output."""
        import datetime as dt
        player = _mock_player(
            name="LeBron James",
            pts=25.0, blk=0.6, ast=8.0, stl=1.2, tpm=2.0,
            fta=5.0, ftm=4.0, fgm=10.0, fga=20.0, to=3.0,
            oreb=1.0, dreb=6.0, window=15, games=4,
        )
        handles = _mock_handles([player])
        adapter = EspnAdapter(window=15)
        base = dt.date.today()
        week_start = base.isoformat()
        week_end = (base + dt.timedelta(days=7)).isoformat()

        result = adapter.parse(
            handles=handles,
            week_start_date=week_start,
            week_end_date=week_end,
        )

        assert len(result) == 1
        p = result[0]

        assert isinstance(p, PlayerProjection)
        assert p.display_name == "LeBron James"
        # Uses the canonical normalize_name (NFKD transliteration)
        assert p.player_key == normalize_name("LeBron James")
        assert p.team == "LAL"
        assert p.positions == ["PG", "SF", "PF"]
        assert p.injury_status == "ACTIVE"

        # Per-game averages
        assert p.pts_pg == 25.0
        assert p.blk_pg == 0.6
        assert p.ast_pg == 8.0
        assert p.stl_pg == 1.2
        assert p.tpm_pg == 2.0
        assert p.fga_pg == 20.0
        assert p.fta_pg == 5.0
        assert p.to_pg == 3.0

        # Derived: REB = OREB + DREB
        assert p.reb_pg == 7.0  # 1.0 + 6.0

        # Derived percentages
        assert p.fg_pct == 0.5   # 10.0 / 20.0
        assert p.ft_pct == 0.8   # 4.0 / 5.0

        # Games in window
        assert p.games == 4.0

        # ESPN has no MPG / value
        assert p.minutes_pg is None
        assert p.value is None

    def test_out_player_zeroed(self):
        """OUT players get all stats zeroed and games=0."""
        import datetime as dt
        player = _mock_player(name="OUT Guy", pts=30.0, injury="OUT", games=3)
        handles = _mock_handles([player])
        adapter = EspnAdapter(window=15)
        base = dt.date.today()
        week_start = base.isoformat()
        week_end = (base + dt.timedelta(days=7)).isoformat()

        result = adapter.parse(
            handles=handles,
            week_start_date=week_start,
            week_end_date=week_end,
        )

        assert len(result) == 1
        p = result[0]

        assert p.injury_status == "OUT"
        assert p.games == 0.0
        for attr in ("pts_pg", "reb_pg", "ast_pg", "stl_pg", "blk_pg",
                      "tpm_pg", "to_pg", "fga_pg", "fta_pg"):
            assert getattr(p, attr) == 0.0, f"{attr} not zeroed"
        assert p.fg_pct is None
        assert p.ft_pct is None

    def test_window_30_reads_correct_stats_key(self):
        """Window=30 reads 2026_last_30, not last_15."""
        import datetime as dt
        player = _mock_player(
            name="Window Test", pts=20.0, window=30, games=2,
        )
        handles = _mock_handles([player])
        adapter = EspnAdapter(window=30)
        base = dt.date.today()
        week_start = base.isoformat()
        week_end = (base + dt.timedelta(days=7)).isoformat()

        result = adapter.parse(
            handles=handles,
            week_start_date=week_start,
            week_end_date=week_end,
        )

        assert len(result) == 1
        assert result[0].pts_pg == 20.0
        assert result[0].games == 2.0

    def test_missing_stats_defaults_to_zero(self):
        """Stats with no data default to 0.0."""
        player = MagicMock()
        player.name = "Empty Stats"
        player.playerId = 9999
        player.injuryStatus = "ACTIVE"
        player.eligibleSlots = []
        player.proTeam = None
        player.stats = {}
        player.schedule = {}

        handles = _mock_handles([player])
        adapter = EspnAdapter(window=15)

        result = adapter.parse(handles=handles)

        assert len(result) == 1
        p = result[0]
        assert p.pts_pg == 0.0
        assert p.reb_pg == 0.0
        assert p.games == 0.0
        assert p.fg_pct is None

    def test_multiple_players(self):
        """Two players on the same team produce two projections."""
        import datetime as dt
        p1 = _mock_player(name="Player A", pts=20.0, games=3)
        p2 = _mock_player(name="Player B", pts=15.0, games=3)
        handles = _mock_handles([p1, p2])
        adapter = EspnAdapter(window=15)
        base = dt.date.today()
        week_start = base.isoformat()
        week_end = (base + dt.timedelta(days=7)).isoformat()

        result = adapter.parse(
            handles=handles,
            week_start_date=week_start,
            week_end_date=week_end,
        )

        assert len(result) == 2
        names = {r.display_name for r in result}
        assert names == {"Player A", "Player B"}

    def test_parse_requires_handles(self):
        """Calling parse() without handles raises ValueError."""
        adapter = EspnAdapter(window=15)
        with pytest.raises(ValueError, match="handles"):
            adapter.parse()

    def test_accented_player_key_uses_canonical_normalizer(self):
        """player_key uses the existing normalize_name (NFKD transliteration).

        Regression test for review finding #1 — a custom normalizer was
        stripping accented chars instead of transliterating them, which
        would break joins at P-3 name resolution time.
        """
        import datetime as dt
        player = _mock_player(name="Luka Dončić", pts=30.0, games=3)
        handles = _mock_handles([player])
        adapter = EspnAdapter(window=15)
        base = dt.date.today()

        result = adapter.parse(
            handles=handles,
            week_start_date=base.isoformat(),
            week_end_date=(base + dt.timedelta(days=7)).isoformat(),
        )

        expected_key = normalize_name("Luka Dončić")
        assert result[0].player_key == expected_key
        # NFKD transliterates č→c while preserving the space separator.
        assert "c" in result[0].player_key
        assert result[0].player_key != "lukadoni"


# ---------------------------------------------------------------------------
# _count_games_in_range
# ---------------------------------------------------------------------------

class TestCountGamesInRange:
    def test_all_games_in_window(self):
        import datetime as dt
        player = _mock_player(games=4)
        base = dt.date.today()
        start = pd.Timestamp(base.isoformat())
        end = pd.Timestamp((base + dt.timedelta(days=10)).isoformat())
        assert _count_games_in_range(player, start, end) == 4

    def test_no_games_in_window(self):
        import datetime as dt
        player = _mock_player(games=4)
        base = dt.date.today()
        # Use past dates so no games fall in the window
        start = pd.Timestamp("2020-01-01")
        end = pd.Timestamp("2020-01-10")
        assert _count_games_in_range(player, start, end) == 0

    def test_no_schedule(self):
        player = MagicMock()
        player.schedule = None
        assert _count_games_in_range(player, pd.Timestamp("2025-01-01"),
                                     pd.Timestamp("2025-01-10")) == 0

    def test_na_dates(self):
        player = _mock_player(games=4)
        assert _count_games_in_range(player, pd.NaT, pd.NaT) == 0


# ---------------------------------------------------------------------------
# get_active_projections accessor
# ---------------------------------------------------------------------------

class TestGetActiveProjections:
    def test_week_returns_espn_output(self):
        """get_active_projections('week') delegates to EspnAdapter."""
        player = _mock_player(name="Test Player", pts=20.0, games=3)
        handles = _mock_handles([player])

        result = get_active_projections(
            "week", handles=handles, window=15,
        )

        assert len(result) == 1
        assert isinstance(result[0], PlayerProjection)
        assert result[0].display_name == "Test Player"
        assert result[0].pts_pg == 20.0

    def test_season_returns_empty(self):
        """get_active_projections('season') returns empty — no adapter registered yet."""
        result = get_active_projections("season")
        assert result == []

    def test_window_15_flows_through_registry(self):
        """window=15 flows through get_active_projections to EspnAdapter."""
        import datetime as dt
        player = _mock_player(name="W15", pts=10.0, window=15, games=2)
        handles = _mock_handles([player])
        base = dt.date.today()

        result = get_active_projections(
            "week",
            handles=handles,
            window=15,
            week_start_date=base.isoformat(),
            week_end_date=(base + dt.timedelta(days=7)).isoformat(),
        )
        assert len(result) == 1
        assert result[0].pts_pg == 10.0

    def test_window_30_flows_through_registry(self):
        """window=30 flows through get_active_projections — reads 2026_last_30."""
        import datetime as dt
        player = _mock_player(name="W30", pts=25.0, window=30, games=3)
        handles = _mock_handles([player])
        base = dt.date.today()

        result = get_active_projections(
            "week",
            handles=handles,
            window=30,
            week_start_date=base.isoformat(),
            week_end_date=(base + dt.timedelta(days=7)).isoformat(),
        )
        assert len(result) == 1
        assert result[0].pts_pg == 25.0
        assert result[0].games == 3.0
