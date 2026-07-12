"""Unit tests for OptimizeLineup(value_source=...) -- the "Forge Value" path
that replaces the uploaded projections' $ column with PatriotGames' own
projection-derived valuation (player_values.calculate_player_values), scaled
to the live league's real team count instead of a hardcoded default.

Same ESPN-isolation pattern as tests/test_plan_diversity_integration.py: a
fake league stands in so this runs without network access. Skips cleanly when
the engine deps or the projections file aren't available.
"""
import contextlib
import io
import os

import pytest

pd = pytest.importorskip("pandas")
ol = pytest.importorskip("optimize_lineup")

try:
    from config import BBM_PROJECTIONS_PATH
except Exception:  # pragma: no cover
    BBM_PROJECTIONS_PATH = "player_rankings/BBM_Projections.xls"

pytestmark = pytest.mark.integration

_HAS_PROJECTIONS = os.path.exists(BBM_PROJECTIONS_PATH)


class _Settings:
    def __init__(self, team_count):
        self.team_count = team_count


def _fake_league(team_count):
    class _FakeLeague:
        def __init__(self, *args, **kwargs):
            self.draft = []
            self.stat_categories = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]
            self.settings = _Settings(team_count)

    return _FakeLeague


class _FakeLeagueNoSettings:
    """Stands in for an offline/degraded league object with no .settings at
    all -- Forge Value must still work, falling back to a sane default team
    count rather than raising."""

    def __init__(self, *args, **kwargs):
        self.draft = []
        self.stat_categories = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]


def _build(monkeypatch, league_cls, **kwargs):
    monkeypatch.setattr(ol, "MyLeague", league_cls)
    with contextlib.redirect_stdout(io.StringIO()):
        return ol.OptimizeLineup(
            initial_budget=200,
            roster_size=13,
            minimum_game_threshold=20,
            **kwargs,
        )


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_default_value_source_is_bbm_and_unchanged(monkeypatch):
    opt = _build(monkeypatch, _fake_league(10))
    assert opt.value_source == "bbm"


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_forge_value_source_changes_the_dollar_column(monkeypatch):
    bbm = _build(monkeypatch, _fake_league(10), value_source="bbm")
    forge = _build(monkeypatch, _fake_league(10), value_source="forge")

    b = bbm.player_data_df.set_index("Name")["$"]
    f = forge.player_data_df.set_index("Name")["$"]
    common = b.index.intersection(f.index)
    assert len(common) > 50
    # A genuinely different valuation model -- not just a rescale of the same
    # ranking -- so at least some players should be priced meaningfully
    # differently, not identically.
    assert (b.loc[common] != f.loc[common]).any()


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_forge_value_uses_the_live_league_team_count(monkeypatch):
    """Same pool, same budget/roster size -- only the live league's team
    count differs -- must produce different prices. This is the "actually
    feeds into what we're doing" guarantee, not a decorative parameter."""
    small_league = _build(monkeypatch, _fake_league(8), value_source="forge")
    big_league = _build(monkeypatch, _fake_league(16), value_source="forge")

    small = small_league.player_data_df.set_index("Name")["$"]
    big = big_league.player_data_df.set_index("Name")["$"]
    common = small.index.intersection(big.index)
    assert (small.loc[common] != big.loc[common]).any()


@pytest.mark.skipif(not _HAS_PROJECTIONS, reason="projections file not present")
def test_forge_value_falls_back_when_league_settings_unavailable(monkeypatch):
    # Must not raise even though the fake league has no .settings at all.
    opt = _build(monkeypatch, _FakeLeagueNoSettings, value_source="forge")
    assert opt.value_source == "forge"
    assert len(opt.player_data_df) > 0


def test_invalid_value_source_rejected(monkeypatch):
    monkeypatch.setattr(ol, "MyLeague", _fake_league(10))
    with pytest.raises(ValueError):
        ol.OptimizeLineup(value_source="yahoo")
