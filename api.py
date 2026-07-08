"""
FastAPI layer over `data_feed` and `optimize_lineup` — thin wrappers only; no business-logic changes.
"""
from __future__ import annotations

import io
import math
import os
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

import data_feed as feed
from config import LEAGUE_ID, SEASON
from fantasy import MyLeague
from optimize_lineup import OptimizeLineup, generate_multiple_plans

# Load local environment variables (e.g. ANTHROPIC_API_KEY) when running the dev server.
# This keeps `ANTHROPIC_API_KEY` setup simple even if it's not exported in the shell.
try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")
except Exception:
    # If `python-dotenv` isn't installed or .env doesn't exist, we'll just rely on real env vars.
    pass

app = FastAPI(title="PatriotGames Fantasy API", version="0.1.0")

# Browser dev: any localhost / 127.0.0.1 port (Vite may use 5174+, etc.) + common LAN preview IPs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3})(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _my_league(year: Optional[int] = None) -> MyLeague:
    """`MyLeague` for in-season endpoints; uses `SEASON` from config when year is omitted."""
    y = SEASON if year is None else year
    return MyLeague(LEAGUE_ID, y)


def _strip_numpy(obj: Any) -> Any:
    """Convert numpy/pandas scalar values to native Python for jsonable_encoder."""
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _strip_numpy(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_numpy(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_strip_numpy(x) for x in obj)
    return obj


def _df_records(df: Optional[pd.DataFrame]) -> List[dict[str, Any]]:
    if df is None:
        return []
    out = df.where(pd.notnull(df), None)
    return jsonable_encoder(_strip_numpy(out.to_dict(orient="records")))


def _handles():
    return feed.connect()


def _read_excel_bytes(data: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(data))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/league/meta")
def league_meta() -> dict[str, Any]:
    h = _handles()
    return feed.pull_league_meta(h)


@app.get("/league/my-league/schedule")
def my_league_schedule(
    year: Optional[int] = Query(None, description="ESPN season year; defaults to config SEASON"),
) -> List[dict[str, Any]]:
    try:
        ml = _my_league(year)
        return _df_records(ml.get_schedule())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/league/my-league/current-week-matchups")
def my_league_current_week_matchups(
    year: Optional[int] = Query(None, description="ESPN season year; defaults to config SEASON"),
) -> List[dict[str, Any]]:
    try:
        ml = _my_league(year)
        return _df_records(ml.get_current_week_matchups())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/power-rankings")
def power_rankings(
    weeks: str = Query(..., description="Comma-separated week list, e.g. '1,2,3'"),
    recent_weeks: int = Query(3, description="How many trailing weeks count as 'recent'"),
) -> List[dict[str, Any]]:
    """
    Composite power rankings using only two `get_universe_wins` calls:
    - full window (all requested weeks)
    - recent window (last N weeks from the requested set)
    """
    try:
        ml = _my_league()

        all_weeks: List[int] = []
        for tok in (weeks or "").split(","):
            t = tok.strip()
            if not t:
                continue
            all_weeks.append(int(t))
        all_weeks = sorted(set(all_weeks))
        if not all_weeks:
            raise HTTPException(status_code=422, detail="`weeks` must include at least one week number.")

        # Clamp to weeks that actually exist in this league's matchup data.
        # Some leagues report a `currentMatchupPeriod` that exceeds the schedule length; `MyLeague`
        # can raise KeyError(week) if the week isn't present in `league_matchups`.
        max_week = 0
        try:
            lm = getattr(ml, "league_matchups", None)
            if isinstance(lm, dict) and lm:
                max_week = max(int(k) for k in lm.keys())
        except Exception:
            max_week = 0
        if max_week <= 0:
            max_week = int(getattr(ml, "length_of_schedule", 0) or 0)

        if max_week > 0:
            all_weeks = [w for w in all_weeks if 1 <= int(w) <= max_week]
        if not all_weeks:
            raise HTTPException(
                status_code=422,
                detail=f"No valid weeks in request. Valid range is 1..{max_week or 'N/A'}.",
            )

        rw = max(1, int(recent_weeks))
        recent_list = all_weeks[-rw:] if len(all_weeks) >= 1 else all_weeks

        # ESPN schedule weeks can be shorter than our UI's 1..22 range; `MyLeague`
        # can raise KeyError(week) when a requested week isn't present.
        try:
            df_full = ml.get_universe_wins(weeks=all_weeks)
            df_recent = ml.get_universe_wins(weeks=recent_list)
        except KeyError as ke:
            bad = None
            try:
                if ke.args:
                    bad = int(ke.args[0])
            except Exception:
                bad = None
            if bad is None:
                raise
            all_weeks = [w for w in all_weeks if int(w) != bad]
            if not all_weeks:
                raise HTTPException(status_code=422, detail=f"Week {bad} is not available for this league.")
            recent_list = all_weeks[-rw:] if len(all_weeks) >= 1 else all_weeks
            df_full = ml.get_universe_wins(weeks=all_weeks)
            df_recent = ml.get_universe_wins(weeks=recent_list)

        if df_full is None or df_full.empty or "Team" not in df_full.columns:
            raise HTTPException(status_code=500, detail="get_universe_wins returned empty full-window data.")
        if df_recent is None or df_recent.empty or "Team" not in df_recent.columns:
            raise HTTPException(status_code=500, detail="get_universe_wins returned empty recent-window data.")

        # Normalize required columns.
        for col in ["Total Win %", "Actual Win %"]:
            if col in df_full.columns:
                df_full[col] = pd.to_numeric(df_full[col], errors="coerce")
        if "Total Win %" in df_recent.columns:
            df_recent["Total Win %"] = pd.to_numeric(df_recent["Total Win %"], errors="coerce")

        # Stat category ranks from the full window.
        stat_cols = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]
        stat_cols_avail = [c for c in stat_cols if c in df_full.columns]
        stats = df_full[["Team"] + stat_cols_avail].copy()
        for c in stat_cols_avail:
            stats[c] = pd.to_numeric(stats[c], errors="coerce")

        ranks: dict[str, pd.Series] = {}
        for c in stat_cols:
            if c not in stats.columns:
                continue
            # Higher is better for all categories here (TO is already inverted upstream in MyLeague.get_wins).
            ranks[c] = stats[c].rank(method="min", ascending=False).astype("Int64")

        rank_df = pd.DataFrame({"Team": stats["Team"]})
        for c, sr in ranks.items():
            rank_df[f"{c.lower().replace('%','_pct')}_rank"] = sr

        # Category dominance: fraction of categories where team is top-3 in league.
        top3_counts = pd.Series(0, index=rank_df.index, dtype="int")
        denom = 0
        for c in stat_cols:
            key = f"{c.lower().replace('%','_pct')}_rank"
            if key in rank_df.columns:
                denom += 1
                top3_counts += (pd.to_numeric(rank_df[key], errors="coerce").fillna(999) <= 3).astype(int)
        dominance = (top3_counts / float(denom or 9)).astype(float)

        # Merge win% components.
        base = df_full[["Team", "Total Win %", "Actual Win %"]].copy()
        base = base.rename(columns={"Total Win %": "allplay_win_pct", "Actual Win %": "actual_win_pct"})
        recent = df_recent[["Team", "Total Win %"]].copy().rename(columns={"Total Win %": "recent_allplay_win_pct"})

        out = base.merge(recent, on="Team", how="left").merge(rank_df, on="Team", how="left")
        out["category_dominance_score"] = dominance.values

        # Composite score (normalize % -> 0..1).
        out["composite_score"] = (
            0.35 * (pd.to_numeric(out["allplay_win_pct"], errors="coerce").fillna(0) / 100.0)
            + 0.35 * (pd.to_numeric(out["recent_allplay_win_pct"], errors="coerce").fillna(0) / 100.0)
            + 0.20 * (pd.to_numeric(out["actual_win_pct"], errors="coerce").fillna(0) / 100.0)
            + 0.10 * (pd.to_numeric(out["category_dominance_score"], errors="coerce").fillna(0))
        )

        out = out.sort_values("composite_score", ascending=False).reset_index(drop=True)
        out["rank"] = out.index + 1

        # Rank change: compare to the same calculation with the most recent week removed.
        rank_change_map: dict[str, int] = {str(t): 0 for t in out["Team"].astype(str).tolist()}
        if len(all_weeks) >= 2:
            prev_weeks = all_weeks[:-1]
            prev_recent = prev_weeks[-rw:] if prev_weeks else prev_weeks
            df_full_prev = ml.get_universe_wins(weeks=prev_weeks)
            df_recent_prev = ml.get_universe_wins(weeks=prev_recent)

            for col in ["Total Win %", "Actual Win %"]:
                if col in df_full_prev.columns:
                    df_full_prev[col] = pd.to_numeric(df_full_prev[col], errors="coerce")
            if "Total Win %" in df_recent_prev.columns:
                df_recent_prev["Total Win %"] = pd.to_numeric(df_recent_prev["Total Win %"], errors="coerce")

            stats_prev = df_full_prev[["Team"] + [c for c in stat_cols if c in df_full_prev.columns]].copy()
            for c in stats_prev.columns:
                if c != "Team":
                    stats_prev[c] = pd.to_numeric(stats_prev[c], errors="coerce")

            rank_df_prev = pd.DataFrame({"Team": stats_prev["Team"]})
            top3_prev = pd.Series(0, index=rank_df_prev.index, dtype="int")
            denom_prev = 0
            for c in stat_cols:
                if c not in stats_prev.columns:
                    continue
                denom_prev += 1
                sr = stats_prev[c].rank(method="min", ascending=False).astype("Int64")
                key = f"{c.lower().replace('%','_pct')}_rank"
                rank_df_prev[key] = sr
                top3_prev += (pd.to_numeric(sr, errors="coerce").fillna(999) <= 3).astype(int)

            dom_prev = (top3_prev / float(denom_prev or 9)).astype(float)
            base_prev = df_full_prev[["Team", "Total Win %", "Actual Win %"]].copy().rename(
                columns={"Total Win %": "allplay_win_pct", "Actual Win %": "actual_win_pct"}
            )
            recent_prev = df_recent_prev[["Team", "Total Win %"]].copy().rename(columns={"Total Win %": "recent_allplay_win_pct"})
            prev = base_prev.merge(recent_prev, on="Team", how="left").merge(rank_df_prev, on="Team", how="left")
            prev["category_dominance_score"] = dom_prev.values
            prev["composite_score"] = (
                0.35 * (pd.to_numeric(prev["allplay_win_pct"], errors="coerce").fillna(0) / 100.0)
                + 0.35 * (pd.to_numeric(prev["recent_allplay_win_pct"], errors="coerce").fillna(0) / 100.0)
                + 0.20 * (pd.to_numeric(prev["actual_win_pct"], errors="coerce").fillna(0) / 100.0)
                + 0.10 * (pd.to_numeric(prev["category_dominance_score"], errors="coerce").fillna(0))
            )
            prev = prev.sort_values("composite_score", ascending=False).reset_index(drop=True)
            prev["rank"] = prev.index + 1
            prev_rank_map = {str(r["Team"]): int(r["rank"]) for _, r in prev.iterrows()}
            for _, r in out.iterrows():
                team = str(r["Team"])
                cur_rank = int(r["rank"])
                prev_rank = prev_rank_map.get(team)
                if prev_rank is None:
                    rank_change_map[team] = 0
                else:
                    # Positive means moved up.
                    rank_change_map[team] = int(prev_rank - cur_rank)

        out["rank_change"] = out["Team"].astype(str).map(rank_change_map).fillna(0).astype(int)

        # API response fields / naming.
        resp_cols = [
            "rank",
            "Team",
            "composite_score",
            "rank_change",
            "allplay_win_pct",
            "recent_allplay_win_pct",
            "actual_win_pct",
            "category_dominance_score",
        ] + [c for c in out.columns if c.endswith("_rank") and c != "rank"]

        out = out[resp_cols].rename(columns={"Team": "team"})
        return _df_records(out)
    except HTTPException:
        raise
    except Exception as e:
        # Surface exception type to make debugging easier in the UI/clients.
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e


