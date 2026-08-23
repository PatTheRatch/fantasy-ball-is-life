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
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

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
    LeagueSeason,
    Matchup,
    MatchupCategoryResult,
    MatchupPeriod,
)
from backend.models.ingestion import IngestionRun
from backend.repos.matchups import LeagueSeasonRepository, MatchupRepository
from backend.services.ingestion import (
    NORMALIZER_VERSION,
    RUN_PARTIAL,
    RUN_SUCCEEDED,
    IngestionService,
)

#: domain ``Result`` → FCP ``matchup_result``, from the home side's perspective.
#: ``None`` is an unknown outcome (a missing/NaN value) — the storage column is
#: nullable, so an unknown is never collapsed into ``tie``. Total over ``Result``
#: so a future member cannot be silently dropped.
_RESULT_MAP: dict[Result, str | None] = {
    Result.WIN: "home",
    Result.LOSS: "away",
    Result.TIE: "tie",
    Result.UNKNOWN: None,
}


@dataclass(frozen=True, slots=True)
class SyncSummary:
    """What one sync did."""

    periods: int
    matchups: int
    created: int
    superseded: int
    unchanged: int
    unknown_categories: int


@dataclass(frozen=True, slots=True)
class _PeriodSync:
    """What syncing one period did — the shared fetch-normalize-persist result."""

    matchups: int
    created: int
    superseded: int
    unchanged: int
    unknowns: int


@dataclass(frozen=True, slots=True)
class FinalizeSummary:
    """What one finalize pass did."""

    finalized: int
    skipped_final: int
    skipped_ineligible: int
    skipped_no_provider_id: int
    unknowns: int


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


def _resolved_stats(
    cats: list[DomainCategory], stats: Mapping[str, float | None]
) -> dict[str, float | None]:
    """Return ``stats`` with each category's value derived and rounded to storage
    precision, stored under its key.

    ``compare`` (per-category result) and ``tally`` (computed_result) must see
    *identical* values or the category rows can stop summing to the matchup
    result at a 3-decimal boundary. Resolving once here — and rounding to the
    ``Numeric(10,3)``/``Numeric(10,2)`` column precision — keeps both consistent
    and makes the stored value equal the in-memory value on resync.
    """
    resolved = dict(stats)
    for cat in cats:
        if cat.kind is CategoryKind.RATIO:
            resolved[cat.key] = _round3(ratio_value(cat, stats))
        else:
            resolved[cat.key] = _round3(stats.get(cat.key))
    return resolved


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


def _period_eligible(
    period: MatchupPeriod, now: datetime, tz: ZoneInfo, grace_hours: int
) -> bool:
    """True when the period's end date has passed by the grace margin, in the
    league's timezone.

    ``end_date`` is a calendar date; the period is over at midnight *after* it
    (its final day of games is still in progress during ``end_date`` itself).
    Comparing in UTC or server-local would mis-finalize by up to a day at the
    boundary — a whole week's standings. ``now`` must be timezone-aware.
    """
    if period.end_date is None:
        return False
    end_of_day = datetime.combine(period.end_date, time.min, tzinfo=tz) + timedelta(days=1)
    return now >= end_of_day + timedelta(hours=grace_hours)


