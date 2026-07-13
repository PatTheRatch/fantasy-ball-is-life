"""Playoff bracket context: round naming, advancement, and next-round pairing.

Derived entirely from league settings (`reg_season_count`, `playoff_team_count`,
`playoff_matchup_period_length`) and the current week's canonical matchups --
no hardcoded week numbers or bracket assumptions beyond a standard
single-elimination format.
"""
from __future__ import annotations

import math
import re
from typing import Any, Callable, Optional


def _slug(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")
    return text or "unknown"


def playoff_round(
    *,
    week: int,
    reg_season_count: Optional[int],
    playoff_team_count: Optional[int],
    playoff_matchup_period_length: Optional[int],
) -> Optional[dict[str, Any]]:
    """Which playoff round `week` falls in, or None outside the playoffs.

    Round names count backward from the final: the last round is always
    "Championship", the one before it "Semifinals", the one before that
    "Quarterfinals"; anything earlier falls back to "Round N". Total rounds
    are derived from `playoff_team_count` assuming a standard bracket
    (ceil(log2(playoff_team_count))).
    """
    if not reg_season_count or not playoff_team_count or playoff_team_count < 2:
        return None
    if week <= reg_season_count:
        return None

    period_length = max(1, int(playoff_matchup_period_length or 1))
    playoff_start_week = reg_season_count + 1
    round_index0 = (week - playoff_start_week) // period_length
    total_rounds = max(1, math.ceil(math.log2(playoff_team_count)))
    if round_index0 >= total_rounds:
        return None  # past the bracket -- e.g. a consolation/placement week

    rounds_from_final = total_rounds - 1 - round_index0
    if rounds_from_final == 0:
        label = "Championship"
    elif rounds_from_final == 1:
        label = "Semifinals"
    elif rounds_from_final == 2:
        label = "Quarterfinals"
    else:
        label = f"Round {round_index0 + 1}"

    return {
        "round_label": label,
        "round_index": round_index0 + 1,
        "total_rounds": total_rounds,
        "is_championship": rounds_from_final == 0,
        "next_round_week": week + period_length,
    }


def playoff_advancement(
    matchups: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """(advancing_teams, eliminated_teams) from this week's decided matchups."""
    advancing: list[str] = []
    eliminated: list[str] = []
    for matchup in matchups:
        winner = matchup.get("winner")
        home = matchup.get("home_team")
        away = matchup.get("away_team")
        if not winner or winner == "Tie":
            continue
        loser = away if winner == home else home
        advancing.append(winner)
        eliminated.append(loser)
    return advancing, eliminated


def next_round_matchups(
    *,
    week: int,
    next_round_week: int,
    advancing_teams: list[str],
    schedule_loader: Callable[[], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Next round's pairings, sourced from ESPN's own schedule -- only when
    every advancing team appears in it as a distinct participant. Returns []
    rather than guessing when the bracket isn't resolved in the schedule yet
    (or the schedule call fails)."""
    if not advancing_teams:
        return []
    try:
        schedule_rows = schedule_loader()
    except Exception:
        return []

    pairs: dict[frozenset, tuple[str, str]] = {}
    for row in schedule_rows:
        try:
            if int(row.get("Week", -1)) != next_round_week:
                continue
        except (TypeError, ValueError):
            continue
        team = str(row.get("Team") or "")
        opponent = str(row.get("Opponent") or "")
        if not team or not opponent or team == opponent:
            continue
        pairs.setdefault(frozenset({team, opponent}), (team, opponent))

    advancing_set = set(advancing_teams)
    paired_teams = {team for pair in pairs for team in pair}
    if not advancing_set.issubset(paired_teams):
        return []  # bracket not resolved in the schedule yet

    matchups: list[dict[str, Any]] = []
    for pair_key, (a, b) in pairs.items():
        if not pair_key.issubset(advancing_set):
            continue
        home, away = sorted((a, b))
        matchups.append(
            {
                "evidence_id": f"week-{week}:next-round:{_slug(home)}-vs-{_slug(away)}",
                "home_team": home,
                "away_team": away,
            }
        )
    return matchups
