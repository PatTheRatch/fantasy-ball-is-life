"""League / standings / rosters / scoreboard endpoints."""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, List, Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder

from backend.api.deps import (
    _df_records,
    _espn_http_exception,
    _handles,
    _my_league,
    _read_excel_bytes,
    _scoreboard,
    _snapshot_read,
)
from backend.league import data_feed as feed

router = APIRouter(tags=["league"])


def _validate_week_range(week_start_date: Optional[str], week_end_date: Optional[str]) -> None:
    """Reject an explicitly inverted roster date window with a 400.

    Only validates when the caller supplies both bounds; when either is omitted
    the data layer derives a sane window from the matchup period.
    """
    if not week_start_date or not week_end_date:
        return
    try:
        start = pd.to_datetime(week_start_date)
        end = pd.to_datetime(week_end_date)
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=422,
            detail="week_start_date/week_end_date must be valid dates (YYYY-MM-DD).",
        ) from e
    if start > end:
        raise HTTPException(
            status_code=400,
            detail=f"week_start_date ({week_start_date}) must be on or before week_end_date ({week_end_date}).",
        )

@router.get("/league/meta")
def league_meta() -> dict[str, Any]:
    try:
        h = _handles()
        return feed.pull_league_meta(h)
    except Exception as e:
        raise _espn_http_exception(e) from e


@router.get("/league/my-league/schedule")
def my_league_schedule(
    year: Optional[int] = Query(None, description="ESPN season year; defaults to config SEASON"),
) -> List[dict[str, Any]]:
    try:
        ml = _my_league(year)
        return _df_records(ml.get_schedule())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/league/my-league/current-week-matchups")
def my_league_current_week_matchups(
    year: Optional[int] = Query(None, description="ESPN season year; defaults to config SEASON"),
) -> List[dict[str, Any]]:
    try:
        ml = _my_league(year)
        return _df_records(ml.get_current_week_matchups())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/power-rankings")
def power_rankings(
    weeks: Optional[str] = Query(None, description="Comma-separated week list (ignored — snapshot is pre-computed)"),
    recent_weeks: int = Query(3, description="For API compat only (ignored)"),
) -> dict[str, Any]:
    """Read stored power rankings from the snapshot worker (P-3b)."""
    payload, fetched_at = _snapshot_read("power_rankings")
    return {"data": payload or [], "fetched_at": fetched_at}