@app.get("/confidence")
def confidence(
    projected_value: float = Query(..., description="Projected stat value to evaluate"),
    stat: str = Query(..., description="Stat name (e.g. PTS, REB, TO, FG%, FT%)"),
    player_avg: float = Query(..., description="Player season average for the stat (used for tier lookup)"),
) -> dict[str, Any]:
    try:
        from consistency import get_confidence

        return get_confidence(
            projected_value=projected_value,
            stat=stat,
            player_avg=player_avg,
            db_path="data/game_logs.db",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/matchup-confidence")
def matchup_confidence(
    current_matchup_period: int = Query(..., description="ESPN current matchup period"),
    projections: str = Query("BBM", description="Projection source (default: BBM)"),
    games_played: int = Query(0, description="How many matchup games have been played so far"),
    total_games: int = Query(1, description="Total expected matchup games"),
) -> List[dict[str, Any]]:
    """
    Enrich the projected scoreboard with tier/confidence per team/stat.

    Note: for now, `player_avg` is proxied by each team's projected score as requested.
    """
    try:
        h = _handles()
        from consistency import get_confidence

        df = feed.get_projected_scoreboard(
            h,
            current_matchup_period=current_matchup_period,
            projections=projections,
        )

        # Convert team totals into a per-player-per-game scale so confidence is computed
        # against the same scale used by consistency.py (game_logs are per-game).
        week_meta = feed.MATCHUP_WEEKS_2025_26.get(current_matchup_period)
        week_start = week_meta["start"] if week_meta else None
        week_end = week_meta["end"] if week_meta else None
        rosters = feed.get_current_rosters(
            h,
            week_start_date=week_start,
            week_end_date=week_end,
            bbm_path=None,
            bbm_df=None,
            current_matchup_period=current_matchup_period,
            projections=projections,
        )
        rosters_df = pd.DataFrame(rosters)
        total_player_games_by_team: dict[str, float] = {}
        if not rosters_df.empty and "team_name" in rosters_df.columns and "num_games_left" in rosters_df.columns:
            # Exclude out players and ensure we only count positive game counts.
            if "injuryStatus" in rosters_df.columns:
                ok = (rosters_df["injuryStatus"].astype(str).str.upper() != "OUT") & pd.to_numeric(
                    rosters_df["num_games_left"], errors="coerce"
                ).fillna(0).gt(0)
                rosters_df = rosters_df[ok]
            else:
                rosters_df = rosters_df[pd.to_numeric(rosters_df["num_games_left"], errors="coerce").fillna(0).gt(0)]

            rosters_df["num_games_left"] = pd.to_numeric(rosters_df["num_games_left"], errors="coerce").fillna(0)
            totals = rosters_df.groupby("team_name", as_index=False)["num_games_left"].sum()
            total_player_games_by_team = {
                str(r["team_name"]): float(r["num_games_left"]) for _, r in totals.iterrows()
            }

        def _scaled_confidence(
            team_name: Any,
            projected_val: Any,
            stat_key: str,
        ) -> dict[str, Any]:
            if projected_val is None or pd.isna(projected_val):
                return {
                    "tier": None,
                    "p10": None,
                    "p25": None,
                    "mean": None,
                    "p75": None,
                    "p90": None,
                    "confidence_pct": None,
                }

            x = float(projected_val)

            # Percent categories are already ratios for the matchup period.
            if stat_key in {"fg%", "ft%"}:
                projected_value = x
                player_avg = x
            else:
                games = total_player_games_by_team.get(str(team_name))
                if not games or games <= 0:
                    # Can't scale without player-game counts.
                    projected_value = float("nan")
                    player_avg = float("nan")
                else:
                    if stat_key == "to":
                        # Matchup-scoreboard encodes TO so "higher is better" => it's negative.
                        # The confidence model expects positive turnover counts for LOWER_IS_BETTER handling.
                        x = abs(x)
                    projected_value = x / games
                    player_avg = projected_value

            return get_confidence(
                projected_value=projected_value,
                stat=stat_key,
                player_avg=player_avg,
                db_path="data/game_logs.db",
                games_played=games_played,
                total_games=total_games,
            )

        enriched_rows: List[dict[str, Any]] = []
        for _, row in df.iterrows():
            rec = row.to_dict()
            stat_name = str(rec.get("stat", "")).strip().lower()

            home_team = rec.get("home_team")
            away_team = rec.get("away_team")

            home_val = rec.get("projected_home_score")
            home_res = _scaled_confidence(home_team, home_val, stat_name)
            rec["home_tier"] = home_res.get("tier")
            rec["home_confidence_pct"] = home_res.get("confidence_pct")

            away_val = rec.get("projected_away_score")
            away_res = _scaled_confidence(away_team, away_val, stat_name)
            rec["away_tier"] = away_res.get("tier")
            rec["away_confidence_pct"] = away_res.get("confidence_pct")

            enriched_rows.append(rec)

        return _df_records(pd.DataFrame(enriched_rows))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


class MatchupCommentaryRow(BaseModel):
    stat: str
    home_score: float
    away_score: float
    result: str
    confidence_pct: Optional[float] = None


class ProjectedRosterPlayer(BaseModel):
    player_name: str
    pts: float
    reb: float
    ast: float
    stl: float
    blk: float
    three_pm: float = Field(alias="3pm")
    fg_pct: float
    ft_pct: float
    to: float
    games_left: Optional[int] = None


class MatchupCommentaryBody(BaseModel):
    home_team: str
    away_team: str
    matchup_data: List[MatchupCommentaryRow]
    home_roster: List[ProjectedRosterPlayer] = []
    away_roster: List[ProjectedRosterPlayer] = []
    projections: Optional[str] = None
    is_live: bool = False


class LeagueRecapBody(BaseModel):
    week: int
    league_settings: Dict[str, Any] = {}
    standings: List[Dict[str, Any]]
    power_rankings: List[Dict[str, Any]]
    transactions: List[Dict[str, Any]]
    scoreboard: List[Dict[str, Any]]
    week_dates: Dict[str, str]


@app.post("/matchup-commentary")
def matchup_commentary(body: MatchupCommentaryBody) -> dict[str, Any]:
    """
    Generate a short ESPN-style preview article for the matchup using Anthropic.
    """
    try:
        from anthropic import Anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=500,
                detail="ANTHROPIC_API_KEY is missing. Set it in your environment or create a valid .env file.",
            )

        # Let the anthropic client read ANTHROPIC_API_KEY from the environment.
        client = Anthropic()

        home_team = body.home_team
        away_team = body.away_team
        rows = body.matchup_data
        home_roster = body.home_roster or []
        away_roster = body.away_roster or []
        projections = body.projections
        is_live = bool(getattr(body, "is_live", False))

        if projections == "15":
            projections_desc = "Projections based on last 15 days of performance"
        elif projections == "30":
            projections_desc = "Projections based on last 30 days of performance"
        else:
            projections_desc = "Projections based on Basketball Monster weekly projections"

        home_wins = [r for r in rows if (r.result or "").upper() == "W"]
        away_wins = [r for r in rows if (r.result or "").upper() == "L"]
        ties = [r for r in rows if (r.result or "").upper() == "T"]

        def _avg_conf(rs: List[MatchupCommentaryRow]) -> Optional[float]:
            vals = [r.confidence_pct for r in rs if r.confidence_pct is not None]
            if not vals:
                return None
            return float(sum(vals) / len(vals))

        home_conf_avg = _avg_conf(home_wins)
        away_conf_avg = _avg_conf(away_wins)

        decisive = [r for r in rows if (r.result or "").upper() in {"W", "L"}]
        overall_conf = _avg_conf(decisive)

        def _fmt_conf_pct(val: Optional[float]) -> str:
            if val is None:
                return "—"
            try:
                if isinstance(val, float) and math.isnan(val):
                    return "—"
            except Exception:
                pass
            return f"{val:.0f}%"

        too_close = [
            r
            for r in rows
            if r.confidence_pct is not None and float(r.confidence_pct) < 55.0
        ]

        dominate_home_stats = ", ".join([r.stat for r in home_wins]) if home_wins else "—"
        dominate_away_stats = ", ".join([r.stat for r in away_wins]) if away_wins else "—"

        projected_record_summary = f"Projected category record: {home_team} {len(home_wins)} - {len(away_wins)} {away_team} (Ties: {len(ties)})."

        # Build category results with context-aware messaging.
        def _format_category_result(r: MatchupCommentaryRow) -> str:
            stat = str(r.stat).upper()
            hs = r.home_score
            as_ = r.away_score
            outcome = (r.result or "").upper()
            if outcome == "W":
                if is_live:
                    return f"{stat}: Home {hs:.0f} - Away {as_:.0f} (Home leads)"
                conf = (
                    f"{(r.confidence_pct or 0.0):.0f}% confidence"
                    if r.confidence_pct is not None
                    else "confidence n/a"
                )
                return f"{stat}: Home {hs:.0f} - Away {as_:.0f} (Home wins, {conf})"
            if outcome == "L":
                if is_live:
                    return f"{stat}: Home {hs:.0f} - Away {as_:.0f} (Away leads)"
                conf = (
                    f"{(r.confidence_pct or 0.0):.0f}% confidence"
                    if r.confidence_pct is not None
                    else "confidence n/a"
                )
                return f"{stat}: Home {hs:.0f} - Away {as_:.0f} (Away wins, {conf})"
            return f"{stat}: Home {hs:.0f} - Away {as_:.0f} (Tied)"

        category_lines = [_format_category_result(r) for r in rows]
        too_close_lines = "\n".join(
            [f"- {r.stat.upper()} ({float(r.confidence_pct):.0f}% confidence)" for r in too_close]
        ) if too_close else "—"

        system_prompt = (
            "You are a witty ESPN fantasy basketball analyst. "
            "Write in the style of a short ESPN news article — punchy, confident, with a bit of personality. "
            "Use fantasy basketball terminology. "
        )
        if is_live:
            system_prompt += "This is a LIVE matchup in progress. Frame your analysis as a mid-week update (how the matchup is shaping up so far). "
        else:
            system_prompt += "Write a preview-style piece about how this matchup is expected to play out. "
        system_prompt += "Keep it to 3-4 paragraphs."

        # Roster formatting (convert to ESPN-style stat snippets).
        def _fmt_pct01(x: float) -> str:
            try:
                return f"{float(x) * 100.0:.1f}%"
            except Exception:
                return "—"

        def _roster_lines(roster: List[ProjectedRosterPlayer]) -> str:
            if not roster:
                return "—"
            max_lines = 10
            # Keep it readable; the prompt isn't trying to include every depth-chart body.
            roster_use = roster[:max_lines]
            out: List[str] = []
            for p in roster_use:
                games_left = getattr(p, "games_left", None)
                games_left_part = f"; {games_left} games left" if games_left is not None else ""
                out.append(
                    f"- {p.player_name}: {p.pts:.1f} PTS, {p.reb:.1f} REB, {p.ast:.1f} AST, "
                    f"{p.stl:.1f} STL, {p.blk:.1f} BLK, {p.three_pm:.1f} 3PM, "
                    f"{_fmt_pct01(p.fg_pct)} FG, {_fmt_pct01(p.ft_pct)} FT, {p.to:.1f} TO{games_left_part}"
                )
            return "\n".join(out)

        decided_home = [r.stat.upper() for r in rows if (r.result or "").upper() == "W"]
        decided_away = [r.stat.upper() for r in rows if (r.result or "").upper() == "L"]
        still_played = [r.stat.upper() for r in rows if (r.result or "").upper() == "T"]

        if is_live:
            user_prompt = (
                f"HOME TEAM: {home_team}\n"
                "Roster:\n"
                f"{_roster_lines(home_roster)}\n\n"
                f"AWAY TEAM: {away_team}\n"
                "Roster:\n"
                f"{_roster_lines(away_roster)}\n\n"
                f"PROJECTION CONTEXT: {projections_desc}\n\n"
                "LIVE CATEGORY RESULTS (so far):\n"
                + "\n".join(category_lines)
                + "\n\n"
                "Categories already decided so far:\n"
                f"- Home leads in: {', '.join(decided_home) if decided_home else '—'}\n"
                f"- Away leads in: {', '.join(decided_away) if decided_away else '—'}\n\n"
                "Categories still being played (currently tied):\n"
                f"{', '.join(still_played) if still_played else '—'}\n\n"
                "Write a mid-week live update on how this matchup is shaping up so far. "
                "Highlight standout players on each team and mention any category tied up right now that could swing. "
                "Keep it to 3-4 punchy paragraphs in ESPN-style news article tone, with a bit of personality."
            )
        else:
            user_prompt = (
                f"HOME TEAM: {home_team}\n"
                "Roster:\n"
                f"{_roster_lines(home_roster)}\n\n"
                f"AWAY TEAM: {away_team}\n"
                "Roster:\n"
                f"{_roster_lines(away_roster)}\n\n"
                f"PROJECTION SOURCE: {projections_desc}\n\n"
                "PROJECTED CATEGORY RESULTS:\n"
                + "\n".join(category_lines)
                + "\n\n"
                f"Overall confidence level (decisive categories avg): {_fmt_conf_pct(overall_conf)}\n"
                f"Home win-category confidence avg: {_fmt_conf_pct(home_conf_avg)}\n"
                f"Away win-category confidence avg: {_fmt_conf_pct(away_conf_avg)}\n\n"
                f"Categories too close to call (confidence < 55%):\n{too_close_lines}\n\n"
                "Write a preview article about how this matchup is expected to play out. "
                "Highlight standout players on each team, call out any category that is too close to call, "
                "and mention any category where one team has a particularly dominant advantage. "
                "Keep it to 3-4 punchy paragraphs in ESPN-style news article tone, with a bit of personality."
            )

        # Anthropics Messages API.
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        commentary_text = ""
        if getattr(resp, "content", None):
            for block in resp.content:
                # block is usually a TextBlock with `.text`.
                if hasattr(block, "text"):
                    commentary_text += block.text
        commentary_text = commentary_text.strip()
        return {"commentary": commentary_text}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/league-recap")
