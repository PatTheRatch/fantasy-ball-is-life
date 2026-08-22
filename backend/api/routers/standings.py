"""Standings endpoint: the folded table for one league_season.

Thin by design — the fold lives in ``services.standings_read`` and the
repo/model wiring lives in the deps layer. This router only declares the
``LEAGUE_SCOPED`` policy, wires dependencies, and maps the service result onto
the wire envelope (``data`` + freshness metadata).
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.api.deps import get_standings_service, require_league_member
from backend.api.policy import RoutePolicy, declare_policy
from backend.services.standings_read import StandingsReadService

router = APIRouter(prefix="/api/v1")


class StandingRowOut(BaseModel):
    rank: int
    team_id: uuid.UUID
    team_name: str
    team_abbreviation: str | None
    wins: int
    losses: int
    ties: int
    win_pct: float
    played: int
    unknown: int


class StandingsResponse(BaseModel):
    data: list[StandingRowOut]
    as_of: date | None
    freshness: str
    stale: bool
    complete: bool
    unknown_category_count: int


@router.get("/leagues/{league_season_id}/standings")
@declare_policy(RoutePolicy.LEAGUE_SCOPED)
def standings(
    league_season_id: uuid.UUID = Depends(require_league_member),
    through_period: int | None = Query(default=None, ge=1),
    svc: StandingsReadService = Depends(get_standings_service),
) -> StandingsResponse:
    result = svc.standings(league_season_id, through_period=through_period)
    return StandingsResponse(
        data=[
            StandingRowOut(
                rank=r.rank,
                team_id=r.team_id,
                team_name=r.team_name,
                team_abbreviation=r.team_abbreviation,
                wins=r.wins,
                losses=r.losses,
                ties=r.ties,
                win_pct=r.win_pct,
                played=r.played,
                unknown=r.unknown,
            )
            for r in result.rows
        ],
        as_of=result.as_of,
        freshness=result.freshness,
        stale=result.stale,
        complete=result.complete,
        unknown_category_count=result.unknown_category_count,
    )
