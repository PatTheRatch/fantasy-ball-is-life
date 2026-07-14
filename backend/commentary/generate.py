"""Anthropic client calls for AI commentary endpoints."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import pandas as pd
import requests
from fastapi import HTTPException
from json_repair import repair_json

from backend import config
from backend.api.deps import _strip_numpy
from backend.commentary import prompts
from backend.commentary.schemas import (
    RecapGeneratedContent,
    WeeklyFactSnapshot,
    dump_model,
    validate_generated_content,
)


def _require_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY is missing. Set it in your environment or create a valid .env file.",
        )


def _complete(
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int,
    effort: Optional[str] = None,
) -> str:
    """Call Claude and return concatenated text blocks (skips thinking blocks).

    Anthropics Messages API. claude-sonnet-4-20250514 is deprecated
    (retires 2026-06-15); claude-sonnet-5 is its designated replacement.
    Sonnet 5 runs adaptive thinking by default; thinking tokens count against
    max_tokens *and* dominate latency (measured ~6k thinking tokens / ~87s for a
    full recap, which can also truncate the output). ``effort`` bounds that:
    ``low``/``medium``/``high`` set ``output_config.effort``, and ``off``
    disables thinking outright. ``None`` leaves the model default.
    """
    from anthropic import Anthropic

    extra: dict[str, Any] = {}
    if effort == "off":
        extra["thinking"] = {"type": "disabled"}
    elif effort:
        extra["output_config"] = {"effort": effort}

    # Let the anthropic client read ANTHROPIC_API_KEY from the environment.
    client = Anthropic()
    resp = client.messages.create(
        model="claude-sonnet-5",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        **extra,
    )
    usage = getattr(resp, "content", None) and getattr(resp, "usage", None)
    if usage is not None:
        thinking = getattr(
            getattr(usage, "output_tokens_details", None), "thinking_tokens", 0
        ) or 0
        logging.info(
            "recap LLM (effort=%s): output=%s thinking=%s input=%s",
            effort, usage.output_tokens, thinking, usage.input_tokens,
        )
    text = ""
    if getattr(resp, "content", None):
        for block in resp.content:
            # block is usually a TextBlock with `.text`.
            if hasattr(block, "text"):
                text += block.text
    return (text or "").strip()


def _require_recap_api_key() -> None:
    if config.RECAP_LLM_PROVIDER == "deepseek":
        if not config.DEEPSEEK_API_KEY:
            raise HTTPException(
                status_code=500,
                detail="DEEPSEEK_API_KEY is missing. Set it in the root .env file.",
            )
        return
    if config.RECAP_LLM_PROVIDER == "anthropic":
        _require_api_key()
        return
    raise HTTPException(
        status_code=500,
        detail=f"Unsupported RECAP_LLM_PROVIDER: {config.RECAP_LLM_PROVIDER}",
    )


def _complete_structured(
    system_prompt: str, user_prompt: str, *, max_tokens: int
) -> str:
    if config.RECAP_LLM_PROVIDER == "anthropic":
        return _complete(
            system_prompt, user_prompt, max_tokens=max_tokens,
            effort=config.RECAP_LLM_EFFORT,
        )

    try:
        response = requests.post(
            f"{config.DEEPSEEK_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                # DeepSeek caps output tokens well below Claude's; clamp so the
                # 16k Claude budget doesn't 400 the DeepSeek fallback.
                "max_tokens": min(max_tokens, 8192),
                "temperature": 0.7,
                "stream": False,
            },
            timeout=120,
        )
    except requests.RequestException as exc:
        raise RuntimeError("DeepSeek API request failed.") from exc

    if not response.ok:
        try:
            error = response.json().get("error", {})
            detail = error.get("message") or response.reason
        except (ValueError, AttributeError):
            detail = response.reason
        raise RuntimeError(
            f"DeepSeek API returned HTTP {response.status_code}: {detail}"
        )

    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("DeepSeek returned no completion choices.")
    choice = choices[0]
    if choice.get("finish_reason") == "length":
        raise RuntimeError("DeepSeek structured output exceeded the token limit.")
    content = (choice.get("message") or {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("DeepSeek returned empty structured output.")
    return content.strip()


def generate_matchup_commentary(body: Any) -> dict[str, Any]:
    """Generate a short ESPN-style preview article for the matchup using Anthropic."""
    try:
        _require_api_key()
        system_prompt, user_prompt = prompts.build_matchup_commentary_prompts(body)
        commentary_text = _complete(system_prompt, user_prompt, max_tokens=2000)
        return {"commentary": commentary_text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def generate_league_recap(body: Any) -> dict[str, Any]:
    """Generate a weekly league newsletter recap (ESPN-style) using Anthropic."""
    try:
        _require_api_key()
        system_prompt, user_prompt = prompts.build_league_recap_prompts(body)
        recap_text = _complete(system_prompt, user_prompt, max_tokens=4000)
        return {"recap": recap_text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def generate_season_commentary(body: Any) -> dict[str, Any]:
    try:
        _require_api_key()
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

        system_prompt, user_prompt = prompts.build_season_commentary_prompts(
            weeks_sorted=weeks_sorted,
            min_w=min_w,
            max_w=max_w,
            week_count=week_count,
            reg_season_count=reg_season_count,
            playoff_team_count=playoff_team_count,
            phase=phase,
            playoff_week=playoff_week,
            standings_payload=standings_payload,
            luck_payload=luck_payload,
            leaders_payload=leaders_payload,
        )
        commentary_text = _complete(system_prompt, user_prompt, max_tokens=4000)
        return {"commentary": commentary_text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


def _parse_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError as strict_exc:
        # LLMs intermittently emit almost-valid JSON — most commonly an
        # unescaped double-quote inside a narrative string, which terminates the
        # string early and yields "Expecting ',' delimiter". Repair and continue
        # rather than throwing away a full ~60s generation; the downstream schema
        # + evidence-id validation still guards correctness if the repair guesses
        # wrong.
        logging.warning(
            "structured recap JSON invalid (%s); attempting repair", strict_exc
        )
        value = repair_json(candidate, return_objects=True)
    if not isinstance(value, dict):
        raise ValueError("Structured recap response must be a JSON object.")
    return value


def _structured_corrective(snapshot: WeeklyFactSnapshot, error_msg: str) -> str:
    """A user-prompt suffix that tells the model exactly what to fix on retry.

    The only hard constraint now is coverage, so we spell out the exact id sets
    it must cover one-for-one -- far more actionable than the bare error."""
    matchup_ids = [item["matchup_id"] for item in snapshot.matchups]
    award_ids = [item["award_id"] for item in snapshot.award_candidates]
    return "\n".join(
        [
            "",
            "",
            "IMPORTANT — your previous response was REJECTED:",
            f"  {error_msg}",
            "Return the COMPLETE corrected JSON object (not a diff, not prose).",
            "Include exactly one entry per id below — none missing, extra, or "
            "duplicated:",
            f"  matchup_takeaways -> one per matchup_id: {matchup_ids}",
            f"  award_explanations -> one per award_id: {award_ids}",
        ]
    )


def generate_structured_recap(
    snapshot: WeeklyFactSnapshot,
    *,
    max_attempts: int = 3,
    skip_ranking_explanations: bool = False,
) -> RecapGeneratedContent:
    """Generate the voice-driven weekly recap for a persisted fact snapshot.

    The model writes one three-voice-plus-insight takeaway per matchup and one
    line per award; the factual headers (who beat whom, the score) come from the
    deterministic snapshot, not the model. Coverage is the only hard constraint,
    so on a miss we re-prompt with the exact ids and retry rather than discarding
    the generation.

    ``skip_ranking_explanations``: when this week's power-rankings blurbs are
    already persisted (see ``backend.recaps.service.generate_draft``), drop
    that section from the prompt entirely -- the caller splices the reused
    blurbs into the result afterward, so asking the LLM to write (and then
    discard) new ones would just waste tokens and latency."""
    _require_recap_api_key()
    snapshot_payload = dump_model(snapshot)
    system_prompt, base_user_prompt = prompts.build_structured_recap_prompts(
        snapshot_payload, skip_ranking_explanations=skip_ranking_explanations,
    )
    last_error: Exception | None = None
    corrective = ""
    for attempt in range(1, max_attempts + 1):
        # 16k so thinking tokens can't crowd out the JSON output and truncate it.
        raw = _complete_structured(
            system_prompt, base_user_prompt + corrective, max_tokens=16000
        )
        try:
            return _parse_and_validate_recap(raw, snapshot)
        except ValueError as exc:
            last_error = exc
            logging.warning(
                "structured recap attempt %d/%d rejected: %s",
                attempt, max_attempts, exc,
            )
            corrective = _structured_corrective(snapshot, str(exc))
    raise ValueError(
        f"LLM returned an invalid structured recap after {max_attempts} attempts: "
        f"{last_error}"
    )


def _parse_and_validate_recap(
    raw: str,
    snapshot: WeeklyFactSnapshot,
) -> RecapGeneratedContent:
    """Parse one raw LLM response and enforce matchup/award coverage.

    Raises ``ValueError`` on any problem (bad JSON, schema, coverage) so the
    caller can retry with corrective feedback. Everything factual is supplied by
    the deterministic snapshot, so there is no evidence-id binding to enforce."""
    try:
        content = validate_generated_content(_parse_json_object(raw))
    except Exception as exc:
        raise ValueError(f"LLM returned an invalid structured recap: {exc}") from exc

    matchup_ids = {item["matchup_id"] for item in snapshot.matchups}
    returned_matchups = {item.matchup_id for item in content.matchup_takeaways}
    if (
        returned_matchups != matchup_ids
        or len(content.matchup_takeaways) != len(matchup_ids)
    ):
        raise ValueError("Structured recap must contain exactly one takeaway per matchup.")

    award_ids = {item["award_id"] for item in snapshot.award_candidates}
    returned_awards = {item.award_id for item in content.award_explanations}
    if returned_awards != award_ids or len(content.award_explanations) != len(
        award_ids
    ):
        raise ValueError(
            "Structured recap must contain exactly one explanation per award."
        )

    return content
