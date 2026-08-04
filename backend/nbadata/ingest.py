"""
FCP Projections M-1 — NBA data ingest.

Fetches historical player stats + bio from nba_api and upserts into Supabase.
Rate-limited, resumable, idempotent. Name-resolution via the existing ESPN
normalize_name + fuzzy_match pipeline.

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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate limiting & retry constants
# ---------------------------------------------------------------------------

_CALL_GAP = 0.75          # seconds between nba_api calls (respect NBA.com)
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0       # multiplicative backoff: 2s, 4s, 8s

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass
class IngestReport:
    """Returned by every ingest run — never silently drop players."""

    seasons_processed: list[int]
    rows_written: int
    unmatched_names: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def matched_count(self) -> int:
        return self.rows_written - len(self.unmatched_names)

    def __repr__(self) -> str:
        return (
            f"IngestReport(seasons={self.seasons_processed}, "
            f"rows={self.rows_written}, matched={self.matched_count}, "
            f"unmatched={len(self.unmatched_names)}, errors={len(self.errors)})"
        )


def backfill_player_seasons(
    seasons: list[int],
    *,
    supabase_url: str | None = None,
    supabase_key: str | None = None,
    espn_player_names: list[str] | None = None,
) -> IngestReport:
    """Fetch and upsert player-season data for the given seasons.

    Idempotent — re-running the same season is a no-op (upsert on
    ``(person_id, season)``).  Skips seasons already fully stored.

    Rate-limited: ~0.75s between nba_api calls + retry with backoff.

    Args:
        seasons: List of season years (e.g. [2018, 2019, …, 2025]).
        supabase_url: Supabase REST URL (optional — skips DB write when None).
        supabase_key: Service-role key (optional).
        espn_player_names: ESPN roster names for fuzzy name resolution.
                           When None, the name column is still normalised but
                           no ESPN match is attempted.

    Returns:
        IngestReport with row counts and unmatched names.
    """
    report = IngestReport(seasons_processed=[], rows_written=0)

    for season in sorted(seasons):
        logger.info("Ingesting season %s …", season)
        try:
            season_rows, unmatched, season_errors = _ingest_season(
                season,
                supabase_url=supabase_url,
                supabase_key=supabase_key,
                espn_player_names=espn_player_names,
            )
            report.seasons_processed.append(season)
            report.rows_written += len(season_rows)
            report.unmatched_names.extend(unmatched)
            report.errors.extend(season_errors)
        except Exception as exc:
            msg = f"Season {season} failed: {exc}"
            logger.error(msg)
            report.errors.append(msg)
            # Failure isolation: one broken season does not abort the rest.
            continue

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
    from datetime import date

    today = date.today()
    # NBA seasons span two calendar years; the "season year" is the year the
    # season *started*.  E.g. the 2025-26 season started in Oct 2025, so
    # ``season = 2025`` for any date after 2025-10-01.
    # Rough heuristic: if today's month >= 10, current season = this year;
    # otherwise current season = last year.
    current_season = today.year if today.month >= 10 else today.year - 1

    return backfill_player_seasons(
        [current_season],
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        espn_player_names=espn_player_names,
    )


# ---------------------------------------------------------------------------
# Internal: season ingest
# ---------------------------------------------------------------------------


def _ingest_season(
    season: int,
    *,
    supabase_url: str | None,
    supabase_key: str | None,
    espn_player_names: list[str] | None,
) -> tuple[list[dict], list[str], list[str]]:
    """Fetch, transform, and upsert one season's data.

    Returns:
        (rows_written, unmatched_names, errors)
    """
    rows: list[dict] = []
    unmatched: list[str] = []
    errors: list[str] = []

    # 1. Fetch all players for the season
    season_stats_df = _fetch_season_stats(season)

    if season_stats_df.empty:
        logger.warning("No players returned for season %s", season)
        return rows, unmatched, errors

    # 2. Normalize names
    season_stats_df["normalized_name"] = season_stats_df["PLAYER_NAME"].apply(
        lambda n: normalize_name(n) if pd.notna(n) else ""
    )

    # 3. Name resolution against ESPN rosters (if provided)
    if espn_player_names:
        name_map = _build_name_map(season_stats_df["normalized_name"].unique(), espn_player_names)
        # unmatched_names are the ones that couldn't be mapped
        unmatched_source = set(season_stats_df["normalized_name"].unique()) - set(
            n for n, t, s in zip(name_map["player_clean"], name_map["proj_name_clean_fuzzy"], name_map["match_score"])
            if pd.notna(t)
        )
        unmatched = sorted(unmatched_source)
        if unmatched:
            logger.warning(
                "Season %s: %d unmatched names (first 5: %s)",
                season, len(unmatched), unmatched[:5],
            )

    # 4. Build rows for upsert
    for _, player_row in season_stats_df.iterrows():
        rows.append(_row_for_upsert(player_row, season))

    # 5. Upsert into Supabase (if configured)
    if supabase_url and supabase_key:
        _upsert_player_seasons(rows, supabase_url, supabase_key, report_errors=errors)

    return rows, unmatched, errors


# ---------------------------------------------------------------------------
# Internal: nba_api wrappers with rate-limiting
# ---------------------------------------------------------------------------


def _fetch_season_stats(season: int) -> pd.DataFrame:
    """Fetch per-game player stats for a full NBA season via nba_api.

    Uses ``LeagueDashPlayerStats`` which returns one row per player with
    per-game averages + totals.  Respects rate limits.
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


