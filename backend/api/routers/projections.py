"""Projections upload + feed-run endpoints."""
from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field

from backend.api.deps import _df_records, _read_excel_bytes
from backend.league import data_feed as feed

router = APIRouter(tags=["projections"])

@router.get("/projections")
def projections(path: Optional[str] = None) -> List[dict[str, Any]]:
    """Read season projections from disk. For uploads use ``POST /projections``."""
    return _df_records(feed.read_projections_xls(path=path))


@router.post("/projections")
async def projections_upload(
    file: Optional[UploadFile] = File(None, description="Season BBM projections Excel file"),
    path: Optional[str] = Form(None, description="Optional disk path if file is omitted"),
) -> List[dict[str, Any]]:
    """Normalize season BBM projections from an uploaded file, or from ``path`` when no file is sent."""
    if file is not None and file.filename:
        raw = await file.read()
        df = _read_excel_bytes(raw)
        return _df_records(feed.read_projections_xls(projections_df=df))
    return _df_records(feed.read_projections_xls(path=path))


class RunFeedBody(BaseModel):
    since: str = Field(..., description="YYYY-MM-DD or 'today'")
    until: str = Field(..., description="YYYY-MM-DD or 'today'")
    outdir: Optional[str] = None
    week_start_date: Optional[str] = None
    week_end_date: Optional[str] = None
    current_matchup_period: Optional[int] = None


@router.post("/feed/run")
def feed_run(body: RunFeedBody) -> dict[str, Any]:
    since = feed._parse_date(body.since)
    until = feed._parse_date(body.until)
    return feed.run(
        since,
        until,
        outdir=body.outdir,
        week_start_date=body.week_start_date,
        week_end_date=body.week_end_date,
        current_matchup_period=body.current_matchup_period,
    )


