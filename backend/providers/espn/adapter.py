"""ESPN provider adapter: map ``espn_api`` objects into FCP DTOs.

Charter §7 — adapters live at the boundary and never become the domain model.
This module *constructs* an ``espn_api.basketball.League`` (composition, never
subclassing) and maps its settings/teams/schedule into the pure DTOs in
``backend.domain.dto``. No ``espn_api`` object is ever returned or stored on a
DTO, and the ``League`` class is never subclassed or its loaders overridden —
the §7 violation V1 built its domain on.

The S1-02 transport gateway's timeout policy is wired here — this is the first
code that actually issues ESPN reads — via :func:`install_espn_timeout_patch`
at construction (idempotent).

The mapping functions are pure (they take a duck-typed league-like object) so
they are hermetic-testable without the SDK or a network. ``_construct_league``
is the single seam where ``espn_api`` is touched; tests patch it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from backend.domain.dto import (
    LeagueSettingsDTO,
    MatchupPeriodDTO,
    PeriodType,
    ScoreboardDTO,
    ScoreboardMatchupDTO,
    ScoreboardTeamStatsDTO,
    TeamDTO,
)
from backend.providers.espn.client import install_espn_timeout_patch

DEFAULT_TIMEZONE = "America/New_York"

#: ESPN basketball leagues are ET-based; the schema's default ``timezone``.
_DEFAULT_TZ = ZoneInfo(DEFAULT_TIMEZONE)

#: ESPN stat abbreviation → FCP canonical stat key. The sync service reads a
#: league's ``Category`` rows by their FCP key (``TPM``, ``fgm``, ``fga`` …) with
#: no provider knowledge (D11); this map is the provider-specific translation.
#: Ratio components are passed through (``FGM``/``FGA``/``FTM``/``FTA``) so the
#: sync service derives FG%/FT% itself and aggregation stays correct — ESPN's
#: precomputed ``FG%``/``FT%`` are deliberately dropped.
ESPN_STAT_KEY_MAP: dict[str, str] = {
    "PTS": "PTS",
    "REB": "REB",
    "AST": "AST",
    "STL": "STL",
    "BLK": "BLK",
    "3PM": "TPM",
    "TO": "TO",
    "FGM": "fgm",
    "FGA": "fga",
    "FTM": "ftm",
    "FTA": "fta",
}

#: ESPN ``winner`` → FCP ``matchup_result``. ``UNDECIDED``/unknown → None.
_WINNER_MAP: dict[str, str] = {"HOME": "home", "AWAY": "away", "TIE": "tie"}


@dataclass(frozen=True, slots=True)
class EspnConnection:
    """Credentials for one ESPN league (the S1-08 ``provider_connections`` row
    will hold these encrypted; for now they are a plain value object)."""

    league_id: str
    swid: str
    espn_s2: str


def _construct_league(conn: EspnConnection, season_year: int) -> Any:
    """Build the espn_api League for ``conn``/``season_year``.

    The only place ``espn_api`` is imported or touched. Composition, not
    subclassing. ``season_year`` is the *ending* year, matching ESPN's ``year``
    argument and ``nba_seasons.season_year`` (03-nba).
    """
    from espn_api.basketball import League

    return League(
        league_id=int(conn.league_id),
        year=season_year,
        espn_s2=conn.espn_s2,
        swid=conn.swid,
    )


def map_settings(league: Any, conn: EspnConnection, season_year: int) -> LeagueSettingsDTO:
    """Map ``league.settings`` into a :class:`LeagueSettingsDTO`.

    Fields the SDK does not expose are left ``None`` — reported honestly, never
    invented (D28). ``scoring_type`` in particular is load-bearing (category vs
    points league), so a missing value stays ``None`` for the ingest pipeline to
    fail visibly on, rather than being coerced to an empty string.
    """
    s = league.settings
    return LeagueSettingsDTO(
        provider_league_id=str(conn.league_id),
        season_year=season_year,
        scoring_type=s.scoring_type,
        timezone=DEFAULT_TIMEZONE,
        team_count=s.team_count,
        playoff_team_count=s.playoff_team_count,
        regular_season_periods=s.reg_season_count,
        acquisition_budget=s.acquisition_budget,
        uses_faab=bool(s.faab) if s.faab is not None else None,
    )


def map_teams(league: Any) -> list[TeamDTO]:
    """Map ``league.teams`` into :class:`TeamDTO` list, sorted by provider id."""
    dtos = [
        TeamDTO(
            provider_team_id=str(t.team_id),
            name=t.team_name,
            abbreviation=t.team_abbrev,
            logo_url=t.logo_url or None,
        )
        for t in league.teams
    ]
    return sorted(dtos, key=lambda d: d.provider_team_id)


def _epoch_ms_to_date(epoch_ms: int) -> date:
    """Convert ESPN's epoch-millisecond game timestamp to a calendar date.

    ESPN's ``proGamesByScoringPeriod`` game ``date`` field is epoch milliseconds
    (``espn_api/basketball/player.py``: ``datetime.fromtimestamp(game['date']/1000.0)``).
    Conversion is in the league's timezone (ET by default) so a late-evening game
    lands on its fantasy day rather than the next UTC day.
    """
    return datetime.fromtimestamp(epoch_ms / 1000.0, tz=_DEFAULT_TZ).date()


def _scoring_period_dates(league: Any) -> dict[int, set[date]]:
    """Flatten ``proGamesByScoringPeriod`` into ``scoring_period_id → dates``.

    The pro schedule is per-team (``{pro_team_id: {scoring_period_id: [games]}}``)
    and each game appears once per participating team, so a scoring period's
    dates are the union across teams (deduped by set). Scoring periods with no
    games (the All-Star break ids) contribute no dates and are simply absent.
    """
    dates: dict[int, set[date]] = {}
    for team_schedule in league._get_all_pro_schedule().values():
        for period_id, games in team_schedule.items():
            if not games:
                continue
            for game in games:
                epoch_ms = game.get("date")
                if epoch_ms:
                    dates.setdefault(int(period_id), set()).add(
                        _epoch_ms_to_date(int(epoch_ms))
                    )
    return dates


def map_periods(league: Any) -> list[MatchupPeriodDTO]:
    """Map ``league.settings.matchup_periods`` into periods with derived dates.

    Dates come from the pro schedule, never arithmetic (S1-03). ``type`` is
    derived from the regular/playoff split: ordinal ≤ ``reg_season_count`` is
    regular, the rest playoff — championship/consolation distinction is a later
    refinement. A period whose scoring periods have no games gets ``None`` dates
    rather than an invented range.
    """
    s = league.settings
    matchup_periods: dict[str, list[int]] = s.matchup_periods
    regular_count: int = s.reg_season_count
    dates_by_period = _scoring_period_dates(league)

    dtos: list[MatchupPeriodDTO] = []
    for key, scoring_period_ids in matchup_periods.items():
        ordinal = int(key)
        period_type = PeriodType.REGULAR if ordinal <= regular_count else PeriodType.PLAYOFF

        all_dates: set[date] = set()
        for scoring_period_id in scoring_period_ids:
            all_dates |= dates_by_period.get(scoring_period_id, set())

        dtos.append(
            MatchupPeriodDTO(
                ordinal=ordinal,
                type=period_type,
                provider_period_id=key,
                start_date=min(all_dates) if all_dates else None,
                end_date=max(all_dates) if all_dates else None,
            )
        )

    return sorted(dtos, key=lambda p: p.ordinal)


def _map_team_stats(
    team: Any, team_cats: dict[str, dict[str, float | str]] | None
) -> ScoreboardTeamStatsDTO:
    """Map one side's raw stats into a :class:`ScoreboardTeamStatsDTO`.

    ``team`` is an ``espn_api`` Team (with ``.team_id``) for a real opponent, or
    ``0``/falsy for a bye. ``team_cats`` is ESPN's ``{abbrev: {'score', 'result'}}``;
    keys are translated to FCP canonical stat keys via :data:`ESPN_STAT_KEY_MAP`.
    """
    provider_team_id = str(team.team_id) if hasattr(team, "team_id") else None
    stats: dict[str, float | None] = {}
    if team_cats:
        for abbrev, cell in team_cats.items():
            key = ESPN_STAT_KEY_MAP.get(abbrev)
            if key is not None:
                raw = cell.get("score")
                stats[key] = float(raw) if raw is not None else None
    return ScoreboardTeamStatsDTO(provider_team_id=provider_team_id, stats=stats)


def map_scoreboard(league: Any, provider_period_id: str) -> ScoreboardDTO:
    """Map a period's ``box_scores`` into a :class:`ScoreboardDTO`.

    A matchup with no away team (``away_team`` stays ``0`` from the SDK) is a
    bye: ``away`` is ``None`` rather than a zero-filled ghost team (02-fantasy:
    the V1 playoff all-play bug came from zero-filling missing matchups).
    """
    boxes = league.box_scores(matchup_period=int(provider_period_id))
    matchups = tuple(
        ScoreboardMatchupDTO(
            home=_map_team_stats(box.home_team, box.home_team_cats),
            away=(
                _map_team_stats(box.away_team, box.away_team_cats)
                if hasattr(box.away_team, "team_id")
                else None
            ),
            provider_result=_WINNER_MAP.get(box.winner),
        )
        for box in boxes
    )
    return ScoreboardDTO(provider_period_id=provider_period_id, matchups=matchups)


class ESPNAdapter:
    """Fetches ESPN league data and returns FCP DTOs."""

    def __init__(self) -> None:
        install_espn_timeout_patch()

    def fetch_settings(self, conn: EspnConnection, season_year: int) -> LeagueSettingsDTO:
        return map_settings(_construct_league(conn, season_year), conn, season_year)

    def fetch_teams(self, conn: EspnConnection, season_year: int) -> list[TeamDTO]:
        return map_teams(_construct_league(conn, season_year))

    def fetch_periods(self, conn: EspnConnection, season_year: int) -> list[MatchupPeriodDTO]:
        return map_periods(_construct_league(conn, season_year))

    def fetch_scoreboard(
        self, conn: EspnConnection, season_year: int, provider_period_id: str
    ) -> ScoreboardDTO:
        return map_scoreboard(_construct_league(conn, season_year), provider_period_id)
