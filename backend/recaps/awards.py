"""Deterministic weekly award selection from canonical recap facts."""
from __future__ import annotations

from collections import Counter
from typing import Any

from backend.commentary.schemas import WeeklyFactSnapshot


def _candidate(
    award_id: str,
    title: str,
    winner: str,
    evidence_ids: list[str],
    **facts: Any,
) -> dict[str, Any]:
    return {
        "award_id": award_id,
        "title": title,
        "winner": winner,
        "evidence_ids": evidence_ids,
        "facts": facts,
    }


def select_awards(snapshot: WeeklyFactSnapshot) -> list[dict[str, Any]]:
    awards: list[dict[str, Any]] = []
    matchups = snapshot.matchups

    decided = [item for item in matchups if item["winner"] != "Tie"]
    if decided:
        team_of_week = max(
            decided,
            key=lambda item: max(
                item["home_category_wins"], item["away_category_wins"]
            ),
        )
        wins = max(
            team_of_week["home_category_wins"],
            team_of_week["away_category_wins"],
        )
        awards.append(
            _candidate(
                "team-of-the-week",
                "Team of the Week",
                team_of_week["winner"],
                [team_of_week["evidence_id"]],
                category_wins=wins,
            )
        )

        margins = [
            (
                abs(item["home_category_wins"] - item["away_category_wins"]),
                item,
            )
            for item in decided
        ]
        blowout_margin, blowout = max(margins, key=lambda pair: pair[0])
        awards.append(
            _candidate(
                "blowout-of-the-week",
                "Blowout of the Week",
                blowout["winner"],
                [blowout["evidence_id"]],
                margin=blowout_margin,
                opponent=(
                    blowout["away_team"]
                    if blowout["winner"] == blowout["home_team"]
                    else blowout["home_team"]
                ),
            )
        )
        photo_margin, photo = min(margins, key=lambda pair: pair[0])
        awards.append(
            _candidate(
                "photo-finish",
                "Photo Finish",
                photo["winner"],
                [photo["evidence_id"]],
                margin=photo_margin,
                opponent=(
                    photo["away_team"]
                    if photo["winner"] == photo["home_team"]
                    else photo["home_team"]
                ),
            )
        )

    standings_rank = {
        str(row.get("team_name")): int(row.get("standing"))
        for row in snapshot.standings
        if row.get("team_name") and row.get("standing") is not None
    }
    upsets: list[tuple[int, dict[str, Any]]] = []
    for matchup in decided:
        winner = matchup["winner"]
        loser = (
            matchup["away_team"]
            if winner == matchup["home_team"]
            else matchup["home_team"]
        )
        winner_rank = standings_rank.get(winner)
        loser_rank = standings_rank.get(loser)
        if winner_rank and loser_rank and winner_rank > loser_rank:
            upsets.append((winner_rank - loser_rank, matchup))
    if upsets:
        rank_gap, upset = max(upsets, key=lambda pair: pair[0])
        awards.append(
            _candidate(
                "biggest-upset",
                "Biggest Upset",
                upset["winner"],
                [upset["evidence_id"]],
                rank_gap=rank_gap,
            )
        )

    luck_rows: list[tuple[float, str, str]] = []
    for row in snapshot.season_stats:
        team = row.get("Team") or row.get("team")
        ratio = row.get("Win % Ratio") or row.get("luck_ratio")
        try:
            luck_rows.append((float(ratio), str(team), str(row["evidence_id"])))
        except (TypeError, ValueError):
            continue
    if luck_rows:
        luckiest = max(luck_rows)
        unluckiest = min(luck_rows)
        awards.extend(
            [
                _candidate(
                    "luckiest-team",
                    "Luckiest Team",
                    luckiest[1],
                    [luckiest[2]],
                    luck_ratio=luckiest[0],
                ),
                _candidate(
                    "unluckiest-team",
                    "Unluckiest Team",
                    unluckiest[1],
                    [unluckiest[2]],
                    luck_ratio=unluckiest[0],
                ),
            ]
        )

    rising = [
        row
        for row in snapshot.power_rankings
        if isinstance(row.get("rank_change"), (int, float))
        and row["rank_change"] > 0
    ]
    falling = [
        row
        for row in snapshot.power_rankings
        if isinstance(row.get("rank_change"), (int, float))
        and row["rank_change"] < 0
    ]
    if rising:
        row = max(rising, key=lambda item: item["rank_change"])
        awards.append(
            _candidate(
                "stock-rising",
                "Stock Rising",
                str(row.get("team") or row.get("Team")),
                [row["evidence_id"]],
                places=int(row["rank_change"]),
            )
        )
    if falling:
        row = min(falling, key=lambda item: item["rank_change"])
        awards.append(
            _candidate(
                "falling-fast",
                "Falling Fast",
                str(row.get("team") or row.get("Team")),
                [row["evidence_id"]],
                places=abs(int(row["rank_change"])),
            )
        )

    transaction_counts = Counter(
        str(row.get("team_name"))
        for row in snapshot.transactions
        if row.get("team_name")
    )
    if transaction_counts:
        team, count = transaction_counts.most_common(1)[0]
        evidence = [
            row["evidence_id"]
            for row in snapshot.transactions
            if str(row.get("team_name")) == team
        ]
        awards.append(
            _candidate(
                "transaction-addict",
                "Transaction Addict",
                team,
                evidence,
                transaction_count=count,
            )
        )

    return awards
