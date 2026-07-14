"""Assemble the group-chat-ready recap text.

The recap is deterministic facts + LLM voice: the matchup headers (who beat
whom, the category score) and award titles/winners come from the snapshot, while
the model supplies the three-voice takes and insight. Assembling here — rather
than asking the model for a free-prose ``whatsapp_full`` — guarantees every
matchup's two teams are named (they're in the header) and that the shared text
always matches what the tabs display.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from backend import config
from backend.commentary.schemas import RecapGeneratedContent, WeeklyFactSnapshot

_DIVIDER = "⸻"


def _public_url(snapshot: WeeklyFactSnapshot) -> str:
    query = urlencode({"season": snapshot.season, "week": snapshot.week})
    return f"{config.PUBLIC_APP_URL}/recap?{query}"


def _matchup_header(matchup: dict[str, Any]) -> str:
    """`Winner def. Loser, 6-3` (ties appended), or a neutral `vs.` on a tie."""
    home = str(matchup.get("home_team") or "")
    away = str(matchup.get("away_team") or "")
    home_wins = int(matchup.get("home_category_wins") or 0)
    away_wins = int(matchup.get("away_category_wins") or 0)
    ties = int(matchup.get("ties") or 0)
    winner = matchup.get("winner") or ""
    tie_suffix = f"-{ties}" if ties else ""

    if winner not in (home, away):  # "Tie" / unavailable
        return f"{home} vs. {away}, {home_wins}-{away_wins}{tie_suffix}"
    loser = away if winner == home else home
    win_cats = home_wins if winner == home else away_wins
    lose_cats = away_wins if winner == home else home_wins
    return f"{winner} def. {loser}, {win_cats}-{lose_cats}{tie_suffix}"


def build_share_text(
    snapshot: WeeklyFactSnapshot, content: RecapGeneratedContent
) -> str:
    """Render the full shareable recap from deterministic facts + LLM voice."""
    takeaway_by_id = {t.matchup_id: t for t in content.matchup_takeaways}
    award_by_id = {a["award_id"]: a for a in snapshot.award_candidates}

    lines: list[str] = [content.headline, "", content.intro, ""]

    for paragraph in content.synopsis:
        lines += [paragraph, ""]

    for matchup in snapshot.matchups:  # snapshot order = stable read order
        takeaway = takeaway_by_id.get(matchup["matchup_id"])
        if takeaway is None:
            continue
        lines += [
            _DIVIDER,
            "",
            _matchup_header(matchup),
            f"Woj: {takeaway.woj}",
            f"Barkley: {takeaway.barkley}",
            f"Stephen A: {takeaway.stephen_a}",
            f"Insight: {takeaway.insight}",
            "",
        ]

    if content.award_explanations:
        lines += [_DIVIDER, ""]
        for award in content.award_explanations:
            meta = award_by_id.get(award.award_id, {})
            title = str(meta.get("title") or award.award_id)
            winner = str(meta.get("winner") or "")
            head = f"🏆 {title}" + (f": {winner}" if winner else "")
            lines += [head, award.text, ""]

    lines.append(f"Read the published recap: {_public_url(snapshot)}")
    return "\n".join(lines).strip()


def format_share_text(
    snapshot: WeeklyFactSnapshot,
    content: RecapGeneratedContent,
) -> RecapGeneratedContent:
    """Populate ``content.share_text`` with the assembled recap."""
    content.share_text = build_share_text(snapshot, content)
    return content
