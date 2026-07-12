"""Build a canonical, evidence-addressable weekly fact snapshot."""
from __future__ import annotations

import math
import re
from typing import Any, Callable, Optional

from backend.api.routers import league as league_api
from backend.commentary.schemas import DataQualityReport, WeeklyFactSnapshot

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
            categories.append(
                {
                    "evidence_id": f"{matchup_id}:category:{_slug(stat)}",
                    "stat": stat,
                    "home_value": home_value,
                    "away_value": away_value,
                    "winner": winner,
                    "complete": complete,
                }
            )

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
                    home if home_wins > away_wins else away if away_wins > home_wins else "Tie"
                ),
                "categories": categories,
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
    try:
        return loader(), True
    except Exception as exc:
        warnings.append(f"{name} unavailable: {exc}")
        return [], False


def assemble_weekly_snapshot(
    *,
    league: dict[str, Any],
    season: int,
    week: int,
    week_start: str,
    week_end: str,
) -> WeeklyFactSnapshot:
    """Collect facts server-side; callers provide only the selected week/date window."""
    warnings: list[str] = []
    weeks_csv = ",".join(str(value) for value in range(1, week + 1))

    standings, standings_ok = _capture(
        "Standings", league_api.league_standings, warnings
    )
    rankings, rankings_ok = _capture(
        "Power rankings",
        lambda: league_api.power_rankings(weeks=weeks_csv, recent_weeks=3),
        warnings,
    )
    scoreboard, scoreboard_ok = _capture(
        "Matchups",
        lambda: league_api.scoreboard_current(scoring_period=week),
        warnings,
    )
    transactions, transactions_ok = _capture(
        "Transactions",
        lambda: league_api.transactions(start=week_start, end=week_end),
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
    if not standings:
        warnings.append("Standings data is empty.")
    if not rankings:
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

    return WeeklyFactSnapshot(
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
    )
