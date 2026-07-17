"""P-3b: Snapshot-based read path for assemble_weekly_snapshot."""

from unittest.mock import Mock, patch

import pytest

from backend.recaps import assemble


def _make_phases(**overrides):
    default = {
        "standings": {
            "payload_json": [
                {"team_name": "Alpha", "wins": 10, "losses": 5, "ties": 0, "win_pct": 66.7}
            ],
            "fetched_at": "2026-01-01T00:00:00Z",
        },
        "power_rankings": {
            "payload_json": [{"Team": "Alpha", "wins": 10, "losses": 5, "ties": 0, "Rank": 1, "Score": 0.85}],
            "fetched_at": "2026-01-01T00:00:00Z",
        },
        "scoreboard": {"payload_json": [], "fetched_at": "2026-01-01T00:00:00Z"},
        "transactions": {"payload_json": [], "fetched_at": "2026-01-01T00:00:00Z"},
        "season_stats": {"payload_json": [], "fetched_at": "2026-01-01T00:00:00Z"},
    }
    default.update(overrides)
    return default


@pytest.fixture
def league():
    return {"id": "test-league-uuid", "slug": "test-league", "name": "Test League"}


class TestSnapshotRead:
    def test_default_reads_from_snapshots(self, league):
        """Not force_fresh → reads from snapshots, no ESPN call."""
        mock_store = Mock()
        mock_store.get_all_phases.return_value = _make_phases()

        with patch.object(assemble, "RecapStore", return_value=mock_store):
            with patch("backend.recaps.awards.select_awards", return_value=[]):
                result = assemble.assemble_weekly_snapshot(
                    league=league,
                    season=2026,
                    week=12,
                    week_start="2026-03-01",
                    week_end="2026-03-07",
                    force_fresh=False,
                )

        assert mock_store.get_all_phases.called
        assert result is not None

    def test_force_fresh_calls_league_api(self, league):
        """force_fresh=True → pulls live ESPN."""
        with patch.object(assemble, "league_api") as mock_api:
            mock_api.power_rankings.return_value = [{"Team": "A"}]
            mock_api.scoreboard_current.return_value = []
            mock_api.transactions_week.return_value = []
            mock_api.season_stats.return_value = []
            # Realistic settings (empty dict) so playoff_round() gets real
            # None values, not a MagicMock that breaks its `< 2` int check.
            mock_api.league_settings.return_value = {}

            with patch.object(
                assemble, "_build_scoped_standings", return_value=([], True)
            ):
                with patch.object(
                    assemble, "_build_single_week_ap", return_value=[]
                ):
                    with patch("backend.recaps.awards.select_awards", return_value=[]):
                        result = assemble.assemble_weekly_snapshot(
                            league=league,
                            season=2026,
                            week=12,
                            week_start="2026-03-01",
                            week_end="2026-03-07",
                            force_fresh=True,
                        )

        # force_fresh pulls live ESPN: rankings via _live_power_rankings()
        # (NOT league_api.power_rankings, which now reads the snapshot), and
        # scoreboard/transactions/season_stats straight from league_api.
        assert mock_api.scoreboard_current.called
        assert not mock_api.power_rankings.called

    def test_missing_snapshots_returns_degraded(self, league):
        """No snapshots → empty/degraded, not a 500."""
        mock_store = Mock()
        mock_store.get_all_phases.return_value = {}

        with patch.object(assemble, "RecapStore", return_value=mock_store):
            with patch("backend.recaps.awards.select_awards", return_value=[]):
                result = assemble.assemble_weekly_snapshot(
                    league=league,
                    season=2026,
                    week=12,
                    week_start="2026-03-01",
                    week_end="2026-03-07",
                    force_fresh=False,
                )

        assert result is not None
        assert not result.data_quality.ready