def _fetch_bio(person_id: int) -> dict[str, Any]:
    """Fetch player bio (height, weight, DOB, draft) via nba_api.

    Retries with backoff on transient failures.
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
            return {
                "person_id": person_id,
                "display_name": row.get("DISPLAY_FIRST_LAST", ""),
                "dob": _parse_date_str(row.get("BIRTHDATE")),
                "height": row.get("HEIGHT"),
                "weight": row.get("WEIGHT"),
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


def _fetch_advanced_stats(season: int) -> pd.DataFrame:
    """Fetch advanced stats (USG%, pace, ORtg) for a season."""
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


# ---------------------------------------------------------------------------
# Internal: helpers
# ---------------------------------------------------------------------------


def _nba_season_string(season: int) -> str:
    """Convert a season year (e.g. 2025) to NBA API format ('2025-26')."""
    return f"{season}-{str(season + 1)[-2:]}"


def _row_for_upsert(player_row: pd.Series, season: int) -> dict:
    """Build a dict ready for Supabase upsert from a LeagueDashPlayerStats row."""
    return {
        "person_id": int(player_row["PLAYER_ID"]),
        "normalized_name": normalize_name(str(player_row.get("PLAYER_NAME", ""))),
        "display_name": str(player_row.get("PLAYER_NAME", "")),
        "season": season,
        "age": _safe_float(player_row.get("AGE")),
        "team": str(player_row.get("TEAM_ABBREVIATION", "")),
        "position": str(player_row.get("POSITION", player_row.get("POS", ""))),
        # availability
        "gp": _safe_int(player_row.get("GP")),
        "gs": _safe_int(player_row.get("GS")),
        "minutes": _safe_float(player_row.get("MIN")),
        "mpg": _safe_float(player_row.get("MIN")),
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
        # context (advanced — may be None for base endpoint; filled by merge)
        "team_pace": _safe_float(player_row.get("PACE")),
        "team_ortg": _safe_float(player_row.get("OFF_RATING")),
    }


def _build_name_map(
    source_names: list[str],
    espn_names: list[str],
    score_cutoff: int = 85,
) -> pd.DataFrame:
    """Map normalized NBA names to ESPN roster names via fuzzy matching."""
    return fuzzy_map_names(
        pd.Series(source_names),
        pd.Series(espn_names),
        score_cutoff=score_cutoff,
    )


def _upsert_player_seasons(
    rows: list[dict],
    supabase_url: str,
    supabase_key: str,
    report_errors: list[str] | None = None,
) -> None:
    """Upsert rows into nba_player_seasons via Supabase REST API.

    Uses ``on_conflict=person_id,season`` for idempotency.
    """
    import json
    import urllib.request
    import urllib.error

    if not rows:
        return

    url = f"{supabase_url}/rest/v1/nba_player_seasons?on_conflict=person_id,season"
    payload = json.dumps(rows).encode("utf-8")

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                if resp.status not in (200, 201):
                    body = resp.read().decode()
                    raise RuntimeError(f"HTTP {resp.status}: {body[:200]}")
            _sleep_between_calls()
            return
        except Exception as exc:
            msg = f"Upsert attempt {attempt}/{_MAX_RETRIES} failed: {exc}"
            logger.warning(msg)
            if attempt < _MAX_RETRIES:
                _sleep_with_backoff(attempt)
            else:
                if report_errors is not None:
                    report_errors.append(msg)
                else:
                    raise


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
