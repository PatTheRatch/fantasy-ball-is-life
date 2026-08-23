"""Periods endpoint: the season's matchup periods, ordinal-ordered.

Thin by design — a scoped read with no fold, so there is no service layer. The
router declares the ``LEAGUE_SCOPED`` policy, wires the membership gate, and maps
the repository rows onto a ``data`` envelope. Every period is returned (the
reader needs the season's actual shape); selectability is a UI decision driven
by ``status``, which is why ``status`` is on the wire.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.api.deps import PeriodsReader, get_periods_repository, require_league_member
from backend.api.policy import RoutePolicy, declare_policy

router = APIRouter(prefix="/api/v1")


class PeriodOut(BaseModel):
    id: uuid.UUID
    ordinal: int
    label: str | None
    type: str
    status: str
    start_date: date
    end_date: date


class PeriodsResponse(BaseModel):
    data: list[PeriodOut]


@router.get("/leagues/{league_season_id}/periods")
@declare_policy(RoutePolicy.LEAGUE_SCOPED)
def periods(
    league_season_id: uuid.UUID = Depends(require_league_member),
    repo: PeriodsReader = Depends(get_periods_repository),
) -> PeriodsResponse:
    return PeriodsResponse(
        data=[
            PeriodOut(
                id=p.id,
                ordinal=p.ordinal,
                label=p.label,
                type=p.type,
                status=p.status,
                start_date=p.start_date,
                end_date=p.end_date,
            )
            for p in repo.periods()
        ]
    )
