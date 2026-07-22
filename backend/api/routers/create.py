"""N-4a: League creation — read-only ESPN validation endpoint.

POST /leagues/preview validates an ESPN league ID + optional cookies
against ESPN's API without writing anything to the database.  On success
it returns the league name, team count, scoring type, season, and team
names so the frontend can confirm "is this your league?" before the user
proceeds past the wizard's first step.

N-4b (credential storage + membership creation) and N-4c (worker
enrolment) are separate PRs and call the same
``validate_espn_league()`` helper underneath.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.league.create import LeagueValidation, validate_espn_league
from backend.recaps.auth import require_supabase_user

router = APIRouter(prefix="/leagues", tags=["leagues"])


class LeaguePreviewRequest(BaseModel):
    espn_league_id: int
    season: int
    swid: str | None = None
    espn_s2: str | None = None


class LeaguePreviewResponse(BaseModel):
    name: str
    teams: int
    scoring_type: str
    season: int
    team_names: list[str]


def _raise_validation_error(result: LeagueValidation) -> None:
    """Map a failed ``LeagueValidation`` to the appropriate HTTPException."""
    if result.error_code == "not_found":
        raise HTTPException(
            status_code=404,
            detail={
                "code": result.error_code,
                "message": result.error_message,
            },
        )
    if result.error_code == "espn_unavailable":
        raise HTTPException(
            status_code=503,
            detail={
                "code": result.error_code,
                "message": result.error_message,
            },
        )
    # private_league, bad_cookies → 422
    raise HTTPException(
        status_code=422,
        detail={
            "code": result.error_code,
            "message": result.error_message,
        },
    )


@router.post("/preview", response_model=LeaguePreviewResponse)
def league_preview(
    body: LeaguePreviewRequest,
    _user: dict[str, Any] = Depends(require_supabase_user),
) -> LeaguePreviewResponse:
    """Validate an ESPN league before creation (read-only, no DB writes).

    Requires a valid Supabase session.
    """
    result = validate_espn_league(
        espn_league_id=body.espn_league_id,
        season=body.season,
        swid=body.swid,
        espn_s2=body.espn_s2,
    )

    if not result.valid:
        _raise_validation_error(result)

    # Satisfy type-checker: all success fields are populated when valid=True.
    assert result.name is not None
    assert result.teams is not None
    assert result.scoring_type is not None
    assert result.season is not None

    return LeaguePreviewResponse(
        name=result.name,
        teams=result.teams,
        scoring_type=result.scoring_type,
        season=result.season,
        team_names=result.team_names,
    )
