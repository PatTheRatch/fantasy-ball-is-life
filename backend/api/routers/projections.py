"""Projection-source framework endpoints (P-2).

Four endpoints per spec §4:

- ``POST /projections``   — upload (multipart) → store parquet + manifest
- ``GET /projections``     — active set rows (``?source=&horizon=`` filters)
- ``GET /projections/sets`` — list uploaded sets
- ``PUT /projections/active`` — activate a previously-uploaded set

The old ``GET/POST /projections`` that called ``read_projections_xls``
are replaced.  Existing callers of those legacy endpoints migrate in P-4
(upload UI).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from backend.api.deps import _df_records, _read_excel_bytes
from backend.projections.registry import _get_store
from backend.projections.store import ProjectionStore

router = APIRouter(tags=["projections"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class ActivateBody(BaseModel):
    set_id: str


# ---------------------------------------------------------------------------
# POST /projections — upload
# ---------------------------------------------------------------------------

@router.post("/projections")
async def projections_upload(
    file: Optional[UploadFile] = File(None, description="BBM projections Excel file (season or weekly)"),
    path: Optional[str] = Form(None, description="On-disk path when no file is uploaded"),
    source: str = Form("bbm", description="Projection source (default: bbm)"),
    horizon: Optional[str] = Form(None, description="'season' or 'week'; auto-detected when omitted"),
) -> Dict[str, Any]:
    """Ingest a projection file into the on-disk store.

    Flow: read Excel → adapter.parse() → name-resolve against ESPN
    rosters (fuzzy-match) → store.save_set() → return ProjectionSet
    metadata with match report.
    """
    from backend.league.data_feed import normalize_name

    # ---- read the raw DataFrame ----
    if file is not None and file.filename:
        raw_bytes = await file.read()
        raw_df = _read_excel_bytes(raw_bytes)
        filename = file.filename
    elif path is not None:
        import pandas as pd
        raw_df = pd.read_excel(path, dtype=str)
        filename = path.rsplit("/", 1)[-1] if "/" in path else path
    else:
        raise HTTPException(status_code=422, detail="Either `file` or `path` is required.")

    # ---- adapter: detect + parse ----
    if source == "bbm":
        from backend.projections.bbm_adapter import BbmAdapter
        adapter = BbmAdapter()
        if horizon is None:
            # Auto-detect: sniff columns
            conf = adapter.detect(raw_df=raw_df)
            if conf < 0.5:
                raise HTTPException(
                    status_code=422,
                    detail="Could not auto-detect BBM export format. Specify `horizon` explicitly.",
                )
        rows = adapter.parse(raw_df=raw_df, horizon=horizon)
    else:
        raise HTTPException(status_code=422, detail=f"Unknown source: {source}")

    # ---- name-resolution against current ESPN rosters ----
    from backend.api.deps import _handles
    try:
        handles = _handles()
        league = getattr(handles, "league", None)
        # Build set of known player keys from live rosters
        known_keys: set[str] = set()
        if league is not None and hasattr(league, "teams"):
            for team in league.teams:
                for player in team.roster:
                    known_keys.add(normalize_name(player.name))
    except Exception:
        # ESPN unavailable — skip matching, still ingest the file
        known_keys = set()

    matched = 0
    unmatched: list[str] = []
    if known_keys:
        from rapidfuzz import fuzz, process

        # Build a lookup list of known normalized names
        known_list = list(known_keys)
        for r in rows:
            if r.player_key in known_keys:
                matched += 1
                continue
            # Fuzzy match against known names
            if known_list:
                best = process.extractOne(r.player_key, known_list, scorer=fuzz.WRatio)
                if best and best[1] >= 80:
                    matched += 1
                    continue
            unmatched.append(r.display_name)
    else:
        matched = len(rows)

    # ---- persist ----
    # horizon is either explicit from the form field, or auto-detected
    effective_horizon = horizon or _infer_horizon_from_df(raw_df)
    # For week-horizon uploads, default the week from the current
    # ESPN matchup period so the set auto-expires at week rollover.
    # Must use the same value load_active receives (caller's
    # current_matchup_period, or ESPN live if none provided).
    upload_week: Optional[int] = None
    if effective_horizon == "week":
        try:
            from backend.api.deps import _handles
            h2 = _handles()
            upload_week = int(getattr(h2.league, "currentMatchupPeriod", 0) or 0)
        except Exception:
            upload_week = None
        if upload_week is None or upload_week <= 0:
            raise HTTPException(
                status_code=422,
                detail="Cannot determine current matchup week. "
                       "Week-horizon uploads require a valid ESPN matchup period. "
                       "Retry during an active matchup week.",
            )

    store = _get_store()
    pset = store.save_set(
        rows,
        source=source,
        horizon=effective_horizon,
        filename=filename,
        uploaded_at=datetime.now(timezone.utc).isoformat(),
        matched_count=matched,
        unmatched_players=unmatched,
        week=upload_week,
    )

    return {
        "set_id": pset.set_id,
        "source": pset.source,
        "horizon": pset.horizon,
        "uploaded_at": pset.uploaded_at,
        "filename": pset.filename,
        "row_count": pset.row_count,
        "matched_count": pset.matched_count,
        "unmatched_players": pset.unmatched_players,
        "week": pset.week,
    }


# ---------------------------------------------------------------------------
# GET /projections — active set rows
# ---------------------------------------------------------------------------

@router.get("/projections")
def projections_get(
    horizon: Optional[str] = Query(None, description="Filter by horizon ('season' or 'week')"),
    source: Optional[str] = Query(None, description="Filter by source ('bbm', etc.)"),
) -> List[Dict[str, Any]]:
    """Return canonical rows for active sets, optionally filtered.

    When no filters are given, returns the union of active season + week sets
    (rows from both horizons).
    """
    store = _get_store()
    all_rows: List[Dict[str, Any]] = []

    horizons_to_load = [horizon] if horizon else ["season", "week"]
    for h in horizons_to_load:
        if source:
            # Only load if the *active* set for this horizon matches the filter
            active_id = store._manifest.active.get(h)
            if not active_id:
                continue
            active_set = next((s for s in store.list_sets() if s.set_id == active_id), None)
            if not active_set or active_set.source != source:
                continue

        rows = store.load_active(h)
        if rows is None:
            continue
        for r in rows:
            d = _projection_to_dict(r)
            d["_horizon"] = h
            all_rows.append(d)

    return all_rows


# ---------------------------------------------------------------------------
# GET /projections/sets — list sets
# ---------------------------------------------------------------------------

@router.get("/projections/sets")
def projections_sets(
    source: Optional[str] = Query(None),
    horizon: Optional[str] = Query(None),
) -> List[Dict[str, Any]]:
    """List all uploaded projection sets with provenance + match quality."""
    store = _get_store()
    sets = store.list_sets(source=source, horizon=horizon)
    return [{
        "set_id": s.set_id,
        "source": s.source,
        "horizon": s.horizon,
        "uploaded_at": s.uploaded_at,
        "filename": s.filename,
        "row_count": s.row_count,
        "matched_count": s.matched_count,
        "unmatched_players": s.unmatched_players,
    } for s in sets]


# ---------------------------------------------------------------------------
# PUT /projections/active — activate a set
# ---------------------------------------------------------------------------

@router.put("/projections/active")
def projections_activate(body: ActivateBody) -> Dict[str, Any]:
    """Promote a previously-uploaded set (or the virtual ESPN set via
    ``espn-live``) to active for its horizon.

    For the ``season`` horizon, clearing or expiring the active set falls
    back to the draft optimizer's legacy on-disk ``BBM_PROJECTIONS_PATH``
    read (wiring the optimizer to ``get_active_projections('season')`` is
    P-8).
    """
    store = _get_store()
    ok = store.set_active(body.set_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Set '{body.set_id}' not found.")
    return {"status": "ok", "set_id": body.set_id}


@router.delete("/projections/active")
def projections_clear(horizon: str = Query("week", description="Horizon to clear ('week' or 'season')")) -> Dict[str, Any]:
    """Clear the active set for ``horizon``, reverting to the default source.

    ``week``  → live ESPN (EspnAdapter)
    ``season`` → legacy on-disk BBM_PROJECTIONS_PATH (optimizer P-8)
    """
    store = _get_store()
    store.clear_horizon(horizon)
    return {"status": "ok", "horizon": horizon, "message": f"Reverted {horizon} to default source."}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _projection_to_dict(r: Any) -> Dict[str, Any]:
    """Convert a PlayerProjection to a JSON-safe dict."""
    return {
        "player_key": r.player_key,
        "display_name": r.display_name,
        "team": r.team,
        "positions": r.positions,
        "games": r.games,
        "minutes_pg": r.minutes_pg,
        "pts_pg": r.pts_pg,
        "reb_pg": r.reb_pg,
        "ast_pg": r.ast_pg,
        "stl_pg": r.stl_pg,
        "blk_pg": r.blk_pg,
        "tpm_pg": r.tpm_pg,
        "to_pg": r.to_pg,
        "fga_pg": r.fga_pg,
        "fta_pg": r.fta_pg,
        "fg_pct": r.fg_pct,
        "ft_pct": r.ft_pct,
        "value": r.value,
        "injury_status": r.injury_status,
    }


def _infer_horizon_from_df(df: Any) -> str:
    """Guess 'season' vs 'week' from header columns."""
    from backend.projections.bbm_adapter import _SEASON_SIGNATURE, _WEEKLY_SIGNATURE
    cols = {str(c).strip().lower() for c in df.columns}
    if len(_SEASON_SIGNATURE & cols) >= 7:
        return "season"
    if len(_WEEKLY_SIGNATURE & cols) >= 7:
        return "week"
    return "season"  # safe default
