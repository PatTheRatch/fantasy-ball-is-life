"""ESPN scoreboard adapter mapping (hermetic — duck-typed box scores)."""

from __future__ import annotations

from backend.providers.espn.adapter import map_scoreboard


class _Team:
    def __init__(self, team_id: int) -> None:
        self.team_id = team_id


class _Box:
    def __init__(self, home, away, home_cats, away_cats, winner) -> None:
        self.home_team = home
        self.away_team = away
        self.home_team_cats = home_cats
        self.away_team_cats = away_cats
        self.winner = winner


class _League:
    def __init__(self, boxes) -> None:
        self._boxes = boxes

    def box_scores(self, matchup_period: int):
        return self._boxes


def _cats(**scores):
    return {abbrev: {"score": score, "result": "WIN"} for abbrev, score in scores.items()}


def test_maps_teams_and_translates_stat_keys() -> None:
    box = _Box(
        home=_Team(1),
        away=_Team(2),
        home_cats=_cats(
            PTS=103.0, REB=44.0, AST=22.0, STL=7.0, BLK=5.0, TO=11.0,
            FGM=40.0, FGA=82.0, FTM=15.0, FTA=18.0, **{"3PM": 12.0, "FG%": 0.487},
        ),
        away_cats=_cats(PTS=98.0, FGM=38.0, FGA=81.0, **{"3PM": 9.0}),
        winner="HOME",
    )
    sb = map_scoreboard(_League([box]), "7")

    assert sb.provider_period_id == "7"
    (m,) = sb.matchups
    assert m.home.provider_team_id == "1"
    assert m.away is not None
    assert m.away.provider_team_id == "2"
    assert m.provider_result == "home"

    # ESPN abbreviations are translated to FCP canonical keys, and ESPN's
    # precomputed ratio (FG%) is dropped — components are what survive.
    assert m.home.stats["PTS"] == 103.0
    assert m.home.stats["TPM"] == 12.0
    assert m.home.stats["fgm"] == 40.0
    assert m.home.stats["fga"] == 82.0
    assert "FG%" not in m.home.stats
    assert "3PM" not in m.home.stats


def test_bye_has_no_away_side() -> None:
    box = _Box(
        home=_Team(1),
        away=0,  # the SDK leaves a bye's away side as integer 0
        home_cats=_cats(PTS=100.0),
        away_cats=None,
        winner="HOME",
    )
    sb = map_scoreboard(_League([box]), "8")

    (m,) = sb.matchups
    assert m.home.provider_team_id == "1"
    assert m.away is None


def test_undecided_winner_maps_to_none() -> None:
    box = _Box(_Team(1), _Team(2), _cats(PTS=1.0), _cats(PTS=1.0), "UNDECIDED")
    sb = map_scoreboard(_League([box]), "1")
    (m,) = sb.matchups
    assert m.provider_result is None
