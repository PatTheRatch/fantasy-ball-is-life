"""Matchups sync: fetch, normalise and persist one league's final periods.

The first bite that ties the stack together: the ESPN adapter (S1-07) fetches a
period's scoreboard, the run ledger (S1-08) records the raw payload, and this
service normalises it into ``matchups`` + ``matchup_category_results`` using the
season's own ``Category`` rows (D11 — never assumes nine) and the pure domain
tally (``domain.categories``).

Supersession, never mutation (README §Supersession): a resync that finds a live
row for a slot either no-ops (identical) or supersedes it. Final periods are the
only periods synced — they are never refetched, so standings through them become
a deterministic fold (S1-10b).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Protocol

from backend.domain.categories import (
    Category as DomainCategory,
)
from backend.domain.categories import (
    CategoryKind,
    Result,
    compare,
    ratio_value,
    tally,
)
from backend.domain.dto import ScoreboardDTO, ScoreboardMatchupDTO
from backend.models.base import uuid7
from backend.models.fantasy import (
    Category,
    FantasyTeamSeason,
    Matchup,
    MatchupCategoryResult,
    MatchupPeriod,
)
from backend.models.ingestion import IngestionRun
from backend.repos.matchups import LeagueSeasonRepository, MatchupRepository
from backend.services.ingestion import NORMALIZER_VERSION, IngestionService

#: domain ``Result`` → FCP ``matchup_result``, from the home side's perspective.
_RESULT_MAP: dict[Result, str] = {
    Result.WIN: "home",
    Result.LOSS: "away",
    Result.TIE: "tie",
}


@dataclass(frozen=True, slots=True)
class SyncSummary:
    """What one sync did."""

    periods: int
    matchups: int
    created: int
    superseded: int
    unchanged: int


class MatchupSyncError(Exception):
    """The sync could not run (unknown season, unresolved team)."""


class ScoreboardAdapter(Protocol):
    """The adapter seam the sync depends on (satisfied by ``ESPNAdapter``)."""

    def fetch_scoreboard(
        self, connection: object, season_year: int, provider_period_id: str
    ) -> ScoreboardDTO: ...


def _to_domain_category(c: Category) -> DomainCategory:
    """Project a DB ``Category`` row onto the pure domain ``Category``."""
    return DomainCategory(
        key=c.key,
        short_name=c.short_name,
        kind=CategoryKind(c.kind),
        higher_is_better=c.higher_is_better,
        numerator=c.numerator_stat,
        denominator=c.denominator_stat,
    )


def _round3(value: float | None) -> float | None:
    """Round a score value to the ``Numeric(10,3)`` column precision."""
    return round(value, 3) if value is not None else None


def _round2(value: float | None) -> float | None:
    """Round a ratio component to the ``Numeric(10,2)`` column precision."""
    return round(value, 2) if value is not None else None


def _matchup_signature(
    matchup: Matchup, results: list[MatchupCategoryResult]
) -> tuple[object, ...]:
    """A content fingerprint for the idempotency comparison (no ids/timestamps)."""
    m_sig = (
        matchup.away_team_season_id,
        matchup.computed_result,
        matchup.provider_result,
        matchup.result_source,
        matchup.status,
    )
    r_sig = tuple(
        sorted(
            (
                r.category_id,
                r.home_value,
                r.away_value,
                r.home_numerator,
                r.home_denominator,
                r.away_numerator,
                r.away_denominator,
                r.result,
            )
            for r in results
        )
    )
    return (m_sig, r_sig)


class MatchupSyncService:
    """Syncs one league_season's final periods into matchups + category results."""

    def __init__(
        self,
        ingestion: IngestionService,
        league_seasons: LeagueSeasonRepository,
        matchups: MatchupRepository,
    ) -> None:
        self.ingestion = ingestion
        self.league_seasons = league_seasons
        self.matchups = matchups

    def sync_league_final_periods(
        self,
        league_season_id: uuid.UUID,
        *,
        connection: object,
        adapter: ScoreboardAdapter,
    ) -> SyncSummary:
        """Fetch + persist every ``final`` period for one league_season."""
        season = self.league_seasons.get(league_season_id)
        if season is None:
            raise MatchupSyncError(f"unknown league_season: {league_season_id!r}")

        run = self.ingestion.start_run(
            season.provider_key, kind="matchups", league_season_id=league_season_id
        )

        model_cats = self.league_seasons.scoring_categories(league_season_id)
        domain_cats = [_to_domain_category(c) for c in model_cats]
        cat_id_by_key = {c.key: c.id for c in model_cats}
        teams_by_provider = self.league_seasons.teams_by_provider(league_season_id)

        periods = matchups = created = superseded = unchanged = 0
        for period in self.league_seasons.final_periods(league_season_id):
            if period.provider_period_id is None:
                continue
            sb = adapter.fetch_scoreboard(
                connection, season.season_year, period.provider_period_id
            )
            self.ingestion.record_payload(
                run, f"scoreboard/{period.provider_period_id}", asdict(sb)
            )
            for m in sb.matchups:
                outcome = self._persist_matchup(
                    m, period, league_season_id, domain_cats, cat_id_by_key,
                    teams_by_provider, run,
                )
                matchups += 1
                if outcome == "created":
                    created += 1
                elif outcome == "superseded":
                    superseded += 1
                else:
                    unchanged += 1
            periods += 1

        summary = SyncSummary(periods, matchups, created, superseded, unchanged)
        self.ingestion.finish_run(run, "succeeded", stats=asdict(summary))
        return summary

    def _persist_matchup(
        self,
        m: ScoreboardMatchupDTO,
        period: MatchupPeriod,
        league_season_id: uuid.UUID,
        domain_cats: list[DomainCategory],
        cat_id_by_key: dict[str, uuid.UUID],
        teams_by_provider: dict[str, FantasyTeamSeason],
        run: IngestionRun,
    ) -> str:
        home_pid = m.home.provider_team_id
        if home_pid is None:
            raise MatchupSyncError("scoreboard home side has no provider_team_id")
        home = teams_by_provider.get(home_pid)
        if home is None:
            raise MatchupSyncError(f"unresolved home team: {home_pid!r}")

        away: FantasyTeamSeason | None = None
        if m.away is not None:
            away_pid = m.away.provider_team_id
            if away_pid is None:
                raise MatchupSyncError("scoreboard away side has no provider_team_id")
            away = teams_by_provider.get(away_pid)
            if away is None:
                raise MatchupSyncError(f"unresolved away team: {away_pid!r}")

        matchup, results = self._normalize(
            m, period, league_season_id, home.id,
            away.id if away is not None else None,
            domain_cats, cat_id_by_key, run,
        )

        existing = self.matchups.find_live(period.id, home.id)
        if existing is None:
            self.matchups.add(matchup)
            for r in results:
                self.matchups.add_category_result(r)
            return "created"

        if _matchup_signature(existing, self.matchups.category_results(existing.id)) == (
            _matchup_signature(matchup, results)
        ):
            return "unchanged"

        # Supersession, not mutation — and the order is load-bearing. The partial
        # unique index (uq_matchups_live_slot) rejects a second live row the
        # instant it is INSERTed, so the old row must leave the live set *before*
        # the new one is flushed. Its ``superseded_at`` (no FK) is flipped first,
        # then the new row is inserted, then ``superseded_by_id`` (a self-FK) can
        # point at it. Setting ``superseded_by_id`` first would violate the FK
        # (the new row doesn't exist yet); inserting first would violate the
        # partial unique index (the old row is still live).
        existing.superseded_at = datetime.now(UTC)
        self.matchups.flush()
        self.matchups.add(matchup)
        for r in results:
            self.matchups.add_category_result(r)
        self.matchups.flush()
        existing.superseded_by_id = matchup.id
        return "superseded"

    def _normalize(
        self,
        m: ScoreboardMatchupDTO,
        period: MatchupPeriod,
        league_season_id: uuid.UUID,
        home_team_season_id: uuid.UUID,
        away_team_season_id: uuid.UUID | None,
        domain_cats: list[DomainCategory],
        cat_id_by_key: dict[str, uuid.UUID],
        run: IngestionRun,
    ) -> tuple[Matchup, list[MatchupCategoryResult]]:
        # A fresh UUIDv7 generated here (not via the column default) so the
        # category rows can reference it, and a superseding link can point at it,
        # before the row is flushed.
        matchup_id = uuid7()
        home_stats = m.home.stats
        away_stats = m.away.stats if m.away is not None else {}

        if m.away is None:
            matchup = Matchup(
                id=matchup_id,
                league_season_id=league_season_id,
                matchup_period_id=period.id,
                home_team_season_id=home_team_season_id,
                away_team_season_id=None,
                status="final",
                computed_result=None,
                provider_result=m.provider_result,
                result_source=None,
                ingestion_run_id=run.id,
                observed_at=datetime.now(UTC),
                normalizer_version=NORMALIZER_VERSION,
            )
            return matchup, []

        home_wins, away_wins, _ = tally(domain_cats, home_stats, away_stats)
        computed = (
            "home" if home_wins > away_wins else "away" if away_wins > home_wins else "tie"
        )
        result_source = "computed"
        if computed == "tie" and m.provider_result in ("home", "away"):
            result_source = "provider_tiebreak"

        matchup = Matchup(
            id=matchup_id,
            league_season_id=league_season_id,
            matchup_period_id=period.id,
            home_team_season_id=home_team_season_id,
            away_team_season_id=away_team_season_id,
            status="final",
            computed_result=computed,
            provider_result=m.provider_result,
            result_source=result_source,
            ingestion_run_id=run.id,
            observed_at=datetime.now(UTC),
            normalizer_version=NORMALIZER_VERSION,
        )

        results: list[MatchupCategoryResult] = []
        for cat in domain_cats:
            if cat.kind is CategoryKind.RATIO:
                assert cat.numerator is not None and cat.denominator is not None
                home_value = _round3(ratio_value(cat, home_stats))
                away_value = _round3(ratio_value(cat, away_stats))
                home_num = _round2(home_stats.get(cat.numerator))
                home_den = _round2(home_stats.get(cat.denominator))
                away_num = _round2(away_stats.get(cat.numerator))
                away_den = _round2(away_stats.get(cat.denominator))
            else:
                home_value = _round3(home_stats.get(cat.key))
                away_value = _round3(away_stats.get(cat.key))
                home_num = home_den = away_num = away_den = None

            home_result, _ = compare(cat, home_value, away_value)
            results.append(
                MatchupCategoryResult(
                    matchup_id=matchup_id,
                    category_id=cat_id_by_key[cat.key],
                    home_value=home_value,
                    away_value=away_value,
                    home_numerator=home_num,
                    home_denominator=home_den,
                    away_numerator=away_num,
                    away_denominator=away_den,
                    result=_RESULT_MAP[home_result],
                )
            )

        return matchup, results
