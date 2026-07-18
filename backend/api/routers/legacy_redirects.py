"""P-4b: Redirect old flat league paths to slug-scoped paths.

Kept for one release so bookmarks and external callers don't break
mid-migration. Each old path → 307 Temporary Redirect to the new
``/leagues/{slug}/...`` path, preserving the query string.

Remove this module after the cutover release.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse

from backend.league.credentials import (
    get_league_context,
    resolve_league_context,
)

router = APIRouter(tags=["legacy-redirects"])


def _redirect(request: Request, path: str) -> RedirectResponse:
    """307 redirect to the slug-scoped path, preserving query string."""
    ctx = get_league_context() or resolve_league_context()
    slug = ctx.slug if ctx else "patriot-games"
    qs = request.url.query
    url = f"/leagues/{slug}{path}"
    if qs:
        url = f"{url}?{qs}"
    return RedirectResponse(url=url, status_code=307)


# ── GET redirects ─────────────────────────────────────────────────────────────

@router.get("/league/meta")
def _r_league_meta(request: Request):
    return _redirect(request, "/meta")

@router.get("/league/my-league/schedule")
def _r_schedule(request: Request):
    return _redirect(request, "/schedule")

@router.get("/league/my-league/current-week-matchups")
def _r_current_week_matchups(request: Request):
    return _redirect(request, "/matchups/current-week")

@router.get("/power-rankings")
def _r_power_rankings(request: Request):
    return _redirect(request, "/power-rankings")

@router.get("/confidence")
def _r_confidence(request: Request):
    return _redirect(request, "/confidence")

@router.get("/matchup-confidence")
def _r_matchup_confidence(request: Request):
    return _redirect(request, "/matchup-confidence")

@router.get("/league/teams")
def _r_league_teams(request: Request):
    return _redirect(request, "/teams")

@router.get("/league/standings")
def _r_league_standings(request: Request):
    return _redirect(request, "/standings")

@router.get("/league/settings")
def _r_league_settings(request: Request):
    return _redirect(request, "/settings")

@router.get("/season-stats")
def _r_season_stats(request: Request):
    return _redirect(request, "/season-stats")

@router.get("/rosters/{on_date}")
def _r_rosters_date(request: Request, on_date: str):
    return _redirect(request, f"/rosters/{on_date}")

@router.get("/transactions")
def _r_transactions(request: Request):
    return _redirect(request, "/transactions")

@router.get("/transactions/week")
def _r_transactions_week(request: Request):
    return _redirect(request, "/transactions/week")

@router.get("/matchups")
def _r_matchups(request: Request):
    return _redirect(request, "/matchups")

@router.get("/scoreboard/current")
def _r_scoreboard_current(request: Request):
    return _redirect(request, "/scoreboard/current")

@router.get("/rosters/current")
def _r_rosters_current(request: Request):
    return _redirect(request, "/rosters/current")

@router.get("/projected-scoreboard")
def _r_projected_scoreboard(request: Request):
    return _redirect(request, "/projected-scoreboard")