class MatchupSyncService:
    """Finalizes and re-syncs one league_season's periods into matchups.

    ``finalize_eligible_periods`` is the only code path that writes
    ``status='final'``; ``resync_final_periods`` is the repair path that
    re-reads already-final periods and never touches status. Both share
    ``_sync_period``, the single implementation of fetch-normalize-persist.
    """

    def __init__(
        self,
        ingestion: IngestionService,
        league_seasons: LeagueSeasonRepository,
        matchups: MatchupRepository,
    ) -> None:
        self.ingestion = ingestion
        self.league_seasons = league_seasons
        self.matchups = matchups

    def _season_context(
        self,
    ) -> tuple[
        LeagueSeason,
        list[DomainCategory],
        dict[str, uuid.UUID],
        dict[str, FantasyTeamSeason],
    ]:
        """Load the scoped season's sync context (season, categories, teams)."""
        season = self.league_seasons.get()
        if season is None:
            raise MatchupSyncError(
                f"unknown league_season: {self.league_seasons.scope.league_season_id!r}"
            )
        model_cats = self.league_seasons.scoring_categories()
        domain_cats = [_to_domain_category(c) for c in model_cats]
        cat_id_by_key = {c.key: c.id for c in model_cats}
        teams_by_provider = self.league_seasons.teams_by_provider()
        return season, domain_cats, cat_id_by_key, teams_by_provider

    def _sync_period(
        self,
        period: MatchupPeriod,
        season: LeagueSeason,
        domain_cats: list[DomainCategory],
        cat_id_by_key: dict[str, uuid.UUID],
        teams_by_provider: dict[str, FantasyTeamSeason],
        run: IngestionRun,
        connection: object,
        adapter: ScoreboardAdapter,
    ) -> _PeriodSync:
        """Fetch + persist one period's matchups — the single implementation of
        the thing that writes matchups, shared by finalize and resync."""
        if period.provider_period_id is None:
            return _PeriodSync(0, 0, 0, 0, 0)
        sb = adapter.fetch_scoreboard(
            connection, season.season_year, period.provider_period_id
        )
        self.ingestion.record_payload(
            run, f"scoreboard/{period.provider_period_id}", asdict(sb)
        )
        matchups = created = superseded = unchanged = unknowns = 0
        for m in sb.matchups:
            outcome, unknown_count = self._persist_matchup(
                m, period, season.id, domain_cats, cat_id_by_key, teams_by_provider, run
            )
            matchups += 1
            unknowns += unknown_count
            if outcome == "created":
                created += 1
            elif outcome == "superseded":
                superseded += 1
            else:
                unchanged += 1
        return _PeriodSync(matchups, created, superseded, unchanged, unknowns)

    def resync_final_periods(
        self, *, connection: object, adapter: ScoreboardAdapter
    ) -> SyncSummary:
        """Repair path: re-read already-``final`` periods after a normalizer change.

        This must **not** change any period's ``status`` — finality is owned by
        :meth:`finalize_period` alone. It re-fetches and supersedes the matchups
        of periods already marked final; a normalizer bump is fixed by re-running
        this over the stored payloads, never by touching finality.
        """
        season, domain_cats, cat_id_by_key, teams_by_provider = self._season_context()
        periods = matchups = created = superseded = unchanged = unknowns = 0
        with self.ingestion.run_scope(
            season.provider_key, kind="matchups", league_season_id=season.id
        ) as run:
            for period in self.league_seasons.final_periods():
                sync = self._sync_period(
                    period, season, domain_cats, cat_id_by_key, teams_by_provider,
                    run, connection, adapter,
                )
                matchups += sync.matchups
                created += sync.created
                superseded += sync.superseded
                unchanged += sync.unchanged
                unknowns += sync.unknowns
                periods += 1
            summary = SyncSummary(
                periods, matchups, created, superseded, unchanged, unknowns
            )
            status = RUN_PARTIAL if unknowns else RUN_SUCCEEDED
            self.ingestion.finish_run(run, status, stats=asdict(summary))
        return summary

    def finalize_period(
        self,
        period: MatchupPeriod,
        *,
        connection: object,
        adapter: ScoreboardAdapter,
        run: IngestionRun,
    ) -> int:
        """Finalize one already-eligible period within an open run.

        Fetch + persist + flip ``status``/``finalized_at`` together (H-05a's
        constraint makes them inseparable), then **commit** — commit per period,
        not per run, so a failure later in the run leaves this period durable and
        a re-run resumes where it stopped. Returns the unknown-category count.

        Recomputes the season context rather than taking it as a parameter, so
        this stays callable standalone; the extra reload per period is fine for a
        ~20-period backfill.
        """
        season, domain_cats, cat_id_by_key, teams_by_provider = self._season_context()
        sync = self._sync_period(
            period, season, domain_cats, cat_id_by_key, teams_by_provider,
            run, connection, adapter,
        )
        period.status = "final"
        period.finalized_at = datetime.now(UTC)
        self.matchups.commit()
        return sync.unknowns

    def finalize_eligible_periods(
        self,
        *,
        connection: object,
        adapter: ScoreboardAdapter,
        grace_hours: int = 48,
        now: datetime | None = None,
    ) -> FinalizeSummary:
        """Finalize every eligible period of the scoped season, in ordinal order.

        A period is eligible when it is not already ``final``, has a
        ``provider_period_id``, and its ``end_date`` has passed by ``grace_hours``
        in the league's timezone. ``now`` is injectable for the boundary tests.
        """
        season, _, _, _ = self._season_context()
        now = now or datetime.now(UTC)
        tz = ZoneInfo(season.timezone)
        finalized = skipped_final = skipped_ineligible = skipped_no_id = 0
        unknowns = 0
        with self.ingestion.run_scope(
            season.provider_key, kind="finalize", league_season_id=season.id
        ) as run:
            for period in self.league_seasons.periods():
                if period.status == "final":
                    skipped_final += 1
                    continue
                if period.provider_period_id is None:
                    skipped_no_id += 1
                    continue
                if not _period_eligible(period, now, tz, grace_hours):
                    skipped_ineligible += 1
                    continue
                unknowns += self.finalize_period(
                    period, connection=connection, adapter=adapter, run=run
                )
                finalized += 1
            summary = FinalizeSummary(
                finalized, skipped_final, skipped_ineligible, skipped_no_id, unknowns
            )
            status = RUN_PARTIAL if unknowns else RUN_SUCCEEDED
            self.ingestion.finish_run(run, status, stats=asdict(summary))
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
    ) -> tuple[str, int]:
        """Persist one matchup; return ``(outcome, unknown_category_count)``.

        ``outcome`` is ``created | superseded | unchanged``. ``unknown_category_count``
        is the number of category outcomes that resolved to ``NULL`` (missing/NaN
        values, charter §10) — reported on every path so an identical resync of
        already-partial data is still reported partial.
        """
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
        unknown_count = sum(1 for r in results if r.result is None)

        existing = self.matchups.find_live(period.id, home.id)
        if existing is None:
            self.matchups.add(matchup)
            for r in results:
                self.matchups.add_category_result(r)
            return "created", unknown_count

        if _matchup_signature(existing, self.matchups.category_results(existing.id)) == (
            _matchup_signature(matchup, results)
        ):
            return "unchanged", unknown_count

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
        return "superseded", unknown_count

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

        home_resolved = _resolved_stats(domain_cats, home_stats)
        away_resolved = _resolved_stats(domain_cats, away_stats)
        home_wins, away_wins, _, _ = tally(domain_cats, home_resolved, away_resolved)
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
                home_num = _round2(home_resolved.get(cat.numerator))
                home_den = _round2(home_resolved.get(cat.denominator))
                away_num = _round2(away_resolved.get(cat.numerator))
                away_den = _round2(away_resolved.get(cat.denominator))
            else:
                home_num = home_den = away_num = away_den = None

            home_value = home_resolved.get(cat.key)
            away_value = away_resolved.get(cat.key)
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
