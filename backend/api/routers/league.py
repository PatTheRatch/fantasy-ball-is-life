"""League / standings / rosters / scoreboard endpoints."""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, List, Optional

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.encoders import jsonable_encoder

from backend.api.deps import (
    _df_records,
    _espn_http_exception,
    _handles,
    _my_league,
    _read_excel_bytes,
)
from backend.league import data_feed as feed

router = APIRouter(tags=["league"])


def _validate_week_range(week_start_date: Optional[str], week_end_date: Optional[str]) -> None:
    """Reject an explicitly inverted roster date window with a 400.

    Only validates when the caller supplies both bounds; when either is omitted
    the data layer derives a sane window from the matchup period.
    """
    if not week_start_date or not week_end_date:
        return
    try:
        start = pd.to_datetime(week_start_date)
        end = pd.to_datetime(week_end_date)
    except (ValueError, TypeError) as e:
        raise HTTPException(
            status_code=422,
            detail="week_start_date/week_end_date must be valid dates (YYYY-MM-DD).",
        ) from e
    if start > end:
        raise HTTPException(
            status_code=400,
            detail=f"week_start_date ({week_start_date}) must be on or before week_end_date ({week_end_date}).",
        )

@router.get("/league/meta")
def league_meta() -> dict[str, Any]:
    try:
        h = _handles()
        return feed.pull_league_meta(h)
    except Exception as e:
        raise _espn_http_exception(e) from e


@router.get("/league/my-league/schedule")
def my_league_schedule(
    year: Optional[int] = Query(None, description="ESPN season year; defaults to config SEASON"),
) -> List[dict[str, Any]]:
    try:
        ml = _my_league(year)
        return _df_records(ml.get_schedule())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/league/my-league/current-week-matchups")
def my_league_current_week_matchups(
    year: Optional[int] = Query(None, description="ESPN season year; defaults to config SEASON"),
) -> List[dict[str, Any]]:
    try:
        ml = _my_league(year)
        return _df_records(ml.get_current_week_matchups())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/power-rankings")
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
            _t0 = time.perf_counter()
            df_full = ml.get_universe_wins(weeks=all_weeks)
            _t1 = time.perf_counter()
            df_recent = ml.get_universe_wins(weeks=recent_list)
            logging.info(
                "power_rankings: get_universe_wins(full=%d weeks) took %.2fs, "
                "get_universe_wins(recent=%d weeks) took %.2fs",
                len(all_weeks), _t1 - _t0, len(recent_list), time.perf_counter() - _t1,
            )

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
            _t2 = time.perf_counter()
            df_full_prev = ml.get_universe_wins(weeks=prev_weeks)
            _t3 = time.perf_counter()
            df_recent_prev = ml.get_universe_wins(weeks=prev_recent)
            logging.info(
                "power_rankings: rank-change get_universe_wins(full=%d weeks) took %.2fs, "
                "get_universe_wins(recent=%d weeks) took %.2fs",
                len(prev_weeks), _t3 - _t2, len(prev_recent), time.perf_counter() - _t3,
            )

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


@router.get("/confidence")
def confidence(
    projected_value: float = Query(..., description="Projected stat value to evaluate"),
    stat: str = Query(..., description="Stat name (e.g. PTS, REB, TO, FG%, FT%)"),
    player_avg: float = Query(..., description="Player season average for the stat (used for tier lookup)"),
) -> dict[str, Any]:
    try:
        from backend.analytics.consistency import get_confidence

        return get_confidence(
            projected_value=projected_value,
            stat=stat,
            player_avg=player_avg,
            db_path="data/game_logs.db",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/matchup-confidence")
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
        from backend.analytics.consistency import get_confidence

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
                        # TO is a natural positive count; abs() defends against any
                        # legacy negative encoding so the confidence model always
                        # sees positive turnover counts for LOWER_IS_BETTER handling.
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


@router.get("/league/teams")
def league_teams() -> List[dict[str, Any]]:
    try:
        h = _handles()
        return _df_records(feed.teams_df(h))
    except Exception as e:
        raise _espn_http_exception(e) from e


@router.get("/league/standings")
def league_standings() -> List[dict[str, Any]]:
    try:
        h = _handles()
        return _df_records(feed.standings_df(h))
    except Exception as e:
        raise _espn_http_exception(e) from e


@router.get("/league/settings")
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


@router.get("/season-stats")
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


@router.get("/rosters/{on_date}")
def rosters_on_date(on_date: date) -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(feed.rosters_df(h, on_date))


@router.get("/transactions")
def transactions(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD"),
) -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(feed.transactions_df(h, start=start, end=end))


@router.get("/transactions/week")
def transactions_week(
    scoring_period: int = Query(..., description="Matchup week / scoring period (one ESPN scoringPeriodId == one week)"),
) -> List[dict[str, Any]]:
    """Executed player-movement transactions (adds/drops + completed trades) for
    a single matchup week, via the ``mTransactions2`` adapter. This is the
    recap-facing path; unlike the legacy date-range ``/transactions`` it is not
    projection-dependent and does not rely on the broken communication feed."""
    try:
        h = _handles()
        return feed.week_transactions(h, scoring_period=scoring_period)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {e}") from e


@router.get("/matchups")
def matchups(scoring_period: Optional[int] = None) -> List[dict[str, Any]]:
    h = _handles()
    return _df_records(feed.matchups_df(h, scoring_period=scoring_period))


@router.get("/scoreboard/current")
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


@router.get("/rosters/current")
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
    _validate_week_range(week_start_date, week_end_date)
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


@router.post("/rosters/current")
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
    _validate_week_range(week_start_date, week_end_date)
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


@router.get("/projected-scoreboard")
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


@router.post("/projected-scoreboard")
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
