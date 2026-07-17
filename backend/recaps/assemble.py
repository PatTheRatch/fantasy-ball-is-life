"""Build a canonical, evidence-addressable weekly fact snapshot.

P-3b: reads from league_state_snapshots (stored by the P-3a worker)
instead of calling ESPN live. force_fresh=True keeps the admin
live-pull path.
"""
from __future__ import annotations

import logging
import math
import re
import time
from typing import Any, Callable, Optional

from backend.api.routers import league as league_api
from backend.commentary.schemas import (
    DataQualityReport,
    PlayoffContext,
    WeeklyFactSnapshot,
)
from backend.league.scoreboard import WeeklyScoreboard
from backend.recaps import playoffs
from backend.recaps.store import RecapStore

STAT_ORDER = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]

def _slug(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return text or "unknown"


def _number(value: Any) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def canonical_matchups(scoreboard: list[dict[str, Any]], week: int) -> list[dict[str, Any]]:
    # ── Catalyst helpers ──────────────────────────────────────────────
    _CATALYST_COUNTING_STATS = {"PTS", "REB", "AST", "STL", "BLK", "3PM"}
    # Tolerate a 1.0-unit drift between the active-player sum and the
    # official category value (floating-point + roster-sync edge cases).
    _CATALYST_SANITY_TOLERANCE = 1.0

    def _catalyst_for_side(
        stat: str, side: str, row: dict[str, Any], official_value: Optional[float]
    ) -> Optional[dict[str, Any]]:
        """Return a catalyst dict for *side* if the data passes the sanity gate.
        Returns None when the gate fails or data is absent."""
        prefix = f"{side}_catalyst_"
        leader_name = row.get(f"{prefix}leader_name")
        leader_value = _number(row.get(f"{prefix}leader_value"))
        team_total = _number(row.get(f"{prefix}team_total"))
        if leader_name is None or leader_value is None or team_total is None:
            return None
        if official_value is None:
            return None
        if team_total <= 0:
            return None
        # Sanity gate: player-sum must match the official value closely.
        if abs(team_total - official_value) > _CATALYST_SANITY_TOLERANCE:
            return None
        share = leader_value / team_total
        shape = "carried" if share >= 0.50 else "team effort"
        return {
            "leader_name": leader_name,
            "leader_value": round(leader_value, 1),
            "team_total": round(team_total, 1),
            "share": round(share, 4),
            "shape": shape,
        }

    # ── Group rows by matchup ─────────────────────────────────────────
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in scoreboard:
        stat = str(row.get("stat") or "").upper()
        home = str(row.get("home_team") or "")
        away = str(row.get("away_team") or "")
        if stat not in STAT_ORDER or not home or not away:
            continue
        if home.lower() == "bye" or away.lower() == "bye":
            continue
        grouped.setdefault((home, away), []).append(row)

    matchups: list[dict[str, Any]] = []
    for (home, away), rows in grouped.items():
        matchup_id = f"week-{week}:{_slug(home)}-vs-{_slug(away)}"
        categories: list[dict[str, Any]] = []
        home_wins = away_wins = ties = 0
        # Collect potential catalysts across categories for notability selection.
        raw_catalysts: list[dict[str, Any]] = []

        for row in sorted(
            rows,
            key=lambda item: STAT_ORDER.index(str(item.get("stat")).upper()),
        ):
            stat = str(row["stat"]).upper()
            home_value = _number(row.get("current_home_score"))
            away_value = _number(row.get("current_away_score"))
            complete = home_value is not None and away_value is not None
            if not complete:
                winner = "unavailable"
            elif home_value == away_value:
                winner = "tie"
                ties += 1
            elif (stat == "TO" and home_value < away_value) or (
                stat != "TO" and home_value > away_value
            ):
                winner = "home"
                home_wins += 1
            else:
                winner = "away"
                away_wins += 1

            cat_entry: dict[str, Any] = {
                "evidence_id": f"{matchup_id}:category:{_slug(stat)}",
                "stat": stat,
                "home_value": home_value,
                "away_value": away_value,
                "winner": winner,
                "complete": complete,
            }
            # Catalyst: only for counting stats, only for the winning side.
            if stat in _CATALYST_COUNTING_STATS and winner in ("home", "away"):
                official_value = home_value if winner == "home" else away_value
                cat = _catalyst_for_side(stat, winner, row, official_value)
                if cat is not None:
                    # margin_ratio for notability: how close the category was.
                    max_val = max(home_value or 0, away_value or 0)
                    margin = abs((home_value or 0) - (away_value or 0))
                    margin_ratio = margin / max_val if max_val > 0 else 1.0
                    cat["stat"] = stat
                    cat["margin"] = round(margin, 1)
                    cat["margin_ratio"] = round(margin_ratio, 4)
                    raw_catalysts.append(cat)
                    cat_entry["catalyst"] = cat

            categories.append(cat_entry)

        # ── Notability selection: ≤2 catalysts per matchup ────────────
        # A category qualifies if decided AND (close OR concentrated).
        notable = [
            c for c in raw_catalysts
            if c.get("margin_ratio", 1.0) <= 0.10 or c.get("share", 0.0) >= 0.60
        ]
        # Sort: smallest margin_ratio first, tie-break by highest share.
        notable.sort(key=lambda c: (c.get("margin_ratio", 1.0), -c.get("share", 0.0)))
        selected_catalysts = notable[:2]

        tally_winner = (
            "home" if home_wins > away_wins else "away" if away_wins > home_wins else "tie"
        )
        # ESPN resolves a head-to-head category tie itself (e.g. a playoff
        # seeding tiebreak) -- our own tally has no notion of that rule, so
        # prefer ESPN's authoritative result when the two disagree on a tie.
        espn_winner = str(rows[0].get("espn_winner") or "").upper()
        if tally_winner == "tie" and espn_winner in ("HOME", "AWAY"):
            winner_side = espn_winner.lower()
            tiebreak_resolved = True
        else:
            winner_side = tally_winner
            tiebreak_resolved = False

        # ── GP: Games Played (None when league doesn't track it) ──────
        home_gp = rows[0].get("home_games_played")
        away_gp = rows[0].get("away_games_played")

        matchups.append(
            {
                "matchup_id": matchup_id,
                "evidence_id": matchup_id,
                "home_team": home,
                "away_team": away,
                "home_category_wins": home_wins,
                "away_category_wins": away_wins,
                "ties": ties,
                "winner": (
                    home if winner_side == "home" else away if winner_side == "away" else "Tie"
                ),
                "tiebreak_resolved": tiebreak_resolved,
                "categories": categories,
                "home_games_played": home_gp,
                "away_games_played": away_gp,
                "catalysts": selected_catalysts,
            }
        )
    return matchups


def _with_evidence(
    rows: list[dict[str, Any]], prefix: str, key: str
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        item = dict(row)
        identifier = item.get(key) or item.get("team_name") or item.get("Team") or index
        item["evidence_id"] = f"{prefix}:{_slug(identifier)}"
        output.append(item)
    return output


def _capture(
    name: str,
    loader: Callable[[], list[dict[str, Any]]],
    warnings: list[str],
) -> tuple[list[dict[str, Any]], bool]:
    started = time.perf_counter()
    try:
        return loader(), True
    except Exception as exc:
        warnings.append(f"{name} unavailable: {exc}")
        return [], False
    finally:
        logging.info(
            "recap assembly: %s took %.2fs", name, time.perf_counter() - started
        )



def _live_power_rankings(weeks_csv: str, recent_weeks: int = 3):
    """Compute power rankings from live ESPN (force_fresh path)."""
    import pandas as pd
    from backend.api.deps import _my_league, _scoreboard

    board = _scoreboard()
    all_weeks = sorted(set(int(w.strip()) for w in weeks_csv.split(",") if w.strip()))
    if not all_weeks:
        return []

    rw = max(1, recent_weeks)
    recent_list = all_weeks[-rw:]

    df_full = board.all_play(weeks=all_weeks)
    df_recent = board.all_play(weeks=recent_list)

    if df_full is None or df_full.empty or "Team" not in df_full.columns:
        return []

    for col in ["Total Win %", "Actual Win %"]:
        if col in df_full.columns:
            df_full[col] = pd.to_numeric(df_full[col], errors="coerce")
    if "Total Win %" in df_recent.columns:
        df_recent["Total Win %"] = pd.to_numeric(df_recent["Total Win %"], errors="coerce")

    stat_cols = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]
    stat_cols_avail = [c for c in stat_cols if c in df_full.columns]
    stats = df_full[["Team"] + stat_cols_avail].copy()
    for c in stat_cols_avail:
        stats[c] = pd.to_numeric(stats[c], errors="coerce")

    ranks = {}
    for c in stat_cols:
        if c not in stats.columns:
            continue
        ranks[c] = stats[c].rank(method="min", ascending=False).astype("Int64")

    rank_df = pd.DataFrame({"Team": stats["Team"]})
    for c, sr in ranks.items():
        rank_df[f"{c.lower().replace('%', '_pct')}_rank"] = sr

    top3 = pd.Series(0, index=rank_df.index, dtype="int")
    denom = 0
    for c in stat_cols:
        key = f"{c.lower().replace('%', '_pct')}_rank"
        if key in rank_df.columns:
            denom += 1
            top3 += (pd.to_numeric(rank_df[key], errors="coerce").fillna(999) <= 3).astype(int)
    dominance = (top3 / float(denom or 9)).astype(float)

    base = df_full[["Team", "Total Win %", "Actual Win %"]].copy()
    base = base.rename(columns={"Total Win %": "allplay_win_pct", "Actual Win %": "actual_win_pct"})
    recent = df_recent[["Team", "Total Win %"]].copy().rename(columns={"Total Win %": "recent_allplay_win_pct"})

    out = base.merge(recent, on="Team", how="left").merge(rank_df, on="Team", how="left")
    out["category_dominance_score"] = dominance.values

    out["composite_score"] = (
        0.35 * (pd.to_numeric(out["allplay_win_pct"], errors="coerce").fillna(0) / 100.0)
        + 0.35 * (pd.to_numeric(out["recent_allplay_win_pct"], errors="coerce").fillna(0) / 100.0)
        + 0.20 * (pd.to_numeric(out["actual_win_pct"], errors="coerce").fillna(0) / 100.0)
        + 0.10 * (pd.to_numeric(out["category_dominance_score"], errors="coerce").fillna(0))
    )

    out = out.sort_values("composite_score", ascending=False).reset_index(drop=True)
    out["Rank"] = out.index + 1

    ml = _my_league()
    records = {}
    for t in ml.teams:
        tn = str(getattr(t, "team_name", getattr(t, "team_id", "")))
        records[tn] = {
            "wins": getattr(t, "wins", 0),
            "losses": getattr(t, "losses", 0),
            "ties": getattr(t, "ties", 0),
        }

    result = []
    for _, row in out.iterrows():
        team = str(row["Team"])
        rec = records.get(team, {"wins": 0, "losses": 0, "ties": 0})
        entry = {
            "Team": team,
            "Rank": int(row["Rank"]),
            "Score": round(float(row["composite_score"]), 4),
            "RecentScore": round(float(row.get("recent_allplay_win_pct", 0) or 0), 2),
            "wins": rec["wins"],
            "losses": rec["losses"],
            "ties": rec["ties"],
        }
        for c in stat_cols:
            key = f"{c.lower().replace('%', '_pct')}_rank"
            if key in row.index:
                entry[f"{c}_rank"] = int(row[key]) if pd.notna(row[key]) else None
        result.append(entry)

    if len(all_weeks) >= 2:
        prev_weeks = all_weeks[:-1]
        df_prev = board.all_play(weeks=prev_weeks)
        if df_prev is not None and not df_prev.empty and "Team" in df_prev.columns:
            df_prev["composite"] = pd.to_numeric(
                df_prev.get("Total Win %", 0), errors="coerce"
            ).fillna(0)
            df_prev = df_prev.sort_values("composite", ascending=False).reset_index(drop=True)
            df_prev["PriorRank"] = df_prev.index + 1
            prior_map = dict(zip(df_prev["Team"].astype(str), df_prev["PriorRank"]))
            for entry in result:
                cur = entry["Rank"]
                prev = prior_map.get(entry["Team"])
                entry["PriorRank"] = prev
                entry["Movement"] = int(prev) - int(cur) if prev is not None else 0

    return result


def assemble_weekly_snapshot(
    *,
    league: dict[str, Any],
    season: int,
    week: int,
    week_start: str,
    week_end: str,
    force_fresh: bool = False,
) -> WeeklyFactSnapshot:
    """Collect facts server-side.

    Default (P-3b): reads from league_state_snapshots (stale but fast,
    never a 500).  ``force_fresh=True`` (admin generate) pulls live ESPN
    first — the one user allowed to wait.
    """
    assembly_started = time.perf_counter()

    warnings: list[str] = []

    if not force_fresh:
        # ── P-3b: read from stored snapshots ──────────────────────────────
        store = RecapStore()
        phases = store.get_all_phases(league_id=league["id"], season=season)

        stored_standings = phases.get("standings", {}).get("payload_json", [])
        standings: list[dict[str, Any]] = []
        standings_ok = bool(stored_standings)
        if standings_ok:
            for row in stored_standings:
                standings.append({
                    "team_name": row.get("team_name", row.get("Team", "")),
                    "team_id": row.get("team_id", _slug(row.get("team_name", row.get("Team", "")))),
                    "wins": row.get("wins", 0),
                    "losses": row.get("losses", 0),
                    "ties": row.get("ties", 0),
                    "win_pct": row.get("win_pct", row.get("win%", 0.0)),
                })
            standings.sort(key=lambda r: (-float(r.get("win_pct", 0) or 0), -int(r.get("wins", 0))))
            for i_s, s in enumerate(standings):
                s["standing"] = i_s + 1

        rankings = phases.get("power_rankings", {}).get("payload_json", []) or []
        rankings_ok = bool(rankings)

        single_week_all_play: list[dict[str, Any]] = []

        scoreboard = phases.get("scoreboard", {}).get("payload_json", []) or []
        scoreboard_ok = bool(scoreboard)

        transactions = phases.get("transactions", {}).get("payload_json", []) or []
        transactions_ok = bool(transactions)

        season_stats = phases.get("season_stats", {}).get("payload_json", []) or []
        season_stats_ok = bool(season_stats)

        fetched_ats = [p.get("fetched_at") for p in phases.values()]
        logging.info(
            "recap assembly: snapshot read for %s (fetched_at=%s)",
            league["id"], max(f for f in fetched_ats if f) if any(fetched_ats) else None,
        )

        del phases, store
    else:
        # ── force_fresh: pull live ESPN (admin flow, slow) ─────────────────
        weeks_csv = ",".join(str(v) for v in range(1, week + 1))

        standings, standings_ok = _build_scoped_standings(league_api, week, warnings)
        rankings, rankings_ok = _capture(
            "Power rankings",
            lambda: _live_power_rankings(weeks_csv, recent_weeks=3),
            warnings,
        )
        single_week_all_play = _build_single_week_ap(league_api, week)
        scoreboard, scoreboard_ok = _capture(
            "Matchups",
            lambda: league_api.scoreboard_current(scoring_period=week),
            warnings,
        )
        transactions, transactions_ok = _capture(
            "Transactions",
            lambda: league_api.transactions_week(scoring_period=week),
            warnings,
        )
        season_stats, season_stats_ok = _capture(
            "Season statistics",
            lambda: league_api.season_stats(weeks=weeks_csv),
            warnings,
        )

    matchups = canonical_matchups(scoreboard, week)
    complete_categories = bool(matchups) and all(
        len(matchup["categories"]) == len(STAT_ORDER)
        and {category["stat"] for category in matchup["categories"]}
        == set(STAT_ORDER)
        and all(category["complete"] for category in matchup["categories"])
        for matchup in matchups
    )
    if not matchups:
        warnings.append("No completed matchup data was found for this week.")
    elif not complete_categories:
        warnings.append("One or more matchups do not contain all nine categories.")
    if not standings_ok or not standings:
        warnings.append("Standings data is empty.")
    if not rankings_ok or not rankings:
        warnings.append("Power-ranking data is empty.")
    if not season_stats:
        warnings.append("Season statistics are empty.")
    if not transactions_ok:
        warnings.append(
            "Transaction-dependent awards are disabled; counts may be omitted."
        )

    checks = {
        "matchups_available": scoreboard_ok and bool(matchups),
        "all_nine_categories": complete_categories,
        "standings_available": standings_ok and bool(standings),
        "power_rankings_available": rankings_ok and bool(rankings),
        "prior_week_comparison": week == 1
        or any("rank_change" in row for row in rankings),
        "transactions_available": transactions_ok,
        "season_stats_available": season_stats_ok and bool(season_stats),
    }
    if week > 1 and not checks["prior_week_comparison"]:
        warnings.append("Prior-week ranking comparison is unavailable.")

    ranking_facts = _with_evidence(rankings, "ranking", "team")
    for row in ranking_facts:
        row["team_id"] = _slug(row.get("team") or row.get("Team"))

    playoff_started = time.perf_counter()
    playoff_context = _build_playoff_context(week, matchups, standings, warnings)
    logging.info(
        "recap assembly: playoff_context took %.2fs", time.perf_counter() - playoff_started
    )

    # F2-6: annotate standings with in_playoffs flag.
    _annotate_standings_playoffs(standings)

    snapshot = WeeklyFactSnapshot(
        league={
            "id": league["id"],
            "slug": league["slug"],
            "name": league["name"],
            "recap_voice": league.get("recap_voice"),
        },
        season=season,
        week=week,
        week_dates={"start": week_start, "end": week_end},
        matchups=matchups,
        standings=_with_evidence(standings, "standing", "team_id"),
        power_rankings=ranking_facts,
        transactions=_with_evidence(transactions, "transaction", "activity_id"),
        season_stats=_with_evidence(season_stats, "season-stat", "Team"),
        award_candidates=[],
        data_quality=DataQualityReport(
            ready=all(checks.values()),
            warnings=list(dict.fromkeys(warnings)),
            checks=checks,
            transaction_quality="counts_only" if transactions_ok else "unavailable",
        ),
        playoff_context=playoff_context,
    )

    # F2-5: compute deterministic awards from the assembled snapshot so
    # award_candidates is always populated (even pre-generation).  The AI
    # explanation line stays gated on a published recap.
    from backend.recaps.awards import select_awards

    # FIX-A: single-week all-play for Team of the Week.
    # WeeklyFactSnapshot is a Pydantic model — use object.__setattr__
    # for fields not declared in the model.
    object.__setattr__(snapshot, "single_week_all_play", single_week_all_play)
    snapshot.award_candidates = select_awards(snapshot)

    # Cache the result so the follow-up generate request reuses this assembly.
    # Only cache when the data is actually ready — a degraded snapshot from a
    # transient ESPN blip should not block recovery for the full TTL.
    logging.info(
        "recap assembly: total %.2fs for %s", time.perf_counter() - assembly_started, ck
    )
    return snapshot


def _championship_split(
    standings: list[dict[str, Any]], playoff_team_count: Optional[int]
) -> tuple[list[str], list[str]]:
    """(championship_teams, consolation_teams) by ESPN playoff seed.

    ``standing`` in the snapshot is ESPN's ``playoffSeed``: seeds
    ``1..playoff_team_count`` made the real playoffs; the rest are the
    consolation bracket. Both lists are ordered by seed."""
    if not playoff_team_count:
        return [], []
    seeded = []
    for row in standings:
        seed = row.get("standing")
        name = row.get("team_name") or row.get("Team")
        if seed is None or not name:
            continue
        seeded.append((int(seed), str(name)))
    seeded.sort()
    championship = [name for seed, name in seeded if seed <= playoff_team_count]
    consolation = [name for seed, name in seeded if seed > playoff_team_count]
    return championship, consolation



def _annotate_standings_playoffs(standings: list[dict[str, Any]]) -> None:
    """F2-6: tag each standings row with in_playoffs (True/False).

    Uses the standings'' standing'' (ESPN playoffSeed) field — seeds
    1..playoff_team_count made the real playoffs.  playoff_team_count
    is read from the live league settings (fetches independently
    so this helper works standalone; the assembly path still calls
    _build_playoff_context for the rich playoff-context data).

    Mutates standings rows in place so the field round-trips through
    the JSON store (a new scalar on the snapshot would silently drop).
    """
    for row in standings:
        row["in_playoffs"] = False  # default
    try:
        settings = league_api.league_settings()
        ptc = settings.get("playoff_team_count")
        if ptc:
            ptc = int(ptc)
            for row in standings:
                seed = row.get("standing")
                if seed is not None:
                    row["in_playoffs"] = int(seed) <= ptc
    except Exception:
        pass  # settings unavailable — all rows stay False


def _build_playoff_context(
    week: int,
    matchups: list[dict[str, Any]],
    standings: list[dict[str, Any]],
    warnings: list[str],
) -> Optional[PlayoffContext]:
    """None for a regular-season week or when settings/round derivation fail --
    playoff context is additive and must never block generation."""
    try:
        settings = league_api.league_settings()
    except Exception as exc:
        warnings.append(f"League settings unavailable: {exc}")
        return None

    round_info = playoffs.playoff_round(
        week=week,
        reg_season_count=settings.get("reg_season_count"),
        playoff_team_count=settings.get("playoff_team_count"),
        playoff_matchup_period_length=settings.get("playoff_matchup_period_length"),
    )
    if round_info is None:
        return None

    championship_teams, consolation_teams = _championship_split(
        standings, settings.get("playoff_team_count")
    )

    # A playoff seed only says who STARTED in the real bracket -- half the
    # field loses every round after that and drops to playing for final
    # positioning, not the title, even though it's still an "in the playoffs"
    # matchup. Replay the bracket's completed rounds to find who's actually
    # still alive for the championship this week.
    reg_season_count = settings.get("reg_season_count")
    still_alive, eliminated_from_title = playoffs.replay_championship_bracket(
        current_week=week,
        playoff_start_week=(int(reg_season_count) + 1) if reg_season_count else week,
        period_length=settings.get("playoff_matchup_period_length") or 1,
        championship_teams=championship_teams,
        matchups_loader=lambda w: canonical_matchups(
            league_api.scoreboard_current(scoring_period=w), w
        ),
    )

    # Tag each playoff matchup: championship (both teams still alive for the
    # title), placement (both made the real playoffs but at least one already
    # lost a bracket game -- playing for final positioning now), or
    # consolation (either team never made the real playoffs at all).
    alive_set = set(still_alive)
    champ_set = set(championship_teams)
    for matchup in matchups:
        home = matchup.get("home_team")
        away = matchup.get("away_team")
        if home in alive_set and away in alive_set:
            matchup["bracket"] = "championship"
        elif home in champ_set and away in champ_set:
            matchup["bracket"] = "placement"
        else:
            matchup["bracket"] = "consolation"

    advancing, eliminated = playoffs.playoff_advancement(matchups)
    next_matchups: list[dict[str, Any]] = []
    if not round_info["is_championship"]:
        next_matchups = playoffs.next_round_matchups(
            week=week,
            next_round_week=round_info["next_round_week"],
            advancing_teams=advancing,
            schedule_loader=league_api.my_league_schedule,
        )

    return PlayoffContext(
        round_label=round_info["round_label"],
        round_index=round_info["round_index"],
        total_rounds=round_info["total_rounds"],
        is_championship=round_info["is_championship"],
        advancing_teams=advancing,
        eliminated_teams=eliminated,
        championship_teams=championship_teams,
        consolation_teams=consolation_teams,
        still_alive_for_title=still_alive,
        eliminated_from_title=eliminated_from_title,
        next_round_matchups=next_matchups,
    )


# ── FIX-B: week-scoped standings from matchups ────────────────────────


def _build_scoped_standings(league_api, week, warnings):
    """Build week-scoped standings: aggregate wins/losses from matchups
    across weeks 1..week.  win_pct is 0–100 (matches allplay_win_pct)."""
    from collections import defaultdict
    records: dict[str, dict] = defaultdict(lambda: {"wins": 0, "losses": 0, "ties": 0})

    for w in range(1, week + 1):
        try:
            matchups = canonical_matchups(
                league_api.scoreboard_current(scoring_period=w), w
            )
        except Exception:
            continue
        for m in matchups:
            winner = m.get("winner", "")
            for side in ("home", "away"):
                team = m.get(f"{side}_team", "")
                if not team:
                    continue
                if winner == team:
                    records[team]["wins"] += 1
                elif winner == "Tie" or not winner:
                    records[team]["ties"] += 1
                else:
                    records[team]["losses"] += 1

    if not records:
        return [], False

    rows = []
    for team, rec in records.items():
        total = rec["wins"] + rec["losses"] + rec["ties"]
        wp = (rec["wins"] / total * 100) if total > 0 else 0.0
        rows.append({"team_name": team, "wins": rec["wins"],
                      "losses": rec["losses"], "ties": rec["ties"],
                      "win_pct": round(wp, 1)})
    rows.sort(key=lambda r: (-r["win_pct"], -r["wins"]))
    for i, r in enumerate(rows):
        r["standing"] = i + 1
    return rows, True


def _build_single_week_ap(league_api, week):
    """FIX-A: single-week all-play for Team of the Week.

    Returns list of {Team, Matchup Wins, Total Wins} — enough for
    select_awards to pick the field-wide winner."""
    try:
        matchups = canonical_matchups(
            league_api.scoreboard_current(scoring_period=week), week
        )
    except Exception:
        return []
    if not matchups:
        return []
    from backend.league.scoreboard import _single_week_all_play
    return _single_week_all_play(matchups)
