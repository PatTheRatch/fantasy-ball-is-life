"""Prompt blobs for AI commentary endpoints (lifted out of api.py / main.py).

Each builder returns ``(system_prompt, user_prompt)``. Prep that exists only
to feed the prompt lives here; Anthropic client calls live in ``generate.py``.
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

from fastapi.encoders import jsonable_encoder


def build_matchup_commentary_prompts(body: Any) -> Tuple[str, str]:
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

    def _avg_conf(rs: list) -> Optional[float]:
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
    def _format_category_result(r: Any) -> str:
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

    def _roster_lines(roster: list) -> str:
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
    return system_prompt, user_prompt


def build_league_recap_prompts(body: Any) -> Tuple[str, str]:
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
    return system_prompt, user_prompt


def build_season_commentary_prompts(
    *,
    weeks_sorted: List[int],
    min_w: int,
    max_w: int,
    week_count: int,
    reg_season_count: int,
    playoff_team_count: int,
    phase: str,
    playoff_week: Optional[int],
    standings_payload: Any,
    luck_payload: Any,
    leaders_payload: Any,
) -> Tuple[str, str]:
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
    return system_prompt, user_prompt


def build_structured_recap_prompts(
    snapshot: Dict[str, Any],
) -> Tuple[str, str]:
    system_prompt = (
        "You are the league's recap columnist -- not a stats-report generator. "
        "Write like a commissioner who watches every matchup and knows every "
        "owner: sports journalism with personality (ESPN recap crossed with a "
        "feature article and group-chat banter), never an AI summary.\n\n"
        "NARRATIVE FIRST. Facts create credibility; narrative creates "
        "entertainment. Statistics support the story, they are not the story -- "
        "use a number only when it makes a moment more dramatic. Before writing, "
        "decide what actually mattered this week (an upset, a streak, a "
        "collapse, standings chaos) and let that story lead; everything else "
        "supports it. If nothing extraordinary happened, say so plainly instead "
        "of manufacturing drama.\n\n"
        "HEADLINE: should read like something ESPN would publish, with real "
        "tension. Never 'Week N Recap' or 'League Update' -- think 'Kings "
        "Fall.' or 'Chaos at the Top.'\n\n"
        "TONE: punch upward at luck, randomness, bad schedules, and cursed "
        "performances -- never at an owner personally. Roast the fantasy "
        "outcome, not the person. Humor emerges from the facts (bad luck, "
        "waiver-wire addiction, a last-second escape), never a joke for its "
        "own sake.\n\n"
        "AVOID: cliches like 'statement win', 'must win', 'absolute clinic', "
        "'masterclass', 'gave 110%', 'at the end of the day', and AI-summary "
        "tells like 'it's worth noting', 'ultimately', 'overall', "
        "'in conclusion', 'showcased', 'demonstrated'.\n\n"
        "The supplied fact snapshot is your only source of truth. Never invent, "
        "infer, or import a player, team, score, result, ranking, transaction, "
        "award winner, or trend that is absent from it. Omit claims when evidence "
        "is unavailable. Return one JSON object only: no Markdown fences and no "
        "text before or after it. Preserve every referenced matchup_id, team_id, "
        "award_id, and evidence_id exactly."
    )
    recap_voice = (snapshot.get("league") or {}).get("recap_voice")
    if recap_voice:
        system_prompt += f"\n\nLEAGUE-SPECIFIC VOICE NOTES (apply on top of the above):\n{recap_voice}"

    schema = {
        "headline": "string",
        "dek": "string",
        "lead_story": ["paragraph string"],
        "matchup_takeaways": [
            {
                "matchup_id": "exact snapshot matchup_id",
                "text": "1-3 sentences: what made this matchup memorable, one supporting fact, one implication -- not a category-by-category recount",
                "evidence_ids": ["exact snapshot evidence_id"],
            }
        ],
        "ranking_explanations": [
            {
                "team_id": "team evidence_id suffix or exact team/team_id value",
                "text": "one or two grounded sentences",
                "evidence_ids": ["exact snapshot evidence_id"],
            }
        ],
        "award_explanations": [
            {
                "award_id": "exact deterministic award_id",
                "text": "one grounded sentence justifying the narrative behind the already-decided winner -- not restating the math",
                "evidence_ids": ["exact snapshot evidence_id"],
            }
        ],
        "whatsapp_summary": "few-scroll WhatsApp-ready summary",
        "whatsapp_full": "complete WhatsApp-ready narrative without tables",
    }
    user_prompt = (
        "OUTPUT SCHEMA:\n"
        f"{json.dumps(schema, separators=(',', ':'))}\n\n"
        "FACT SNAPSHOT:\n"
        f"{json.dumps(snapshot, separators=(',', ':'), ensure_ascii=False)}\n\n"
        "Write the edition. Include a matchup_takeaway for every matchup and an "
        "award_explanation for every supplied award. The WhatsApp summary must "
        "include every matchup result, key ranking movers, selected awards, and "
        "restrained section labels. If data_quality.ready is false, disclose the "
        "warnings and do not fill the gaps. lead_story should read as one "
        "throughline (the week's biggest story, evidence for it, why it "
        "matters going forward) rather than a paragraph per matchup -- three "
        "paragraphs is a good default when there's a clear headline story.\n\n"
        "Before returning, check your own draft: does the headline create "
        "curiosity instead of describing the document? Is there one clear "
        "throughline the rest of the piece supports? Would a league member "
        "quote a line of this in the group chat, or does it read like an "
        "auto-generated summary?"
    )
    return system_prompt, user_prompt