def league_recap(body: LeagueRecapBody) -> dict[str, Any]:
    """
    Generate a weekly league newsletter recap (ESPN-style) using Anthropic.
    """
    try:
        from anthropic import Anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=500,
                detail="ANTHROPIC_API_KEY is missing. Set it in your environment or create a valid .env file.",
            )

        client = Anthropic()

        week = body.week
        league_settings = body.league_settings or {}
        standings = body.standings
        power_rankings = body.power_rankings
        transactions = body.transactions
        scoreboard = body.scoreboard
        week_dates = body.week_dates

        # Defensive: ensure we only send the 9 standard categories in the recap payload,
        # even if a client accidentally includes made/attempt stats.
        keep_stats = {"PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"}
        try:
            scoreboard = [r for r in (scoreboard or []) if str(r.get("stat")) in keep_stats]
        except Exception:
            scoreboard = scoreboard or []

        def _build_matchup_results(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            # Group by matchup pair. Note: scoreboard rows include both teams per stat in the same row.
            # We compute explicit 9-cat W/L/T and final category score to avoid the model misreading raw rows.
            by_key: dict[tuple[str, str], list[Dict[str, Any]]] = {}
            for r in rows or []:
                home = str(r.get("home_team") or "")
                away = str(r.get("away_team") or "")
                if not home or not away or home.lower() == "bye" or away.lower() == "bye":
                    continue
                by_key.setdefault((home, away), []).append(r)

            out: List[Dict[str, Any]] = []
            for (home, away), rs in by_key.items():
                home_w = away_w = ties = 0
                per_stat: List[Dict[str, Any]] = []
                for r in rs:
                    stat = str(r.get("stat"))
                    if stat not in keep_stats:
                        continue
                    try:
                        hs = float(r.get("current_home_score") or 0)
                    except Exception:
                        hs = 0.0
                    try:
                        as_ = float(r.get("current_away_score") or 0)
                    except Exception:
                        as_ = 0.0

                    if hs > as_:
                        res = "HOME"
                        home_w += 1
                    elif hs < as_:
                        res = "AWAY"
                        away_w += 1
                    else:
                        res = "TIE"
                        ties += 1
                    per_stat.append({"stat": stat, "home": hs, "away": as_, "winner": res})

                # Sort stats in a stable "fantasy" order for readability.
                stat_order = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]
                per_stat = sorted(per_stat, key=lambda x: stat_order.index(x["stat"]) if x["stat"] in stat_order else 999)

                out.append(
                    {
                        "home_team": home,
                        "away_team": away,
                        "home_cat_wins": home_w,
                        "away_cat_wins": away_w,
                        "cat_ties": ties,
                        "final_score": f"{home_w}-{away_w}" if ties == 0 else f"{home_w}-{away_w}-{ties}",
                        "by_category": per_stat,
                    }
                )
            return out

        matchup_results = _build_matchup_results(scoreboard or [])

        def _int_setting(key: str) -> Optional[int]:
            try:
                v = league_settings.get(key)
                return None if v is None else int(v)
            except Exception:
                return None

        reg_season_count = _int_setting("reg_season_count")
        playoff_team_count = _int_setting("playoff_team_count")
        playoff_matchup_period_length = _int_setting("playoff_matchup_period_length")
        team_count = _int_setting("team_count")

        # Determine season context for the selected recap week.
        phase = "regular season"
        phase_detail = ""
        if reg_season_count is not None and week == reg_season_count:
            phase_detail = " (final week of the regular season)"
        if reg_season_count is not None and week > reg_season_count:
            phase = "playoffs"
            p_len = playoff_matchup_period_length or 1
            playoff_week_num = ((week - reg_season_count - 1) // max(1, p_len)) + 1
            # Approximate number of playoff rounds from bracket size.
            rounds = None
            try:
                import math

                if playoff_team_count and playoff_team_count > 1:
                    rounds = int(math.ceil(math.log2(int(playoff_team_count))))
            except Exception:
                rounds = None
            if rounds:
                if playoff_week_num >= rounds:
                    phase_detail = f" (championship round; playoffs week {playoff_week_num} of {rounds})"
                else:
                    phase_detail = f" (playoffs week {playoff_week_num} of {rounds})"
            else:
                phase_detail = f" (playoffs week {playoff_week_num})"

        system_prompt = (
            "You are a witty, opinionated ESPN fantasy basketball analyst writing the weekly league newsletter. "
            "Write with personality — call out good moves, bad moves, lucky wins, and dominant performances. "
            "Use fantasy basketball slang. "
            "Structure your response with these exact sections: "
            "HEADLINE (one punchy sentence), "
            "RESULTS (recap each matchup result in 1-2 sentences each), "
            "MOVE OF THE WEEK (best waiver/trade move), "
            "POWER RANKINGS RECAP (who rose, who fell and why), "
            "LOOKING AHEAD (2-3 sentences on the week ahead)."
        )

        # Provide explicit matchup results so the model doesn't have to infer winners from raw stat rows.
        user_prompt = (
            f"WEEK: {week}\n"
            f"WEEK DATES: start={week_dates.get('start')} end={week_dates.get('end')}\n\n"
            f"SEASON CONTEXT: {phase}{phase_detail}\n"
            "LEAGUE SETTINGS (for context):\n"
            f"{jsonable_encoder({'reg_season_count': reg_season_count, 'playoff_team_count': playoff_team_count, 'playoff_matchup_period_length': playoff_matchup_period_length, 'team_count': team_count, 'name': league_settings.get('name'), 'scoring_type': league_settings.get('scoring_type')})}\n\n"
            "LEAGUE STANDINGS:\n"
            f"{jsonable_encoder(standings)}\n\n"
            "POWER RANKINGS (with rank changes):\n"
            f"{jsonable_encoder(power_rankings)}\n\n"
            "TRANSACTIONS (adds/drops/trades):\n"
            f"{jsonable_encoder(transactions)}\n\n"
            "WEEK RESULTS (final category scores and per-category winners):\n"
            f"{jsonable_encoder(matchup_results)}\n\n"
            "Write the recap now. Use the section headers exactly as specified."
        )

        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        recap_text = ""
        if getattr(resp, "content", None):
            for block in resp.content:
                if hasattr(block, "text"):
                    recap_text += block.text
        recap_text = (recap_text or "").strip()

        return {"recap": recap_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/league/teams")
def league_teams() -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(feed.teams_df(h))


@app.get("/league/standings")
def league_standings() -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(feed.standings_df(h))


@app.get("/league/settings")
def league_settings() -> dict[str, Any]:
    try:
        h = _handles()
        s = getattr(h.league, "settings", None)
        out = {
            "reg_season_count": getattr(s, "reg_season_count", None),
            "playoff_team_count": getattr(s, "playoff_team_count", None),
            "playoff_matchup_period_length": getattr(s, "playoff_matchup_period_length", None),
            "name": getattr(s, "name", None),
            "team_count": getattr(s, "team_count", None),
            "acquisition_budget": getattr(s, "acquisition_budget", None),
            "faab": getattr(s, "faab", None),
            "scoring_type": getattr(s, "scoring_type", None),
            "current_week": getattr(h.league, "currentMatchupPeriod", None),
        }
        return jsonable_encoder(out)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/season-stats")
def season_stats(
    weeks: str = Query(..., description="Comma-separated list of week numbers, e.g. '1,2,3'"),
) -> List[dict[str, Any]]:
    try:
        ml = _my_league()
        week_list = []
        for tok in (weeks or "").split(","):
            t = tok.strip()
            if not t:
                continue
            week_list.append(int(t))
        if not week_list:
            raise HTTPException(status_code=422, detail="`weeks` must contain at least one integer week number.")
        df = ml.get_universe_wins(weeks=week_list)
        return _df_records(df)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


class SeasonCommentaryBody(BaseModel):
    """Season stats aggregate; `weeks` must match the week range used to build `season_stats`."""

    season_stats: List[Dict[str, Any]]
    weeks: List[int]
    league_settings: Dict[str, Any]
    min_week: Optional[int] = None
    max_week: Optional[int] = None


@app.post("/season-commentary")
def season_commentary(body: SeasonCommentaryBody) -> dict[str, Any]:
    try:
        from anthropic import Anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=500,
                detail="ANTHROPIC_API_KEY is missing. Set it in your environment or create a valid .env file.",
            )

        league_settings = body.league_settings or {}
        reg_season_count = int(league_settings.get("reg_season_count") or 0)
        playoff_team_count = int(league_settings.get("playoff_team_count") or 0)

        weeks_sorted = sorted({int(w) for w in (body.weeks or [])})
        if not weeks_sorted:
            raise HTTPException(
                status_code=422,
                detail="`weeks` must contain at least one week number.",
            )
        min_w = weeks_sorted[0]
        max_w = weeks_sorted[-1]
        week_count = len(weeks_sorted)
        if body.min_week is not None and int(body.min_week) != min_w:
            raise HTTPException(
                status_code=422,
                detail="`min_week` must match the smallest value in `weeks`.",
            )
        if body.max_week is not None and int(body.max_week) != max_w:
            raise HTTPException(
                status_code=422,
                detail="`max_week` must match the largest value in `weeks`.",
            )

        if reg_season_count <= 0:
            reg_season_count = max_w or week_count or 1

        # Phase from the latest week in the requested window (not ESPN "current" week).
        peak_week = max_w
        half = reg_season_count * 0.5
        phase: str
        playoff_week: Optional[int] = None
        if peak_week <= half:
            phase = "early season"
        elif peak_week <= reg_season_count:
            phase = "mid season"
        else:
            phase = "playoffs"
            playoff_week = max(1, peak_week - reg_season_count)

        df = pd.DataFrame(body.season_stats or [])
        if df.empty or "Team" not in df.columns:
            raise HTTPException(status_code=422, detail="`season_stats` must include rows with a 'Team' field.")

        # Build labeled standings for mid-season context.
        standings_rows = df.copy()
        if "Actual Win %" in standings_rows.columns:
            standings_rows["Actual Win %"] = pd.to_numeric(standings_rows["Actual Win %"], errors="coerce")
            standings_rows = standings_rows.sort_values("Actual Win %", ascending=False)

        standings_rows = standings_rows.reset_index(drop=True)
        standings_rows["Actual Rank"] = standings_rows.index + 1

        label_map: dict[str, str] = {}
        if phase == "mid season" and playoff_team_count > 0:
            for _, r in standings_rows.iterrows():
                team = str(r.get("Team"))
                rank = int(r.get("Actual Rank") or 0)
                if rank <= playoff_team_count:
                    label_map[team] = "Playoff Position"
                elif rank <= playoff_team_count + 2:
                    label_map[team] = "On the Bubble"
                else:
                    label_map[team] = "Eliminated (for now)"
        else:
            for _, r in standings_rows.iterrows():
                team = str(r.get("Team"))
                label_map[team] = "—"

        standings_rows["Status"] = standings_rows["Team"].map(label_map).fillna("—")

        # Stat leaders: use available stat columns from get_universe_wins (stat totals are named like 'PTS', 'REB', ...)
        stat_cols = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "TO", "FG%", "FT%"]
        available_stats = [c for c in stat_cols if c in df.columns]
        leaders = {}
        for c in available_stats:
            try:
                series = pd.to_numeric(df[c], errors="coerce")
                if c == "TO":
                    idx = series.idxmin()
                else:
                    idx = series.idxmax()
                team = str(df.loc[idx, "Team"]) if idx is not None and idx == idx else None
                val = df.loc[idx, c] if idx is not None and idx == idx else None
                leaders[c] = {"team": team, "value": val}
            except Exception:
                leaders[c] = {"team": None, "value": None}

        if phase == "early season":
            system_prompt = (
                "You are writing an early season fantasy basketball power piece. "
                "Focus on fast starters, early trends, and bold predictions. "
                "Only discuss the matchup weeks the user lists; never reference ESPN's current period or weeks outside that list."
            )
        elif phase == "mid season":
            system_prompt = (
                "You are writing a mid-season fantasy basketball analysis. "
                "Focus on playoff races, who's on the bubble, trade deadline implications, and which teams are peaking or fading. "
                "Only discuss the matchup weeks the user lists; never reference ESPN's current period or weeks outside that list."
            )
        else:
            system_prompt = (
                "You are writing a fantasy basketball playoff recap. "
                f"Within the user's data window, the latest week falls in the playoffs (playoff week {playoff_week} relative to the regular season length they provide). "
                "Focus on who has been eliminated, who is still alive, dominant performances, and championship predictions. "
                "Only discuss the matchup weeks the user lists; never reference ESPN's current period or weeks outside that list."
            )

        standings_payload = _strip_numpy(standings_rows.to_dict(orient="records"))
        if all(c in df.columns for c in ["Team", "Actual Win %", "Total Win %", "Win % Ratio"]):
            luck_payload = _strip_numpy(
                df[["Team", "Actual Win %", "Total Win %", "Win % Ratio"]].to_dict(
                    orient="records"
                )
            )
        else:
            luck_payload = _strip_numpy(df.to_dict(orient="records"))
        leaders_payload = _strip_numpy(leaders)

        if min_w == max_w:
            coverage_line = (
                f"This analysis covers week {min_w} only (1 week of data)."
            )
        else:
            coverage_line = (
                f"This analysis covers weeks {min_w} through {max_w} ({week_count} weeks of data)."
            )

        user_prompt = (
            "FANTASY MATCHUP WEEKS IN THIS REQUEST (the only weeks you may reference; "
            "do not mention ESPN's current matchup period, the live week, or any week not listed here):\n"
            f"Week numbers: {weeks_sorted}\n"
            f"{coverage_line}\n\n"
            f"SEASON PHASE (from the latest week in the window above, vs league regular-season length): {phase}\n"
            f"REGULAR SEASON LENGTH (weeks, league setting): {reg_season_count}\n"
            f"PLAYOFF TEAM COUNT (league setting): {playoff_team_count}\n\n"
            "FULL STANDINGS (include labels):\n"
            f"{jsonable_encoder(standings_payload)}\n\n"
            "ALL-PLAY / LUCK (use Total Win % vs Actual Win % and Win % Ratio):\n"
            f"{jsonable_encoder(luck_payload)}\n\n"
            "STAT LEADERS (team/value):\n"
            f"{jsonable_encoder(leaders_payload)}\n\n"
            "Write the season commentary now. Use personality, fantasy slang, and cite specific teams. "
            "Ground every claim in the stats above and the weeks listed at the top — nothing else."
        )

        client = Anthropic()
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        commentary_text = ""
        if getattr(resp, "content", None):
            for block in resp.content:
                if hasattr(block, "text"):
                    commentary_text += block.text
        commentary_text = (commentary_text or "").strip()
        return {"commentary": commentary_text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/rosters/{on_date}")
def rosters_on_date(on_date: date) -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(feed.rosters_df(h, on_date))


@app.get("/transactions")
def transactions(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
) -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(feed.transactions_df(h, start=start, end=end))


@app.get("/matchups")
def matchups(scoring_period: Optional[int] = None) -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(feed.matchups_df(h, scoring_period=scoring_period))


@app.get("/scoreboard/current")
def scoreboard_current(scoring_period: Optional[int] = None) -> List[dict[str, Any]]:
    h = _handles()
    df = feed.get_current_scoreboard(h, scoring_period=scoring_period)
    if df is None or df.empty:
        return []

    # Weekly recap (and most UI) should use only the 9 standard categories.
    # ESPN box scores often include FGM/FGA/FTM/FTA in addition to FG%/FT%.
    keep_stats = {"PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"}

    # If ESPN didn't provide FG%/FT% but did provide made/attempts, derive them.
    stats_present = set(df.get("stat", pd.Series(dtype=str)).astype(str).unique().tolist())
    need_fg = "FG%" not in stats_present and {"FGM", "FGA"} <= stats_present
    need_ft = "FT%" not in stats_present and {"FTM", "FTA"} <= stats_present
    if need_fg or need_ft:
        wide = (
            df.pivot_table(
                index=["home_team", "away_team"],
                columns="stat",
                values=["current_home_score", "current_away_score"],
                aggfunc="first",
            )
            .copy()
        )
        # Flatten columns like ("current_home_score","FGM") -> "current_home_score_FGM"
        wide.columns = [f"{a}_{b}" for a, b in wide.columns]
        wide = wide.reset_index()

        extra_rows: list[dict[str, Any]] = []
        for _, r in wide.iterrows():
            if need_fg:
                h_fgm = float(r.get("current_home_score_FGM", 0) or 0)
                h_fga = float(r.get("current_home_score_FGA", 0) or 0)
                a_fgm = float(r.get("current_away_score_FGM", 0) or 0)
                a_fga = float(r.get("current_away_score_FGA", 0) or 0)
                extra_rows.append(
                    {
                        "home_team": r["home_team"],
                        "away_team": r["away_team"],
                        "stat": "FG%",
                        "current_home_score": (h_fgm / h_fga) if h_fga else 0.0,
                        "current_away_score": (a_fgm / a_fga) if a_fga else 0.0,
                    }
                )
            if need_ft:
                h_ftm = float(r.get("current_home_score_FTM", 0) or 0)
                h_fta = float(r.get("current_home_score_FTA", 0) or 0)
                a_ftm = float(r.get("current_away_score_FTM", 0) or 0)
                a_fta = float(r.get("current_away_score_FTA", 0) or 0)
                extra_rows.append(
                    {
                        "home_team": r["home_team"],
                        "away_team": r["away_team"],
                        "stat": "FT%",
                        "current_home_score": (h_ftm / h_fta) if h_fta else 0.0,
                        "current_away_score": (a_ftm / a_fta) if a_fta else 0.0,
                    }
                )
        if extra_rows:
            df = pd.concat([df, pd.DataFrame(extra_rows)], ignore_index=True)

    df = df[df["stat"].isin(keep_stats)].copy()
    return _df_records(df)


@app.get("/rosters/current")
def rosters_current(
    week_start_date: Optional[str] = None,
    week_end_date: Optional[str] = None,
    bbm_path: Optional[str] = None,
    current_matchup_period: Optional[int] = None,
    projections: Optional[str] = Query(
        None,
        description="Projection source for roster projections (e.g. 'BBM','15','30'). Currently used for API contract compatibility only.",
    ),
) -> List[dict[str, Any]]:
    """Load weekly BBM file from disk via ``bbm_path`` (or config default). For uploads use ``POST /rosters/current``."""
    h = _handles()
    effective_projections = projections or "BBM"
    return _df_records(
        feed.get_current_rosters(
            h,
            week_start_date=week_start_date,
            week_end_date=week_end_date,
            bbm_path=bbm_path,
            bbm_df=None,
            current_matchup_period=current_matchup_period,
            projections=effective_projections,
        )
    )


@app.post("/rosters/current")
async def rosters_current_upload(
    bbm_file: Optional[UploadFile] = File(None, description="Weekly BBM projections Excel file"),
    bbm_path: Optional[str] = Form(None, description="Disk path when no file is uploaded (same as GET)"),
    week_start_date: Optional[str] = Form(None),
    week_end_date: Optional[str] = Form(None),
    current_matchup_period: Optional[str] = Form(None),
    projections: Optional[str] = Query(
        None,
        description="Projection source for roster projections (e.g. 'BBM','15','30'). When no file is uploaded, the app passes this for compatibility.",
    ),
) -> List[dict[str, Any]]:
    """Pass weekly BBM projections as an uploaded file, or use ``bbm_path`` / config default on disk."""
    h = _handles()
    bbm_df = None
    if bbm_file is not None and bbm_file.filename:
        raw = await bbm_file.read()
        bbm_df = _read_excel_bytes(raw)
    cmp: Optional[int] = None
    if current_matchup_period not in (None, ""):
        try:
            cmp = int(current_matchup_period)
        except ValueError:
            raise HTTPException(status_code=422, detail="current_matchup_period must be an integer") from None
    # If no file was uploaded, we *must* have a projection window specified.
    # Otherwise we'd default to BBM and try to load weekly spreadsheets from disk.
    effective_projections = projections
    if effective_projections is None:
        effective_projections = "BBM" if bbm_df is not None else None
    if effective_projections is None:
        raise HTTPException(
            status_code=422,
            detail="Missing `projections` query param when no `bbm_file` is uploaded. Use `projections=BBM|15|30`.",
        )

    # Helpful runtime trace in uvicorn logs so we can confirm which projection
    # mode the client actually requested.
    print(
        f"[rosters_current_upload] projections={projections!r} effective={effective_projections!r} "
        f"has_bbm_file={bbm_df is not None} current_matchup_period={cmp}"
    )

    return _df_records(
        feed.get_current_rosters(
            h,
            week_start_date=week_start_date,
            week_end_date=week_end_date,
            bbm_path=bbm_path,
            bbm_df=bbm_df,
            current_matchup_period=cmp,
            projections=effective_projections,
        )
    )


@app.get("/projections")
def projections(path: Optional[str] = None) -> List[dict[str, Any]]:
    """Read season projections from disk. For uploads use ``POST /projections``."""
    return _df_records(feed.read_projections_xls(path=path))


@app.post("/projections")
async def projections_upload(
    file: Optional[UploadFile] = File(None, description="Season BBM projections Excel file"),
    path: Optional[str] = Form(None, description="Optional disk path if file is omitted"),
) -> List[dict[str, Any]]:
    """Normalize season BBM projections from an uploaded file, or from ``path`` when no file is sent."""
    if file is not None and file.filename:
        raw = await file.read()
        df = _read_excel_bytes(raw)
        return _df_records(feed.read_projections_xls(projections_df=df))
    return _df_records(feed.read_projections_xls(path=path))


class RunFeedBody(BaseModel):
    since: str = Field(..., description="YYYY-MM-DD or 'today'")
    until: str = Field(..., description="YYYY-MM-DD or 'today'")
    outdir: Optional[str] = None
    week_start_date: Optional[str] = None
    week_end_date: Optional[str] = None
    current_matchup_period: Optional[int] = None


@app.post("/feed/run")
def feed_run(body: RunFeedBody) -> dict[str, Any]:
    since = feed._parse_date(body.since)
    until = feed._parse_date(body.until)
    return feed.run(
        since,
        until,
        outdir=body.outdir,
        week_start_date=body.week_start_date,
        week_end_date=body.week_end_date,
        current_matchup_period=body.current_matchup_period,
    )


class DraftPick(BaseModel):
    name: str
    bid: float


class OptimizeBody(BaseModel):
    exclude_players: Optional[List[str]] = None
    games_per_week: float = 3.0
    initial_budget: float = 200
    year: Optional[int] = None
    roster_size: int = 13
    minimum_value_players: int = 3
    favorite_team: Optional[str] = None
    favorite_team_representation: int = 1
    minimum_game_threshold: float = 55
    value_col: str = "$"
    categories: Optional[List[str]] = None
    percentile: float = 0.75
    stat_to_maximize: str = "PTS"
    draft_picks: List[DraftPick] = Field(default_factory=list)


@app.post("/optimizer/optimize")
async def optimizer_optimize(request: Request) -> List[dict[str, Any]]:
    """
    JSON body (``application/json``): same as ``OptimizeBody``.

    Multipart (``multipart/form-data``): field ``data`` = JSON string for ``OptimizeBody``;
    optional file field ``bbm_file`` = season BBM projections Excel (passed as ``projections_df`` to ``OptimizeLineup``).
    """
    content_type = request.headers.get("content-type", "").lower()
    bbm_df: Optional[pd.DataFrame] = None
    if "multipart/form-data" in content_type:
        form = await request.form()
        data_raw = form.get("data")
        if data_raw is None:
            raise HTTPException(
                status_code=422,
                detail="multipart requests must include a form field 'data' containing JSON for OptimizeBody",
            )
        if isinstance(data_raw, bytes):
            data_raw = data_raw.decode("utf-8")
        elif not isinstance(data_raw, str):
            data_raw = str(data_raw)
        body = OptimizeBody.model_validate_json(data_raw)
        up = form.get("bbm_file")
        if up is not None and hasattr(up, "read"):
            raw = await up.read()
            if raw:
                bbm_df = _read_excel_bytes(raw)
    else:
        try:
            payload = await request.json()
        except Exception as e:
            raise HTTPException(status_code=422, detail="Request body must be valid JSON for OptimizeBody") from e
        body = OptimizeBody.model_validate(payload)

    try:
        opt = OptimizeLineup(
            exclude_players=body.exclude_players,
            games_per_week=body.games_per_week,
            initial_budget=body.initial_budget,
            year=body.year,
            roster_size=body.roster_size,
            minimum_value_players=body.minimum_value_players,
            favorite_team=body.favorite_team,
            favorite_team_representation=body.favorite_team_representation,
            minimum_game_threshold=body.minimum_game_threshold,
            value_col=body.value_col,
            projections_df=bbm_df,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    for p in body.draft_picks:
        opt.draft_player(p.name, p.bid)

    if body.categories:
        opt.set_requirements(body.categories, percentile=body.percentile)

    try:
        results = opt.optimize_roster(body.stat_to_maximize)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return _df_records(results)


class MultiplePlansBody(BaseModel):
    n_plans: int = 20
    base_excluded: Optional[List[str]] = None
    base_percentile: float = 0.80
    percentiles_cycle: Optional[List[float]] = None
    categories: List[str] = Field(default_factory=lambda: ["PTS", "REB", "STL", "BLK", "AST"])
    value_col: str = "Value"
    year: Optional[int] = None
    roster_size: int = 13
    favorite_team: str = "CLE"
    minimum_game_threshold: float = 55
    initial_budget: float = 200
    sort_primary: str = "Price"
    out_prefix: str = "draft_plan_"
    objective_focus: str = "3PM"


@app.post("/optimizer/multiple-plans")
def optimizer_multiple_plans(body: MultiplePlansBody) -> List[dict[str, Any]]:
    pct_cycle = body.percentiles_cycle
    if pct_cycle is None:
        pct_cycle = (0.78, 0.80, 0.82, 0.84, 0.86)
    try:
        summary = generate_multiple_plans(
            n_plans=body.n_plans,
            base_excluded=body.base_excluded,
            base_percentile=body.base_percentile,
            percentiles_cycle=tuple(pct_cycle),
            categories=tuple(body.categories),
            value_col=body.value_col,
            year=body.year,
            roster_size=body.roster_size,
            favorite_team=body.favorite_team,
            minimum_game_threshold=body.minimum_game_threshold,
            initial_budget=body.initial_budget,
            sort_primary=body.sort_primary,
            out_prefix=body.out_prefix,
            objective_focus=body.objective_focus,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return _df_records(summary)


@app.get("/projected-scoreboard")
def projected_scoreboard(
    week_end_date: Optional[str] = None,
    current_matchup_period: Optional[int] = None,
    projections: str = "BBM",
) -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(
        feed.get_projected_scoreboard(
            h,
            week_end_date=week_end_date,
            current_matchup_period=current_matchup_period,
            projections=projections,
            bbm_df=None,
        )
    )


@app.post("/projected-scoreboard")
async def projected_scoreboard_upload(request: Request) -> List[dict[str, Any]]:
    """
    Same output as GET /projected-scoreboard, but accepts multipart form:
    - `data`: JSON string with keys: current_matchup_period (int), projections (str), optional week_end_date (str)
    - `bbm_file`: optional Excel upload (used when projections is BBM)
    """
    import json as _json

    h = _handles()
    form = await request.form()
    data_raw = form.get("data")
    if data_raw is None:
        raise HTTPException(
            status_code=422,
            detail="multipart form must include `data` (JSON string) with at least current_matchup_period",
        )
    if isinstance(data_raw, bytes):
        data_raw = data_raw.decode("utf-8")
    payload = _json.loads(str(data_raw))
    week_end_date = payload.get("week_end_date")
    current_matchup_period = payload.get("current_matchup_period")
    projections = payload.get("projections", "BBM")

    bbm_df = None
    up = form.get("bbm_file")
    if up is not None and hasattr(up, "read"):
        raw = await up.read()
        if raw:
            bbm_df = _read_excel_bytes(raw)

    try:
        return _df_records(
            feed.get_projected_scoreboard(
                h,
                week_end_date=week_end_date,
                current_matchup_period=current_matchup_period,
                projections=projections,
                bbm_df=bbm_df,
            )
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
