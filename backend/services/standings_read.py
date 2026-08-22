"""Standings read path: fold stored matchups into a ranked table.

Standings are **not stored** (02-fantasy.md): they are a deterministic fold over
``matchups`` + ``matchup_category_results`` for ``final`` periods 1..N. This
service reads the facts S1-10a persisted, counts each matchup's category
outcomes, and folds them with the pure domain ``standings_through``. It does NOT
re-run ``tally`` — the per-category ``result`` was already computed at sync time
and stored on ``matchup_category_results``.

Only ``final`` periods are read, so freshness is always ``"final"`` and never
stale; ``as_of`` is the latest included period's ``end_date``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from backend.domain.standings import MatchupResult, standings_through
from backend.models.fantasy import MatchupCategoryResult
from backend.repos.matchups import LeagueSeasonRepository, MatchupRepository


class StandingsReadError(Exception):
    """The standings could not be assembled (unknown team reference)."""


@dataclass(frozen=True, slots=True)
class StandingTeamRow:
    """One team's folded record, enriched with its display fields."""

    rank: int
    team_id: uuid.UUID
    team_name: str
    team_abbreviation: str | None
    wins: int
    losses: int
    ties: int
    win_pct: float
    played: int
    unknown: int


@dataclass(frozen=True, slots=True)
class StandingsResult:
    """The folded table plus its freshness envelope.

    ``complete`` is True only when every folded category was decided; an
    ``unknown`` category is never a result, so its presence is surfaced rather
    than silently dropped (charter §10).
    """

    rows: tuple[StandingTeamRow, ...]
    as_of: date | None  # max end_date of included periods; None pre-season
    freshness: str  # always "final" — only final periods are folded
    stale: bool  # always False — final history never goes stale
    complete: bool  # True iff no folded category outcome was unknown
    unknown_category_count: int  # season total of undetermined category outcomes


def _group_by_matchup(
    results: list[MatchupCategoryResult],
) -> dict[uuid.UUID, list[MatchupCategoryResult]]:
    grouped: dict[uuid.UUID, list[MatchupCategoryResult]] = {}
    for r in results:
        grouped.setdefault(r.matchup_id, []).append(r)
    return grouped


class StandingsReadService:
    """Folds a league_season's final periods into standings + freshness."""

    def __init__(
        self,
        league_seasons: LeagueSeasonRepository,
        matchups: MatchupRepository,
    ) -> None:
        self.league_seasons = league_seasons
        self.matchups = matchups

    def standings(
        self, league_season_id: uuid.UUID, *, through_period: int | None = None
    ) -> StandingsResult:
        periods = self.league_seasons.final_periods(league_season_id)
        if through_period is not None:
            periods = [p for p in periods if p.ordinal <= through_period]

        teams = {t.id: t for t in self.league_seasons.teams(league_season_id)}

        period_ids = [p.id for p in periods]
        matchups = self.matchups.live_for_season(
            league_season_id, period_ids=period_ids
        )
        by_matchup = _group_by_matchup(
            self.matchups.category_results_for([m.id for m in matchups])
        )

        domain_results: list[MatchupResult] = []
        for m in matchups:
            if m.away_team_season_id is None:
                # A bye — the home side did not play; neither side accrues.
                domain_results.append(
                    MatchupResult(str(m.home_team_season_id), None, 0, 0, 0)
                )
                continue
            category_rows = by_matchup.get(m.id, [])
            # ``result`` is the HOME side's perspective: 'home' is a home win,
            # 'away' an away win, 'tie' a tie. ``None`` is an undetermined
            # outcome (a missing/NaN value) — never a tie (charter §10).
            home_wins = sum(1 for r in category_rows if r.result == "home")
            away_wins = sum(1 for r in category_rows if r.result == "away")
            ties = sum(1 for r in category_rows if r.result == "tie")
            unknowns = sum(1 for r in category_rows if r.result is None)
            domain_results.append(
                MatchupResult(
                    str(m.home_team_season_id),
                    str(m.away_team_season_id),
                    home_wins,
                    away_wins,
                    ties,
                    category_unknowns=unknowns,
                )
            )

        rows: list[StandingTeamRow] = []
        for row in standings_through(domain_results):
            team = teams.get(uuid.UUID(row.team_id))
            if team is None:
                raise StandingsReadError(
                    f"standings referenced an unknown team: {row.team_id!r}"
                )
            rows.append(
                StandingTeamRow(
                    rank=row.rank,
                    team_id=team.id,
                    team_name=team.name,
                    team_abbreviation=team.abbreviation,
                    wins=row.wins,
                    losses=row.losses,
                    ties=row.ties,
                    win_pct=row.win_pct,
                    played=row.played,
                    unknown=row.unknown,
                )
            )

        as_of = max((p.end_date for p in periods), default=None)
        unknown_category_count = sum(dr.category_unknowns for dr in domain_results)
        return StandingsResult(
            rows=tuple(rows),
            as_of=as_of,
            freshness="final",
            stale=False,
            complete=unknown_category_count == 0,
            unknown_category_count=unknown_category_count,
        )
