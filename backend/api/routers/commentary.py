"""AI commentary endpoints."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.commentary import generate

router = APIRouter(tags=["commentary"])

class MatchupCommentaryRow(BaseModel):
    stat: str
    home_score: float
    away_score: float
    result: str
    confidence_pct: Optional[float] = None


class ProjectedRosterPlayer(BaseModel):
    player_name: str
    pts: float
    reb: float
    ast: float
    stl: float
    blk: float
    three_pm: float = Field(alias="3pm")
    fg_pct: float
    ft_pct: float
    to: float
    games_left: Optional[int] = None


class MatchupCommentaryBody(BaseModel):
    home_team: str
    away_team: str
    matchup_data: List[MatchupCommentaryRow]
    home_roster: List[ProjectedRosterPlayer] = []
    away_roster: List[ProjectedRosterPlayer] = []
    projections: Optional[str] = None
    is_live: bool = False


class LeagueRecapBody(BaseModel):
    week: int
    league_settings: Dict[str, Any] = {}
    standings: List[Dict[str, Any]]
    power_rankings: List[Dict[str, Any]]
    transactions: List[Dict[str, Any]]
    scoreboard: List[Dict[str, Any]]
    week_dates: Dict[str, str]


class SeasonCommentaryBody(BaseModel):
    """Season stats aggregate; `weeks` must match the week range used to build `season_stats`."""

    season_stats: List[Dict[str, Any]]
    weeks: List[int]
    league_settings: Dict[str, Any]
    min_week: Optional[int] = None
    max_week: Optional[int] = None



@router.post("/matchup-commentary")
def matchup_commentary(body: MatchupCommentaryBody) -> dict[str, Any]:
    """
    Generate a short ESPN-style preview article for the matchup using Anthropic.
    """
    return generate.generate_matchup_commentary(body)


@router.post("/league-recap")
def league_recap(body: LeagueRecapBody) -> dict[str, Any]:
    """
    Generate a weekly league newsletter recap (ESPN-style) using Anthropic.
    """
    return generate.generate_league_recap(body)


@router.post("/season-commentary")
def season_commentary(body: SeasonCommentaryBody) -> dict[str, Any]:
    return generate.generate_season_commentary(body)
