"""P-4b: Redirect old flat league paths to slug-scoped paths.

Kept for one release so bookmarks and external callers don't break
mid-migration. Each old path → 307 Temporary Redirect to the new
``/leagues/{slug}/...`` path.

Remove this module after the cutover release.
"""

from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import RedirectResponse

from backend.league.credentials import get_league_context

router = APIRouter(tags=["legacy-redirects"])

# Default slug when no league context is available (single-league interim)
_DEFAULT_SLUG = "patriot-games"


def _redirect(path: str, *, keep_params: bool = True) -> RedirectResponse:
    """307 redirect to the slug-scoped path."""
    ctx = get_league_context()
    slug = ctx.slug if ctx else _DEFAULT_SLUG
    return RedirectResponse(
        url=f"/leagues/{slug}{path}",
        status_code=307,
    )


# ── GET redirects ─────────────────────────────────────────────────────────────

@router.get("/league/meta")
def _r_league_meta():
    return _redirect("/meta")

@router.get("/league/my-league/schedule")
def _r_schedule():
    return _redirect("/schedule")

@router.get("/league/my-league/current-week-matchups")
def _r_current_week_matchups():
    return _redirect("/matchups/current-week")

@router.get("/power-rankings")
def _r_power_rankings():
    return _redirect("/power-rankings")

@router.get("/confidence")
def _r_confidence():
    return _redirect("/confidence")

@router.get("/matchup-confidence")
def _r_matchup_confidence():
    return _redirect("/matchup-confidence")

@router.get("/league/teams")
def _r_league_teams():
    return _redirect("/teams")

@router.get("/league/standings")
def _r_league_standings():
    return _redirect("/standings")

@router.get("/league/settings")
def _r_league_settings():
    return _redirect("/settings")

@router.get("/season-stats")
def _r_season_stats():
    return _redirect("/season-stats")

@router.get("/rosters/{on_date}")
def _r_rosters_date(on_date: str):
    return _redirect(f"/rosters/{on_date}")

@router.get("/transactions")
def _r_transactions():
    return _redirect("/transactions")

@router.get("/transactions/week")
def _r_transactions_week():
    return _redirect("/transactions/week")

@router.get("/matchups")
def _r_matchups():
    return _redirect("/matchups")

@router.get("/scoreboard/current")
def _r_scoreboard_current():
    return _redirect("/scoreboard/current")

@router.get("/rosters/current")
def _r_rosters_current():
    return _redirect("/rosters/current")

@router.get("/projected-scoreboard")
def _r_projected_scoreboard():
    return _redirect("/projected-scoreboard")
