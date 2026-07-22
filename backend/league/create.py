"""Shared ESPN league validation — reusable across N-4a/N-4b/N-4c.

Constructs an ESPN ``League`` handle directly (bypassing ``connect()``
and its DB-context fallback) so validation works for *any* league ID,
not just the one seeded in the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from espn_api.basketball import League
from espn_api.requests.espn_requests import ESPNAccessDenied, ESPNInvalidLeague

from backend.league.data_feed import ESPNHandles, pull_league_meta


@dataclass(frozen=True)
class LeagueValidation:
    """Typed result from ``validate_espn_league``.

    Callers inspect ``valid``; on success, ``name`` / ``teams`` /
    ``scoring_type`` / ``season`` / ``team_names`` are populated.
    On failure, ``error_code`` and ``error_message`` are set.
    """

    valid: bool
    error_code: str | None = None
    error_message: str | None = None
    name: str | None = None
    teams: int | None = None
    scoring_type: str | None = None
    season: int | None = None
    team_names: list[str] = field(default_factory=list)


def validate_espn_league(
    *,
    espn_league_id: int,
    season: int,
    swid: str | None = None,
    espn_s2: str | None = None,
) -> LeagueValidation:
    """Fetch ESPN league metadata without touching the database.

    Does NOT use ``connect()`` — that function falls back to
    ``resolve_league_context()`` when params are None, which would
    silently validate against the seeded league instead of the
    user-supplied ID.

    Returns ``LeagueValidation(valid=True, ...)`` on success, or
    ``LeagueValidation(valid=False, error_code=..., ...)`` on a
    recognised ESPN error.
    """
    try:
        league = League(
            league_id=espn_league_id,
            year=season,
            espn_s2=espn_s2,
            swid=swid,
        )
    except ESPNAccessDenied as exc:
        msg = str(exc)
        if "espn_s2 and swid are required" in msg.lower():
            return LeagueValidation(
                valid=False,
                error_code="private_league",
                error_message=(
                    "This league is private. Please provide your ESPN S2 and SWID "
                    "cookies so we can verify league access."
                ),
            )
        return LeagueValidation(
            valid=False,
            error_code="bad_cookies",
            error_message=(
                "ESPN rejected the provided credentials. "
                "Please check your ESPN S2 and SWID cookies and try again."
            ),
        )
    except ESPNInvalidLeague as exc:
        return LeagueValidation(
            valid=False,
            error_code="not_found",
            error_message=str(exc),
        )
    except Exception as exc:
        return LeagueValidation(
            valid=False,
            error_code="espn_unavailable",
            error_message=(
                f"ESPN is currently unreachable ({type(exc).__name__}). "
                "Please try again in a few minutes."
            ),
        )

    handles = ESPNHandles(league=league)
    meta: dict[str, Any] = pull_league_meta(handles)

    # Extract team names from the constructed league
    team_names: list[str] = [
        t.team_name for t in league.teams
    ]

    return LeagueValidation(
        valid=True,
        name=meta["league_name"],
        teams=meta["teams"],
        scoring_type=meta["scoring_type"],
        season=meta["season"],
        team_names=team_names,
    )
