"""Legacy /optimizer/* endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional

import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.api.deps import _df_records, _read_excel_bytes
from backend.config import BBM_PROJECTIONS_PATH
from backend.draft.optimizer import OptimizeLineup, generate_multiple_plans

router = APIRouter(tags=["optimizer"])

class DraftPick(BaseModel):
    name: str
    bid: float


class OptimizeBody(BaseModel):
    exclude_players: Optional[List[str]] = None
    games_per_week: Optional[float] = None  # None -> config.GAMES_PER_WEEK (3.5)
    initial_budget: float = 200
    year: Optional[int] = None
    roster_size: int = 13
    minimum_value_players: int = 3
    favorite_team: Optional[str] = None
    favorite_team_representation: int = 1
    minimum_game_threshold: float = 55
    value_col: str = "$"
    target_method: str = "monte_carlo"  # 'monte_carlo' (default) | 'historical'
    categories: Optional[List[str]] = None
    percentile: float = 0.75
    stat_to_maximize: str = "PTS"
    draft_picks: List[DraftPick] = Field(default_factory=list)


@router.post("/optimizer/optimize")
async def optimizer_optimize(request: Request) -> List[dict[str, Any]]:
    """
    JSON body (``application/json``): same as ``OptimizeBody``.

    Multipart (``multipart/form-data``): field ``data`` = JSON string for ``OptimizeBody``;
    optional file field ``bbm_file`` = season BBM projections Excel (passed as ``projections_df`` to ``OptimizeLineup``).
    """
    content_type = request.headers.get("content-type", "").lower()
    bbm_df: Optional[pd.DataFrame] = None
    if "multipart/form-data" in content_type:
        form = await request.form()
        data_raw = form.get("data")
        if data_raw is None:
            raise HTTPException(
                status_code=422,
                detail="multipart requests must include a form field 'data' containing JSON for OptimizeBody",
            )
        if isinstance(data_raw, bytes):
            data_raw = data_raw.decode("utf-8")
        elif not isinstance(data_raw, str):
            data_raw = str(data_raw)
        body = OptimizeBody.model_validate_json(data_raw)
        up = form.get("bbm_file")
        if up is not None and hasattr(up, "read"):
            raw = await up.read()
            if raw:
                bbm_df = _read_excel_bytes(raw)
        if bbm_df is None:
            default_path = Path(BBM_PROJECTIONS_PATH)
            if not default_path.exists():
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"No `bbm_file` was uploaded and the default projections file "
                        f"was not found at {BBM_PROJECTIONS_PATH}"
                    ),
                )
            bbm_df = _read_excel_bytes(default_path.read_bytes())
    else:
        try:
            payload = await request.json()
        except Exception as e:
            raise HTTPException(status_code=422, detail="Request body must be valid JSON for OptimizeBody") from e
        body = OptimizeBody.model_validate(payload)

    try:
        opt = OptimizeLineup(
            exclude_players=body.exclude_players,
            games_per_week=body.games_per_week,
            initial_budget=body.initial_budget,
            year=body.year,
            roster_size=body.roster_size,
            minimum_value_players=body.minimum_value_players,
            favorite_team=body.favorite_team,
            favorite_team_representation=body.favorite_team_representation,
            minimum_game_threshold=body.minimum_game_threshold,
            value_col=body.value_col,
            projections_df=bbm_df,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    for p in body.draft_picks:
        opt.draft_player(p.name, p.bid)

    if body.categories:
        opt.set_requirements(
            body.categories, percentile=body.percentile, target_method=body.target_method,
        )

    try:
        results = opt.optimize_roster(body.stat_to_maximize)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return _df_records(results)


class MultiplePlansBody(BaseModel):
    n_plans: int = Field(default=10, ge=1, le=10)
    base_excluded: Optional[List[str]] = None
    base_percentile: float = 0.80
    percentiles_cycle: Optional[List[float]] = None
    categories: List[str] = Field(default_factory=lambda: ["PTS", "REB", "STL", "BLK", "AST"])
    value_col: str = "Value"
    year: Optional[int] = None
    roster_size: int = 13
    favorite_team: str = "CLE"
    minimum_game_threshold: float = 55
    initial_budget: float = 200
    sort_primary: str = "Price"
    out_prefix: str = "draft_plan_"
    objective_focus: str = "3PM"
    target_method: str = "monte_carlo"  # 'monte_carlo' (default) | 'historical'




@router.post("/optimizer/multiple-plans")
def optimizer_multiple_plans(body: MultiplePlansBody) -> List[dict[str, Any]]:
    pct_cycle = body.percentiles_cycle
    if pct_cycle is None:
        pct_cycle = (0.78, 0.80, 0.82, 0.84, 0.86)
    try:
        summary = generate_multiple_plans(
            n_plans=body.n_plans,
            base_excluded=body.base_excluded,
            base_percentile=body.base_percentile,
            percentiles_cycle=tuple(pct_cycle),
            categories=tuple(body.categories),
            value_col=body.value_col,
            year=body.year,
            roster_size=body.roster_size,
            favorite_team=body.favorite_team,
            minimum_game_threshold=body.minimum_game_threshold,
            initial_budget=body.initial_budget,
            sort_primary=body.sort_primary,
            out_prefix=body.out_prefix,
            objective_focus=body.objective_focus,
            target_method=body.target_method,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return _df_records(summary)


