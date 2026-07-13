"""Shared FastAPI helpers used by routers and the app factory.

Kept separate from ``main`` so routers can import helpers without a
``main`` ↔ ``routers`` circular import.
"""
from __future__ import annotations

import io
from typing import Any, List, Optional

import numpy as np
import pandas as pd
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from backend.config import LEAGUE_ID, SEASON
from backend.league import data_feed as feed
from backend.league.fantasy import MyLeague
from backend.league.gateway import espn_error_status_code


def _my_league(year: Optional[int] = None) -> MyLeague:
    """``MyLeague`` for in-season endpoints; uses ``SEASON`` from config when year is omitted.

    Cached per request via ``ESPNRequestCache`` (PR F). The first call constructs
    a new ``MyLeague`` (4 ESPN requests); subsequent calls inside the same HTTP
    request reuse the cached instance.
    """
    from backend.league.cache import get_request_cache

    y = SEASON if year is None else year
    cache = get_request_cache()
    if cache is not None:
        existing = cache.get_my_league(LEAGUE_ID, y)
        if existing is not None:
            return existing

    ml = MyLeague(LEAGUE_ID, y)

    if cache is not None:
        cache.put_my_league(LEAGUE_ID, y, ml)

    return ml


def _strip_numpy(obj: Any) -> Any:
    """Convert numpy/pandas scalar values to native Python for jsonable_encoder."""
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _strip_numpy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_numpy(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_strip_numpy(x) for x in obj)
    return obj


def _df_records(df: Optional[pd.DataFrame]) -> List[dict[str, Any]]:
    if df is None:
        return []
    out = df.where(pd.notnull(df), None)
    return jsonable_encoder(_strip_numpy(out.to_dict(orient="records")))


def _handles():
    return feed.connect()


def _espn_http_exception(e: Exception) -> HTTPException:
    """Map an ESPN-origin failure to its HTTP status: 504 for a gateway
    timeout, 502 for any other upstream/transport failure, 500 otherwise
    (unchanged fallback for non-ESPN errors)."""
    return HTTPException(status_code=espn_error_status_code(e), detail=str(e))


def _read_excel_bytes(data: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(data))
