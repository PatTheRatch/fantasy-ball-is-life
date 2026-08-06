"""
FCP Projections M-1 — NBA data ingest.

Fetches historical player stats + bios from nba_api and upserts into Supabase.
Rate-limited, resumable, idempotent. Name-resolution via the existing ESPN
normalize_name + fuzzy_match pipeline.

Per season, two nba_api calls are made: LeagueDashPlayerStats with the Base
measure type (counting stats) and again with Advanced (USG%, pace, ORtg —
these columns only exist on the Advanced endpoint). The frames are merged on
PLAYER_ID before upsert. Stats are stored as per-game averages; ``minutes``
is the derived season total (mpg × gp).

Bios (DOB, height, weight, draft, position) come from CommonPlayerInfo — one
call per player, so the bio pass only fetches players without a stored bio.
Re-running a backfill skips past seasons that are already stored; the current
season is always refreshed.

Entry points:
  - backfill_player_seasons(seasons)  — full historical backfill
  - upkeep()                          — refresh current season only
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from backend.league.data_feed import fuzzy_map_names, normalize_name
from backend.recaps.store import RecapStore, RecapStoreError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiting & retry constants
# ---------------------------------------------------------------------------

_CALL_GAP = 0.75          # seconds between nba_api calls (respect NBA.com)
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0       # multiplicative backoff: 2s, 4s, 8s

# Columns that only exist on the Advanced measure type.
_ADVANCED_COLUMNS = ("USG_PCT", "PACE", "OFF_RATING")

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class IngestReport:
    """Returned by every ingest run — never silently drop players."""

    seasons_processed: list[int]
    rows_written: int = 0
    players_seen: int = 0
    bios_written: int = 0
    seasons_skipped: list[int] = field(default_factory=list)
    unmatched_names: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def matched_count(self) -> int:
        """Player-season rows whose name matched an ESPN roster name."""
        return max(self.players_seen - len(self.unmatched_names), 0)

    def __repr__(self) -> str:
        return (
            f"IngestReport(seasons={self.seasons_processed}, "
            f"skipped={self.seasons_skipped}, "
            f"rows={self.rows_written}, bios={self.bios_written}, "
            f"matched={self.matched_count}, "
            f"unmatched={len(self.unmatched_names)}, errors={len(self.errors)})"
        )


def backfill_player_seasons(
    seasons: list[int],
    *,
    supabase_url: str | None = None,
    supabase_key: str | None = None,
    espn_player_names: list[str] | None = None,
    skip_existing: bool = True,
    include_bios: bool = True,
) -> IngestReport:
    """Fetch and upsert player-season data for the given seasons.

    Idempotent — re-running the same season upserts on ``(person_id,
    season)``.  Resumable — past seasons with stored rows are skipped
    (``skip_existing=False`` forces a refetch); the current season is
    always refetched so in-progress stats stay fresh.

    Rate-limited: ~0.75s between nba_api calls + retry with backoff.

    Args:
        seasons: List of season years (e.g. [2018, 2019, …, 2025]).
        supabase_url: Supabase REST URL. When None, no DB writes happen and
                      ``rows_written`` counts rows built (dry run).
        supabase_key: Service-role key (optional).
        espn_player_names: ESPN roster names for fuzzy name resolution.
                           When None, the name column is still normalised but
                           no ESPN match is attempted.
        skip_existing: Skip past seasons that already have stored rows.
        include_bios: After the season pass, fetch bios for any player
                      without a stored ``nba_player_bio`` row.

    Returns:
        IngestReport with row counts and unmatched names.
    """
    report = IngestReport(seasons_processed=[])

    store: RecapStore | None = None
    if supabase_url and supabase_key:
        store = RecapStore(url=supabase_url, service_role_key=supabase_key)

    current_season = _current_season()
    # person_id → display_name for every player seen this run (bio pass input)
    persons_seen: dict[int, str] = {}

    for season in sorted(seasons):
        if (
            store is not None
            and skip_existing
            and season < current_season
            and _season_already_stored(store, season)
        ):
            logger.info("Season %s already stored — skipping", season)
            report.seasons_skipped.append(season)
            continue

        logger.info("Ingesting season %s …", season)
        try:
            rows, written, unmatched, season_errors = _ingest_season(
                season,
                store=store,
                espn_player_names=espn_player_names,
            )
            report.seasons_processed.append(season)
            report.rows_written += written
            report.players_seen += len(rows)
            report.unmatched_names.extend(unmatched)
            report.errors.extend(season_errors)
            for row in rows:
                persons_seen[row["person_id"]] = row["display_name"]
        except Exception as exc:
            msg = f"Season {season} failed: {exc}"
            logger.error(msg)
            report.errors.append(msg)
            # Failure isolation: one broken season does not abort the rest.
            continue

    if store is not None and include_bios and persons_seen:
        _ingest_bios(persons_seen, store, report)

    return report


def upkeep(
    *,
    supabase_url: str | None = None,
    supabase_key: str | None = None,
    espn_player_names: list[str] | None = None,
) -> IngestReport:
    """Refresh the current NBA season only.

    Convenience wrapper around ``backfill_player_seasons`` for nightly cron.
    """
    return backfill_player_seasons(
        [_current_season()],
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        espn_player_names=espn_player_names,
    )


# ---------------------------------------------------------------------------
# Internal: season ingest
# ---------------------------------------------------------------------------


def _current_season() -> int:
    """Season year of the NBA season in progress (or most recently ended).

    NBA seasons span two calendar years; the "season year" is the year the
    season *started*.  E.g. the 2025-26 season started in Oct 2025, so
    ``season = 2025`` for any date after 2025-10-01.
    """
    from datetime import date as _date

    today = _date.today()
    return today.year if today.month >= 10 else today.year - 1


def _season_already_stored(store: RecapStore, season: int) -> bool:
    """True if the season has stored rows. Errors count as "not stored" so a
    flaky check re-ingests (idempotent) rather than silently skipping."""
    try:
        return store.has_nba_player_season(season)
    except RecapStoreError as exc:
        logger.warning("Skip-check for season %s failed: %s", season, exc)
        return False


def _ingest_season(
    season: int,
    *,
    store: RecapStore | None,
    espn_player_names: list[str] | None,
) -> tuple[list[dict], int, list[str], list[str]]:
    """Fetch, transform, and upsert one season's data.

    Returns:
        (rows_built, rows_written, unmatched_names, errors)
    """
    rows: list[dict] = []
    unmatched: list[str] = []
    errors: list[str] = []

    # 1. Fetch all players for the season (Base + Advanced, merged)
    season_stats_df = _fetch_season_stats(season)

    if season_stats_df.empty:
        logger.warning("No players returned for season %s", season)
        return rows, 0, unmatched, errors

    season_stats_df = _merge_advanced_stats(season_stats_df, season, errors)

    # 2. Normalize names
    season_stats_df["normalized_name"] = season_stats_df["PLAYER_NAME"].apply(
        lambda n: normalize_name(n) if pd.notna(n) else ""
    )

    # 3. Name resolution against ESPN rosters (if provided)
    if espn_player_names:
        source_names = sorted(
            n for n in season_stats_df["normalized_name"].unique() if n
        )
        name_map = _build_name_map(source_names, espn_player_names)
        matched = set(
            name_map.loc[
                name_map["proj_name_clean_fuzzy"].notna(), "player_clean"
            ]
        )
        unmatched = sorted(set(source_names) - matched)
        if unmatched:
            logger.warning(
                "Season %s: %d unmatched names (first 5: %s)",
                season, len(unmatched), unmatched[:5],
            )

    # 4. Build rows for upsert
    for _, player_row in season_stats_df.iterrows():
        rows.append(_row_for_upsert(player_row, season))

    # 5. Upsert into Supabase (if configured). Dry runs report rows built.
    written = len(rows)
    if store is not None:
        written = _upsert_player_seasons(rows, store, report_errors=errors)

    return rows, written, unmatched, errors


def _ingest_bios(
    persons_seen: dict[int, str],
    store: RecapStore,
    report: IngestReport,
) -> None:
    """Fetch + upsert bios for players without a stored bio row.

    One CommonPlayerInfo call per missing player, so this is the slow pass —
    already-stored bios are never refetched, making re-runs cheap. A failed
    fetch is reported and skipped; the next run picks it up again.
    """
    try:
        stored_ids = store.list_nba_bio_person_ids()
    except RecapStoreError as exc:
        msg = f"Bio pass skipped: could not list stored bios: {exc}"
        logger.error(msg)
        report.errors.append(msg)
        return

    missing = [pid for pid in sorted(persons_seen) if pid not in stored_ids]
    if not missing:
        logger.info("Bio pass: all %d players already stored", len(persons_seen))
        return

    logger.info(
        "Bio pass: fetching %d of %d players", len(missing), len(persons_seen)
    )
    bio_rows: list[dict] = []
    for person_id in missing:
        bio = _fetch_bio(person_id)
        if not bio:
            report.errors.append(
                f"Bio fetch failed for person_id={person_id} "
                f"({persons_seen[person_id]})"
            )
            continue
        bio["normalized_name"] = normalize_name(bio.get("display_name", ""))
        bio_rows.append(bio)

    if bio_rows:
        report.bios_written += _upsert_player_bios(
            bio_rows, store, report_errors=report.errors
        )


# ---------------------------------------------------------------------------
# Internal: nba_api wrappers with rate-limiting
# ---------------------------------------------------------------------------


def _fetch_season_stats(season: int) -> pd.DataFrame:
    """Fetch per-game player stats for a full NBA season via nba_api.

    Uses ``LeagueDashPlayerStats`` (Base measure type) — one row per player
    with per-game averages.  Respects rate limits.
    """
    from nba_api.stats.endpoints import leaguedashplayerstats

    season_str = _nba_season_string(season)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = leaguedashplayerstats.LeagueDashPlayerStats(
                season=season_str,
                season_type_all_star="Regular Season",
                per_mode_detailed="PerGame",
                measure_type_detailed_defense="Base",
            )
            df = resp.get_data_frames()[0]
            _sleep_between_calls()
            return df
        except Exception as exc:
            logger.warning(
                "LeagueDashPlayerStats season=%s attempt %d/%d failed: %s",
                season, attempt, _MAX_RETRIES, exc,
            )
            if attempt < _MAX_RETRIES:
                _sleep_with_backoff(attempt)
            else:
                raise


def _fetch_advanced_stats(season: int) -> pd.DataFrame:
    """Fetch advanced stats (USG%, pace, ORtg) for a season.

    These columns are only present on the Advanced measure type — the Base
    frame does not carry them.
    """
    from nba_api.stats.endpoints import leaguedashplayerstats

    season_str = _nba_season_string(season)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = leaguedashplayerstats.LeagueDashPlayerStats(
                season=season_str,
                season_type_all_star="Regular Season",
                per_mode_detailed="PerGame",
                measure_type_detailed_defense="Advanced",
            )
            df = resp.get_data_frames()[0]
            _sleep_between_calls()
            return df
        except Exception as exc:
            logger.warning(
                "LeagueDashPlayerStats (Advanced) season=%s attempt %d/%d failed: %s",
                season, attempt, _MAX_RETRIES, exc,
            )
            if attempt < _MAX_RETRIES:
                _sleep_with_backoff(attempt)
            else:
                raise


def _merge_advanced_stats(
    base_df: pd.DataFrame, season: int, errors: list[str]
) -> pd.DataFrame:
    """Left-join USG%/pace/ORtg from the Advanced frame onto the Base frame.

    Failure-tolerant: if the Advanced fetch fails, the season still ingests
    with those columns null and the failure lands in the report.
    """
    try:
        adv_df = _fetch_advanced_stats(season)
    except Exception as exc:
        msg = f"Season {season}: advanced stats fetch failed: {exc}"
        logger.warning(msg)
        errors.append(msg)
        return base_df

    if adv_df is None or adv_df.empty or "PLAYER_ID" not in adv_df.columns:
        return base_df

    adv_cols = [c for c in _ADVANCED_COLUMNS if c in adv_df.columns]
    if not adv_cols:
        return base_df

    base = base_df.drop(
        columns=[c for c in _ADVANCED_COLUMNS if c in base_df.columns]
    )
    return base.merge(
        adv_df[["PLAYER_ID", *adv_cols]].drop_duplicates("PLAYER_ID"),
        on="PLAYER_ID",
        how="left",
    )


def _fetch_bio(person_id: int) -> dict[str, Any]:
    """Fetch player bio (height, weight, DOB, draft, position) via nba_api.

    Retries with backoff on transient failures; returns {} on give-up so the
    caller can report + skip.
    """
    from nba_api.stats.endpoints import commonplayerinfo

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = commonplayerinfo.CommonPlayerInfo(player_id=person_id)
            df = resp.get_data_frames()[0]
            _sleep_between_calls()
            if df.empty:
                return {}
            row = df.iloc[0].to_dict()
            dob = _parse_date_str(row.get("BIRTHDATE"))
            return {
                "person_id": person_id,
                "display_name": row.get("DISPLAY_FIRST_LAST", ""),
                "dob": dob.isoformat() if dob else None,
                "height": row.get("HEIGHT"),
                "weight": _safe_int(row.get("WEIGHT")),
                "position": row.get("POSITION") or None,
                "draft_year": _safe_int(row.get("DRAFT_YEAR")),
                "draft_round": _safe_int(row.get("DRAFT_ROUND")),
                "draft_pick": _safe_int(row.get("DRAFT_NUMBER")),
                "experience": _safe_int(row.get("SEASON_EXP")),
            }
        except Exception as exc:
            logger.warning(
                "CommonPlayerInfo player=%s attempt %d/%d failed: %s",
                person_id, attempt, _MAX_RETRIES, exc,
            )
            if attempt < _MAX_RETRIES:
                _sleep_with_backoff(attempt)
            else:
                logger.error("Giving up on player %s after %d retries", person_id, _MAX_RETRIES)
                return {}


# ---------------------------------------------------------------------------
# Internal: helpers
# ---------------------------------------------------------------------------


def _nba_season_string(season: int) -> str:
    """Convert a season year (e.g. 2025) to NBA API format ('2025-26')."""
    return f"{season}-{str(season + 1)[-2:]}"


def _row_for_upsert(player_row: pd.Series, season: int) -> dict:
    """Build a dict ready for Supabase upsert from a merged Base+Advanced row.

    Stats are per-game averages (PerMode=PerGame); ``minutes`` is the derived
    season total. USG%/pace/ORtg are null unless the Advanced merge supplied
    them — the Base frame does not carry those columns.
    """
    mpg = _safe_float(player_row.get("MIN"))
    gp = _safe_int(player_row.get("GP"))
    return {
        "person_id": int(player_row["PLAYER_ID"]),
        "normalized_name": normalize_name(str(player_row.get("PLAYER_NAME", ""))),
        "display_name": str(player_row.get("PLAYER_NAME", "")),
        "season": season,
        "age": _safe_float(player_row.get("AGE")),
        "team": str(player_row.get("TEAM_ABBREVIATION", "")),
        # availability
        "gp": gp,
        "gs": _safe_int(player_row.get("GS")),
        "minutes": round(mpg * gp, 1) if mpg is not None and gp is not None else None,
        "mpg": mpg,
        # volume — makes AND attempts
        "fgm": _safe_float(player_row.get("FGM")),
        "fga": _safe_float(player_row.get("FGA")),
        "ftm": _safe_float(player_row.get("FTM")),
        "fta": _safe_float(player_row.get("FTA")),
        "tpm": _safe_float(player_row.get("FG3M")),
        "tpa": _safe_float(player_row.get("FG3A")),
        "tov": _safe_float(player_row.get("TOV")),
        "usg_pct": _safe_float(player_row.get("USG_PCT")),
        # production
        "pts": _safe_float(player_row.get("PTS")),
        "reb": _safe_float(player_row.get("REB")),
        "ast": _safe_float(player_row.get("AST")),
        "stl": _safe_float(player_row.get("STL")),
        "blk": _safe_float(player_row.get("BLK")),
        # context (Advanced measure type only)
        "team_pace": _safe_float(player_row.get("PACE")),
        "team_ortg": _safe_float(player_row.get("OFF_RATING")),
    }


def _build_name_map(
    source_names: list[str],
    espn_names: list[str],
    score_cutoff: int = 85,
) -> pd.DataFrame:
    """Map normalized NBA names to ESPN roster names via fuzzy matching.

    ESPN names are normalized here too — fuzzy_map_names compares raw
    strings, so an un-normalized target side would tank every score.
    """
    espn_normalized = [normalize_name(str(n)) for n in espn_names]
    return fuzzy_map_names(
        pd.Series(list(source_names)),
        pd.Series(espn_normalized),
        score_cutoff=score_cutoff,
    )


def _upsert_player_seasons(
    rows: list[dict],
    store: RecapStore,
    report_errors: list[str] | None = None,
) -> int:
    """Upsert season rows with retry/backoff. Returns rows actually written
    (0 on final failure — never count rows we didn't store)."""
    return _upsert_with_retry(
        rows, store.upsert_nba_player_seasons, "nba_player_seasons", report_errors
    )


def _upsert_player_bios(
    rows: list[dict],
    store: RecapStore,
    report_errors: list[str] | None = None,
) -> int:
    """Upsert bio rows with retry/backoff. Returns rows actually written."""
    return _upsert_with_retry(
        rows, store.upsert_nba_player_bios, "nba_player_bio", report_errors
    )


def _upsert_with_retry(
    rows: list[dict],
    upsert_fn: Any,
    label: str,
    report_errors: list[str] | None,
) -> int:
    if not rows:
        return 0

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            upsert_fn(rows)
            _sleep_between_calls()
            return len(rows)
        except RecapStoreError as exc:
            msg = f"{label} upsert attempt {attempt}/{_MAX_RETRIES} failed: {exc}"
            logger.warning(msg)
            if attempt < _MAX_RETRIES:
                _sleep_with_backoff(attempt)
            else:
                if report_errors is not None:
                    report_errors.append(msg)
                    return 0
                raise
    return 0


# ---------------------------------------------------------------------------
# Rate-limiting helpers
# ---------------------------------------------------------------------------


def _sleep_between_calls() -> None:
    """Sleep to respect NBA.com rate limits."""
    time.sleep(_CALL_GAP)


def _sleep_with_backoff(attempt: int) -> None:
    """Exponential backoff before retry."""
    delay = _BACKOFF_BASE ** attempt
    logger.debug("Backing off for %.1fs (attempt %d)", delay, attempt)
    time.sleep(delay)


def _safe_float(value: Any) -> float | None:
    """Convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        v = float(value)
        return v if pd.notna(v) else None
    except (ValueError, TypeError):
        return None


def _safe_int(value: Any) -> int | None:
    """Convert a value to int, returning None on failure."""
    if value is None:
        return None
    try:
        v = int(float(value))
        return v if pd.notna(v) else None
    except (ValueError, TypeError):
        return None


def _parse_date_str(value: Any) -> date | None:
    """Parse a date string to date, returning None on failure."""
    if value is None:
        return None
    try:
        from datetime import datetime
        s = str(value).strip()
        # NBA API returns dates like "1984-12-30T00:00:00"
        if "T" in s:
            return datetime.fromisoformat(s).date()
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