@router.get("/confidence")
def confidence(
    projected_value: float = Query(..., description="Projected stat value to evaluate"),
    stat: str = Query(..., description="Stat name (e.g. PTS, REB, TO, FG%, FT%)"),
    player_avg: float = Query(..., description="Player season average for the stat (used for tier lookup)"),
) -> dict[str, Any]:
    try:
        from backend.analytics.consistency import get_confidence

        return get_confidence(
            projected_value=projected_value,
            stat=stat,
            player_avg=player_avg,
            db_path="data/game_logs.db",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/matchup-confidence")
def matchup_confidence(
    current_matchup_period: int = Query(..., description="ESPN current matchup period"),
    projections: str = Query("15", description="Projection source (default: ESPN Last 15)"),
    games_played: int = Query(0, description="How many matchup games have been played so far"),
    total_games: int = Query(1, description="Total expected matchup games"),
) -> List[dict[str, Any]]:
    """
    Enrich the projected scoreboard with tier/confidence per team/stat.

    Note: for now, `player_avg` is proxied by each team's projected score as requested.
    """
    try:
        h = _handles()
        from backend.analytics.consistency import get_confidence

        df = feed.get_projected_scoreboard(
            h,
            current_matchup_period=current_matchup_period,
            projections=projections,
        )

        # Convert team totals into a per-player-per-game scale so confidence is computed
        # against the same scale used by consistency.py (game_logs are per-game).
        week_meta = feed.MATCHUP_WEEKS_2025_26.get(current_matchup_period)
        week_start = week_meta["start"] if week_meta else None
        week_end = week_meta["end"] if week_meta else None
        rosters = feed.get_current_rosters(
            h,
            week_start_date=week_start,
            week_end_date=week_end,
            bbm_path=None,
            bbm_df=None,
            current_matchup_period=current_matchup_period,
            projections=projections,
        )
        rosters_df = pd.DataFrame(rosters)
        total_player_games_by_team: dict[str, float] = {}
        if not rosters_df.empty and "team_name" in rosters_df.columns and "num_games_left" in rosters_df.columns:
            # Exclude out players and ensure we only count positive game counts.
            if "injuryStatus" in rosters_df.columns:
                ok = (rosters_df["injuryStatus"].astype(str).str.upper() != "OUT") & pd.to_numeric(
                    rosters_df["num_games_left"], errors="coerce"
                ).fillna(0).gt(0)
                rosters_df = rosters_df[ok]
            else:
                rosters_df = rosters_df[pd.to_numeric(rosters_df["num_games_left"], errors="coerce").fillna(0).gt(0)]

            rosters_df["num_games_left"] = pd.to_numeric(rosters_df["num_games_left"], errors="coerce").fillna(0)
            totals = rosters_df.groupby("team_name", as_index=False)["num_games_left"].sum()
            total_player_games_by_team = {
                str(r["team_name"]): float(r["num_games_left"]) for _, r in totals.iterrows()
            }

        def _scaled_confidence(
            team_name: Any,
            projected_val: Any,
            stat_key: str,
        ) -> dict[str, Any]:
            if projected_val is None or pd.isna(projected_val):
                return {
                    "tier": None,
                    "p10": None,
                    "p25": None,
                    "mean": None,
                    "p75": None,
                    "p90": None,
                    "confidence_pct": None,
                }

            x = float(projected_val)

            # Percent categories are already ratios for the matchup period.
            if stat_key in {"fg%", "ft%"}:
                projected_value = x
                player_avg = x
            else:
                games = total_player_games_by_team.get(str(team_name))
                if not games or games <= 0:
                    # Can't scale without player-game counts.
                    projected_value = float("nan")
                    player_avg = float("nan")
                else:
                    if stat_key == "to":
                        # TO is a natural positive count; abs() defends against any
                        # legacy negative encoding so the confidence model always
                        # sees positive turnover counts for LOWER_IS_BETTER handling.
                        x = abs(x)
                    projected_value = x / games
                    player_avg = projected_value

            return get_confidence(
                projected_value=projected_value,
                stat=stat_key,
                player_avg=player_avg,
                db_path="data/game_logs.db",
                games_played=games_played,
                total_games=total_games,
            )

        enriched_rows: List[dict[str, Any]] = []
        for _, row in df.iterrows():
            rec = row.to_dict()
            stat_name = str(rec.get("stat", "")).strip().lower()

            home_team = rec.get("home_team")
            away_team = rec.get("away_team")

            home_val = rec.get("projected_home_score")
            home_res = _scaled_confidence(home_team, home_val, stat_name)
            rec["home_tier"] = home_res.get("tier")
            rec["home_confidence_pct"] = home_res.get("confidence_pct")

            away_val = rec.get("projected_away_score")
            away_res = _scaled_confidence(away_team, away_val, stat_name)
            rec["away_tier"] = away_res.get("tier")
            rec["away_confidence_pct"] = away_res.get("confidence_pct")

            enriched_rows.append(rec)

        return _df_records(pd.DataFrame(enriched_rows))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/league/teams")
def league_teams() -> List[dict[str, Any]]:
    try:
        h = _handles()
        return _df_records(feed.teams_df(h))
    except Exception as e:
        raise _espn_http_exception(e) from e


@router.get("/league/standings")
def league_standings() -> dict[str, Any]:
    """Read computed standings from the snapshot worker (P-3b)."""
    payload, fetched_at = _snapshot_read("standings")
    if payload is None:
        return {"data": [], "fetched_at": None}
    return {"data": payload, "fetched_at": fetched_at}


@router.get("/league/settings")
def league_settings() -> dict[str, Any]:
    """Read stored league settings from the snapshot worker (P-3b)."""
    payload, fetched_at = _snapshot_read("settings")
    return {"data": payload or {}, "fetched_at": fetched_at}


@router.get("/season-stats")
def season_stats(
    weeks: Optional[str] = Query(None, description="Comma-separated week list (ignored — snapshot is pre-computed)"),
) -> dict[str, Any]:
    """Read stored season stats from the snapshot worker (P-3b)."""
    payload, fetched_at = _snapshot_read("season_stats")
    return {"data": payload or [], "fetched_at": fetched_at}


@router.get("/rosters/{on_date}")
def rosters_on_date(on_date: date) -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(feed.rosters_df(h, on_date))


@router.get("/transactions")
def transactions(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
) -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(feed.transactions_df(h, start=start, end=end))


@router.get("/transactions/week")
def transactions_week(
    scoring_period: Optional[int] = Query(None, description="Week number (ignored — snapshot is pre-computed)"),
) -> dict[str, Any]:
    """Read stored weekly transactions from the snapshot worker (P-3b)."""
    payload, fetched_at = _snapshot_read("transactions")
    return {"data": payload or [], "fetched_at": fetched_at}


@router.get("/matchups")
def matchups(scoring_period: Optional[int] = None) -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(feed.matchups_df(h, scoring_period=scoring_period))


@router.get("/scoreboard/current")
def scoreboard_current(scoring_period: Optional[int] = None) -> dict[str, Any]:
    """Read stored scoreboard from the snapshot worker (P-3b)."""
    payload, fetched_at = _snapshot_read("scoreboard")
    return {"data": payload or [], "fetched_at": fetched_at}


@router.get("/rosters/current")
def rosters_current(
    week_start_date: Optional[str] = None,
    week_end_date: Optional[str] = None,
    bbm_path: Optional[str] = None,
    current_matchup_period: Optional[int] = None,
    projections: Optional[str] = Query(
        None,
        description="Projection source for roster projections (e.g. 'BBM','15','30'). Currently used for API contract compatibility only.",
    ),
) -> List[dict[str, Any]]:
    """Load weekly BBM file from disk via ``bbm_path`` (or config default). For uploads use ``POST /rosters/current``."""
    _validate_week_range(week_start_date, week_end_date)
    h = _handles()
    effective_projections = projections or "15"
    return _df_records(
        feed.get_current_rosters(
            h,
            week_start_date=week_start_date,
            week_end_date=week_end_date,
            bbm_path=bbm_path,
            bbm_df=None,
            current_matchup_period=current_matchup_period,
            projections=effective_projections,
        )
    )


@router.post("/rosters/current")
async def rosters_current_upload(
    bbm_file: Optional[UploadFile] = File(None, description="Weekly BBM projections Excel file"),
    bbm_path: Optional[str] = Form(None, description="Disk path when no file is uploaded (same as GET)"),
    week_start_date: Optional[str] = Form(None),
    week_end_date: Optional[str] = Form(None),
    current_matchup_period: Optional[str] = Form(None),
    projections: Optional[str] = Query(
        None,
        description="Projection source for roster projections (e.g. 'BBM','15','30'). When no file is uploaded, the app passes this for compatibility.",
    ),
) -> List[dict[str, Any]]:
    """Pass weekly BBM projections as an uploaded file, or use ``bbm_path`` / config default on disk."""
    _validate_week_range(week_start_date, week_end_date)
    h = _handles()
    bbm_df = None
    if bbm_file is not None and bbm_file.filename:
        raw = await bbm_file.read()
        bbm_df = _read_excel_bytes(raw)
    cmp: Optional[int] = None
    if current_matchup_period not in (None, ""):
        try:
            cmp = int(current_matchup_period)
        except ValueError:
            raise HTTPException(status_code=422, detail="current_matchup_period must be an integer") from None
    # If no file was uploaded, we *must* have a projection window specified.
    # Otherwise we'd default to BBM and try to load weekly spreadsheets from disk.
    effective_projections = projections
    if effective_projections is None:
        effective_projections = "BBM" if bbm_df is not None else None
    if effective_projections is None:
        raise HTTPException(
            status_code=422,
            detail="Missing `projections` query param when no `bbm_file` is uploaded. Use `projections=BBM|15|30`.",
        )

    # Helpful runtime trace in uvicorn logs so we can confirm which projection
    # mode the client actually requested.
    print(
        f"[rosters_current_upload] projections={projections!r} effective={effective_projections!r} "
        f"has_bbm_file={bbm_df is not None} current_matchup_period={cmp}"
    )

    return _df_records(
        feed.get_current_rosters(
            h,
            week_start_date=week_start_date,
            week_end_date=week_end_date,
            bbm_path=bbm_path,
            bbm_df=bbm_df,
            current_matchup_period=cmp,
            projections=effective_projections,
        )
    )


@router.get("/projected-scoreboard")
def projected_scoreboard(
    week_end_date: Optional[str] = None,
    current_matchup_period: Optional[int] = None,
    projections: str = "15",
) -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(
        feed.get_projected_scoreboard(
            h,
            week_end_date=week_end_date,
            current_matchup_period=current_matchup_period,
            projections=projections,
            bbm_df=None,
        )
    )


@router.post("/projected-scoreboard")
async def projected_scoreboard_upload(request: Request) -> List[dict[str, Any]]:
    """
    Same output as GET /projected-scoreboard, but accepts multipart form:
    - `data`: JSON string with keys: current_matchup_period (int), projections (str), optional week_end_date (str)
    - `bbm_file`: optional Excel upload (used when projections is BBM)
    """
    import json as _json

    h = _handles()
    form = await request.form()
    data_raw = form.get("data")
    if data_raw is None:
        raise HTTPException(
            status_code=422,
            detail="multipart form must include `data` (JSON string) with at least current_matchup_period",
        )
    if isinstance(data_raw, bytes):
        data_raw = data_raw.decode("utf-8")
    payload = _json.loads(str(data_raw))
    week_end_date = payload.get("week_end_date")
    current_matchup_period = payload.get("current_matchup_period")
    projections = payload.get("projections", "15")

    bbm_df = None
    up = form.get("bbm_file")
    if up is not None and hasattr(up, "read"):
        raw = await up.read()
        if raw:
            bbm_df = _read_excel_bytes(raw)

    try:
        return _df_records(
            feed.get_projected_scoreboard(
                h,
                week_end_date=week_end_date,
                current_matchup_period=current_matchup_period,
                projections=projections,
                bbm_df=bbm_df,
            )
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
