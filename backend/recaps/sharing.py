"""WhatsApp-friendly recap formatters using deterministic facts + AI narrative."""
from __future__ import annotations

from urllib.parse import urlencode

from backend import config
from backend.commentary.schemas import RecapGeneratedContent, WeeklyFactSnapshot


def _public_url(snapshot: WeeklyFactSnapshot) -> str:
    query = urlencode({"season": snapshot.season, "week": snapshot.week})
    return f"{config.PUBLIC_APP_URL}/recap?{query}"


def format_share_text(
    snapshot: WeeklyFactSnapshot,
    content: RecapGeneratedContent,
) -> RecapGeneratedContent:
    takeaway_by_id = {
        item.matchup_id: item.text for item in content.matchup_takeaways
    }
    award_by_id = {
        item.award_id: item.text for item in content.award_explanations
    }

    matchup_lines = []
    for matchup in snapshot.matchups:
        result = (
            f"{matchup['home_team']} {matchup['home_category_wins']}–"
            f"{matchup['away_category_wins']} {matchup['away_team']}"
        )
        takeaway = takeaway_by_id.get(matchup["matchup_id"])
        matchup_lines.append(f"• {result}" + (f" — {takeaway}" if takeaway else ""))

    mover_lines = []
    for row in snapshot.power_rankings:
        change = row.get("rank_change")
        if not isinstance(change, (int, float)) or change == 0:
            continue
        team = row.get("team") or row.get("Team")
        direction = f"▲{int(change)}" if change > 0 else f"▼{abs(int(change))}"
        mover_lines.append(f"• {team} {direction} to #{row.get('rank')}")

    award_lines = []
    for award in snapshot.award_candidates:
        explanation = award_by_id.get(award["award_id"])
        line = f"• {award['title']}: {award['winner']}"
        award_lines.append(line + (f" — {explanation}" if explanation else ""))

    url = _public_url(snapshot)
    summary_parts = [
        f"*{content.headline}*",
        content.dek,
        "🏀 *Matchups*\n" + "\n".join(matchup_lines),
    ]
    if mover_lines:
        summary_parts.append("📈 *Power Ranking Movers*\n" + "\n".join(mover_lines))
    if award_lines:
        summary_parts.append("🏆 *Awards*\n" + "\n".join(award_lines))
    if snapshot.data_quality.warnings:
        summary_parts.append(
            "⚠️ *Data notes*\n"
            + "\n".join(f"• {warning}" for warning in snapshot.data_quality.warnings)
        )
    summary_parts.append(f"Read the published recap: {url}")

    full_parts = [
        f"*{content.headline}*",
        content.dek,
        "\n\n".join(content.lead_story),
        "🏀 *Matchups*\n" + "\n".join(matchup_lines),
    ]
    if award_lines:
        full_parts.append("🏆 *Awards*\n" + "\n".join(award_lines))
    full_parts.append(f"Read the published recap: {url}")

    content.whatsapp_summary = "\n\n".join(summary_parts)
    content.whatsapp_full = "\n\n".join(full_parts)
    return content
