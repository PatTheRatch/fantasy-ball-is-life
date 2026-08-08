"""FCP Projections M-2 — the projection accuracy scoreboard.

Scores every stored week-horizon projection set (BBM uploads, worker ESPN
snapshots, later FCP) against the actual weekly results already stored in
``league_week_scoreboards``: per source × week × category, projected fantasy
team totals vs actual team totals — MAE, signed bias, and Spearman rank
correlation across the league's teams — plus per-source aggregates across
weeks.

This is the benchmark harness from the spec's §5 ("final boss battle"): it
is the merge gate for the FCP model (M-3's baseline comparison and M-7's
"only if it beats v1") and eventually the public "our model vs Basketball
Monster, measured" page.

Granularity note: v1 scores at the fantasy-team-week level because that is
what the stored actuals contain. Player-level MAE / rank correlation needs
per-player weekly actuals (nba_api game logs) — a follow-up once that
ingest exists. Rank correlation across ~10 fantasy teams is coarse; MAE is
the primary metric at this granularity.

Roster mapping: projected team totals need to know who was on which fantasy
roster that week. ESPN snapshot sets embed it (``roster_team``); global
uploads (BBM) don't, so they borrow the same week's ESPN snapshot roster
map. A week with no roster source is reported unscoreable, never guessed.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd

from backend.projections.adapter import PlayerProjection
from backend.projections.store import ESPN_VIRTUAL_SET_ID, ProjectionStore

logger = logging.getLogger(__name__)

# The 9-cat keys as they appear in stored week scoreboards (`stat` column).
CATEGORIES: tuple[str, ...] = (
    "PTS", "REB", "AST", "STL", "BLK", "3PM", "TO", "FG%", "FT%",
)

# Counting categories → PlayerProjection per-game field.
_COUNTING_FIELDS: dict[str, str] = {
    "PTS": "pts_pg",
    "REB": "reb_pg",
    "AST": "ast_pg",
    "STL": "stl_pg",
    "BLK": "blk_pg",
    "3PM": "tpm_pg",
    "TO": "to_pg",
}

# Games-played is scored as a bonus category when the league tracks it —
# it isolates "wrong about schedules/availability" from "wrong about rates".
GP_CATEGORY = "GP"


# ---------------------------------------------------------------------------
# Projected side
# ---------------------------------------------------------------------------


def projected_team_totals(
    rows: list[PlayerProjection],
    roster_map: Optional[dict[str, str]] = None,
) -> tuple[dict[str, dict[str, float]], int]:
    """Aggregate player projections into fantasy-team category totals.

    Team assignment comes from ``roster_map`` (player_key → fantasy team)
    when given, else each row's own ``roster_team``. Rows with neither are
    skipped and counted (never silently dropped).

    Counting stats: Σ rate × games. Percentages: derived from summed
    makes/attempts (attempt-weighted — never averaged percentages).

    Returns (totals, skipped_row_count).
    """
    totals: dict[str, dict[str, float]] = {}
    # makes/attempts accumulators per team, for FG%/FT%
    shooting: dict[str, dict[str, float]] = {}
    skipped = 0

    for r in rows:
        team = (roster_map or {}).get(r.player_key) or r.roster_team
        if not team:
            skipped += 1
            continue
        games = float(r.games or 0.0)

        acc = totals.setdefault(
            team, {cat: 0.0 for cat in _COUNTING_FIELDS} | {GP_CATEGORY: 0.0}
        )
        sh = shooting.setdefault(
            team, {"fgm": 0.0, "fga": 0.0, "ftm": 0.0, "fta": 0.0}
        )

        for cat, fld in _COUNTING_FIELDS.items():
            acc[cat] += float(getattr(r, fld) or 0.0) * games
        acc[GP_CATEGORY] += games

        fga = float(r.fga_pg or 0.0) * games
        fta = float(r.fta_pg or 0.0) * games
        if fga > 0 and r.fg_pct is not None:
            sh["fga"] += fga
            sh["fgm"] += fga * float(r.fg_pct)
        if fta > 0 and r.ft_pct is not None:
            sh["fta"] += fta
            sh["ftm"] += fta * float(r.ft_pct)

    for team, sh in shooting.items():
        if sh["fga"] > 0:
            totals[team]["FG%"] = sh["fgm"] / sh["fga"]
        if sh["fta"] > 0:
            totals[team]["FT%"] = sh["ftm"] / sh["fta"]

    return totals, skipped


def roster_map_from_rows(rows: list[PlayerProjection]) -> dict[str, str]:
    """player_key → fantasy team, from a set that embeds rosters (ESPN)."""
    return {
        r.player_key: r.roster_team
        for r in rows
        if r.player_key and r.roster_team
    }


# ---------------------------------------------------------------------------
# Actual side
# ---------------------------------------------------------------------------


def actual_team_totals(
    payload_rows: list[dict[str, Any]],
) -> dict[str, dict[str, float]]:
    """Parse a stored ``league_week_scoreboards`` payload into team totals.

    The payload is one row per matchup per stat with home/away team names
    and values; 'Bye' sides and missing values are skipped. GP rides along
    on every row (``home_games_played``/``away_games_played``) — captured
    once per team.
    """
    totals: dict[str, dict[str, float]] = {}
    for row in payload_rows or []:
        stat = str(row.get("stat") or "").upper()
        for side in ("home", "away"):
            team = row.get(f"{side}_team")
            if not team or team == "Bye":
                continue
            entry = totals.setdefault(str(team), {})
            value = row.get(f"current_{side}_score")
            if stat and value is not None:
                try:
                    entry[stat] = float(value)
                except (TypeError, ValueError):
                    pass
            gp = row.get(f"{side}_games_played")
            if gp is not None and GP_CATEGORY not in entry:
                try:
                    entry[GP_CATEGORY] = float(gp)
                except (TypeError, ValueError):
                    pass
    return totals


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _spearman(projected: list[float], actual: list[float]) -> Optional[float]:
    """Spearman rank correlation (average ranks on ties). None for n < 3
    or degenerate (constant) inputs where correlation is undefined."""
    if len(projected) < 3:
        return None
    p = pd.Series(projected).rank()
    a = pd.Series(actual).rank()
    if p.nunique() < 2 or a.nunique() < 2:
        return None
    corr = p.corr(a)
    return None if pd.isna(corr) else round(float(corr), 3)


def score_week(
    projected: dict[str, dict[str, float]],
    actual: dict[str, dict[str, float]],
    categories: tuple[str, ...] = CATEGORIES,
) -> dict[str, Any]:
    """Score one source-week: projected vs actual team totals.

    Only teams present on both sides count (name mismatches shrink
    coverage visibly via ``teams_matched`` instead of corrupting the
    metrics). Per category: MAE, MAE as % of the actual mean magnitude,
    signed bias (projected − actual; positive = over-projection), and
    Spearman rank correlation across teams.
    """
    teams = sorted(set(projected) & set(actual))
    scored_categories = list(categories)
    if any(GP_CATEGORY in actual[t] for t in teams):
        scored_categories.append(GP_CATEGORY)

    per_category: dict[str, dict[str, Any]] = {}
    for cat in scored_categories:
        proj_vals: list[float] = []
        act_vals: list[float] = []
        for t in teams:
            pv = projected[t].get(cat)
            av = actual[t].get(cat)
            if pv is None or av is None:
                continue
            proj_vals.append(float(pv))
            act_vals.append(float(av))
        if not proj_vals:
            continue
        errors = [p - a for p, a in zip(proj_vals, act_vals)]
        mae = sum(abs(e) for e in errors) / len(errors)
        bias = sum(errors) / len(errors)
        actual_scale = sum(abs(a) for a in act_vals) / len(act_vals)
        per_category[cat] = {
            "mae": round(mae, 4),
            "mae_pct": round(mae / actual_scale, 4) if actual_scale > 0 else None,
            "bias": round(bias, 4),
            "rank_corr": _spearman(proj_vals, act_vals),
            "teams": len(proj_vals),
        }

    return {
        "per_category": per_category,
        "teams_matched": len(teams),
        "teams_total": len(actual),
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def build_accuracy_scoreboard(
    *,
    recap_store: Any,
    league_id: str,
    league_slug: str,
    season: int,
    current_week: Optional[int] = None,
    projection_store: Optional[ProjectionStore] = None,
) -> dict[str, Any]:
    """Assemble the full accuracy scoreboard for one league season.

    Scores every stored week-horizon set (global sets like BBM, plus this
    league's ESPN snapshots) whose week has stored actuals. The current
    in-progress week is excluded when ``current_week`` is known — partial
    actuals would flatter nobody fairly. Everything unscoreable is listed
    with a reason (honest empty over silent absence).
    """
    pstore = projection_store or ProjectionStore()

    actual_weeks = sorted(
        recap_store.list_week_scoreboard_weeks(league_id=league_id, season=season)
    )

    # Candidate sets: week-scoped, real (not the live-ESPN sentinel), and
    # either global or scoped to this league. Manifest order is newest
    # first — keep the newest per (source, week).
    candidates: dict[tuple[str, int], Any] = {}
    for s in pstore.list_sets(horizon="week"):
        if s.set_id == ESPN_VIRTUAL_SET_ID or s.week is None:
            continue
        if s.league_slug is not None and s.league_slug != league_slug:
            continue
        candidates.setdefault((s.source, int(s.week)), s)

    # Lazily-built roster maps from this league's ESPN snapshot per week.
    espn_maps: dict[int, Optional[dict[str, str]]] = {}

    def _espn_roster_map(week: int) -> Optional[dict[str, str]]:
        if week not in espn_maps:
            espn_set = candidates.get(("espn", week))
            rows = pstore.load_set(espn_set.set_id) if espn_set else None
            espn_maps[week] = roster_map_from_rows(rows) if rows else None
        return espn_maps[week]

    weeks_out: list[dict[str, Any]] = []
    unscoreable: list[dict[str, Any]] = []

    for (source, week), pset in sorted(candidates.items()):
        def _skip(reason: str) -> None:
            unscoreable.append({"source": source, "week": week, "reason": reason})

        if current_week is not None and week >= current_week:
            _skip("week_in_progress")
            continue
        if week not in actual_weeks:
            _skip("no_actuals_for_week")
            continue

        rows = pstore.load_set(pset.set_id)
        if not rows:
            _skip("set_file_missing")
            continue

        roster_map: Optional[dict[str, str]] = None
        if not any(r.roster_team for r in rows):
            roster_map = _espn_roster_map(week)
            if not roster_map:
                _skip("no_roster_mapping")
                continue

        stored = recap_store.get_week_scoreboard(
            league_id=league_id, season=season, week=week
        )
        payload = (stored or {}).get("payload_json") or []
        actual = actual_team_totals(payload)
        if not actual:
            _skip("empty_actuals")
            continue

        projected, skipped_rows = projected_team_totals(rows, roster_map)
        score = score_week(projected, actual)
        if score["teams_matched"] == 0:
            _skip("no_team_overlap")
            continue

        weeks_out.append({
            "source": source,
            "week": week,
            "set_id": pset.set_id,
            "uploaded_at": pset.uploaded_at,
            "players_unassigned": skipped_rows,
            **score,
        })

    return {
        "league": league_slug,
        "season": season,
        "weeks_with_actuals": actual_weeks,
        "sources": _aggregate_sources(weeks_out),
        "weeks": weeks_out,
        "unscoreable": unscoreable,
    }


def _aggregate_sources(weeks_out: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per source × category means across scored weeks."""
    by_source: dict[str, list[dict[str, Any]]] = {}
    for entry in weeks_out:
        by_source.setdefault(entry["source"], []).append(entry)

    out: list[dict[str, Any]] = []
    for source, entries in sorted(by_source.items()):
        cats: dict[str, dict[str, Any]] = {}
        cat_names: set[str] = set()
        for e in entries:
            cat_names.update(e["per_category"].keys())
        for cat in sorted(cat_names):
            samples = [
                e["per_category"][cat]
                for e in entries
                if cat in e["per_category"]
            ]
            corrs = [
                s["rank_corr"] for s in samples if s["rank_corr"] is not None
            ]
            pcts = [s["mae_pct"] for s in samples if s["mae_pct"] is not None]
            cats[cat] = {
                "mae": round(sum(s["mae"] for s in samples) / len(samples), 4),
                "mae_pct": round(sum(pcts) / len(pcts), 4) if pcts else None,
                "bias": round(sum(s["bias"] for s in samples) / len(samples), 4),
                "rank_corr": round(sum(corrs) / len(corrs), 3) if corrs else None,
                "weeks": len(samples),
            }
        out.append({
            "source": source,
            "weeks_scored": len(entries),
            "per_category": cats,
        })
    return out
