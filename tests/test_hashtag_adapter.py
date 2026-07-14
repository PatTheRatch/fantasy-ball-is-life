"""Tests for HashtagAdapter (P-5)."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.projections.hashtag_adapter import HashtagAdapter
from backend.projections.adapter import PlayerProjection, ProjectionAdapter


PASTED_SAMPLE = """Player\tTeam\tPos\tGP\tMIN\tPTS\t3PM\tREB\tAST\tSTL\tBLK\tFG%\tFT%\tTO
Nikola Jokic\tDEN\tC\t72\t34.5\t26.3\t1.2\t12.1\t9.0\t1.4\t0.7\t58.3\t82.2\t3.0
Luka Doncic\tDAL\tPG\t68\t37.0\t32.4\t3.0\t8.5\t8.0\t1.5\t0.5\t49.6\t74.2\t3.5
Victor Wembanyama\tSAS\tC\t68\t32.0\t22.0\t1.5\t10.5\t3.0\t1.2\t3.5\t48.5\t80.0\t2.5
"""


class TestHashtagAdapterProtocol:
    def test_is_projectable(self):
        assert isinstance(HashtagAdapter(), ProjectionAdapter)

    def test_source_id(self):
        assert HashtagAdapter.source_id == "hashtag"

    def test_supported_horizons(self):
        assert HashtagAdapter.supported_horizons == ["season"]


class TestHashtagDetect:
    def test_pasted_text_detected(self):
        a = HashtagAdapter()
        df = pd.read_csv(pd.io.common.StringIO(PASTED_SAMPLE), sep="\t", dtype=str)
        assert a.detect(raw_df=df) == 0.95

    def test_partial_columns_lower_confidence(self):
        a = HashtagAdapter()
        df = pd.DataFrame({"player": ["X"], "pts": ["20"], "reb": ["10"]})
        assert a.detect(raw_df=df) < 0.9

    def test_unknown_format_zero(self):
        a = HashtagAdapter()
        df = pd.DataFrame({"foo": ["bar"]})
        assert a.detect(raw_df=df) == 0.0


class TestParsePasted:
    def test_parse_three_players(self):
        a = HashtagAdapter()
        rows = a.parse(pasted_text=PASTED_SAMPLE)
        assert len(rows) == 3

    def test_jokic_stats_exact(self):
        a = HashtagAdapter()
        rows = a.parse(pasted_text=PASTED_SAMPLE)
        jokic = rows[0]
        assert jokic.display_name == "Nikola Jokic"
        assert jokic.player_key == "nikola jokic"
        assert jokic.team == "DEN"
        assert jokic.positions == ["C"]
        assert jokic.games == 72.0
        assert jokic.minutes_pg == 34.5
        assert jokic.pts_pg == 26.3
        assert jokic.tpm_pg == 1.2
        assert jokic.reb_pg == 12.1
        assert jokic.ast_pg == 9.0
        assert jokic.stl_pg == 1.4
        assert jokic.blk_pg == 0.7
        assert jokic.to_pg == 3.0
        # Percentages stored as ratios
        assert jokic.fg_pct == pytest.approx(0.583)
        assert jokic.ft_pct == pytest.approx(0.822)

    def test_percentages_converted_from_whole(self):
        """58.3 should become 0.583, not 58.3"""
        a = HashtagAdapter()
        rows = a.parse(pasted_text=PASTED_SAMPLE)
        jokic = rows[0]
        assert jokic.fg_pct < 1.0
        assert jokic.ft_pct < 1.0

    def test_parse_accepts_raw_dataframe(self):
        a = HashtagAdapter()
        df = pd.DataFrame({
            "Player": ["Test Player"],
            "PTS": ["20.0"],
            "REB": ["10.0"],
            "AST": ["5.0"],
            "STL": ["1.0"],
            "BLK": ["0.5"],
            "3PM": ["2.0"],
            "FG%": ["45.0"],
            "FT%": ["80.0"],
            "TO": ["2.0"],
            "GP": ["70"],
        })
        rows = a.parse(raw_df=df)
        assert len(rows) == 1
        assert rows[0].pts_pg == 20.0
        assert rows[0].fg_pct == 0.45

    def test_missing_stats_default_to_zero(self):
        a = HashtagAdapter()
        df = pd.DataFrame({
            "Player": ["Minimal Player"],
            "PTS": ["15.0"],
        })
        rows = a.parse(raw_df=df)
        assert rows[0].pts_pg == 15.0
        assert rows[0].reb_pg == 0.0
        assert rows[0].ast_pg == 0.0

    def test_no_player_column_raises(self):
        a = HashtagAdapter()
        df = pd.DataFrame({"PTS": ["20"]})
        with pytest.raises(ValueError, match="player-name column"):
            a.parse(raw_df=df)

    def test_empty_names_skipped(self):
        a = HashtagAdapter()
        df = pd.DataFrame({
            "Player": ["", "Real Player", None],
            "PTS": ["10", "20", "30"],
        })
        rows = a.parse(raw_df=df)
        assert len(rows) == 1
        assert rows[0].display_name == "Real Player"

    def test_whitespace_delimited_paste(self):
        """Spaces instead of tabs between columns should work."""
        text = "Player PTS REB AST\nTest 20.0 10.0 5.0"
        a = HashtagAdapter()
        rows = a.parse(pasted_text=text)
        assert len(rows) == 1
        assert rows[0].pts_pg == 20.0
