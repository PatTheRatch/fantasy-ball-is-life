"""WhatsApp-friendly recap formatters.

The narrative itself (matchups, ranking movers, awards, storylines) is
written by the model as free prose in `whatsapp_summary` / `whatsapp_full` --
see `generate.py`'s `_validate_whatsapp_completeness`, which rejects a draft
that fails to mention every matchup team and award winner by name. This
module only adds the one thing the model can't know: the app's public URL.
"""
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
    url = _public_url(snapshot)
    link_line = f"Read the published recap: {url}"
    content.whatsapp_summary = f"{content.whatsapp_summary}\n\n{link_line}"
    content.whatsapp_full = f"{content.whatsapp_full}\n\n{link_line}"
    return content
