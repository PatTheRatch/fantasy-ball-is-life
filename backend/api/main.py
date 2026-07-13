"""
FastAPI layer over `backend.league.data_feed` and `backend.draft.optimizer` —
thin wrappers only; no business-logic changes.

App factory lives here; shared helpers are in ``backend.api.deps``; route
handlers are split into ``backend.api.routers.*`` (BACKEND_RESTRUCTURE §4 PR 2).
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Re-export helpers so existing `from backend.api.main import _df_records`
# call sites (tests, etc.) keep working.
from backend.api.deps import (  # noqa: F401
    _df_records,
    _handles,
    _my_league,
    _read_excel_bytes,
    _strip_numpy,
)

# Load local environment variables (e.g. ANTHROPIC_API_KEY) when running the dev server.
# This keeps `ANTHROPIC_API_KEY` setup simple even if it's not exported in the shell.
# Uses backend.config.PROJECT_ROOT rather than a second hand-rolled relative
# path -- this file moved one directory deeper (backend/api/) in the package
# restructure, and a bare `Path(__file__).resolve().parent` here would land
# on backend/api/ instead of the repo root where .env actually lives.
try:
    from dotenv import load_dotenv

    from backend.config import PROJECT_ROOT

    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
except Exception:
    # If `python-dotenv` isn't installed or .env doesn't exist, we'll just rely on real env vars.
    pass

from backend.league.cache import ESPNRequestCacheMiddleware

app = FastAPI(title="PatriotGames Fantasy API", version="0.1.0")

# ESPN request cache: reuses one League construction per request. The recap's
# assemble_weekly_snapshot() calls connect() 4 separate times; this deduplicates
# those to one construction (12 fewer ESPN requests, ~22 → ~10). The remaining
# MyLeague constructions (power rankings, season stats) are PR F's concern.
app.add_middleware(ESPNRequestCacheMiddleware)

# Browser dev: any localhost / 127.0.0.1 port (Vite may use 5174+, etc.) + common LAN preview IPs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3})(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


from backend.api.routers import (  # noqa: E402
    commentary,
    draft,
    league,
    optimizer,
    projections,
    recaps,
)

app.include_router(league.router)
app.include_router(draft.router)
app.include_router(commentary.router)
app.include_router(projections.router)
app.include_router(optimizer.router)
app.include_router(recaps.router)
