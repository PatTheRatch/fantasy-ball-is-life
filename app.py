"""
Streamlit UI for PatriotGames fantasy tools (calls FastAPI backend).
"""
from __future__ import annotations

import hashlib
import io
import json
import html as html_lib
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pandas as pd
import streamlit as st

from backend.config import BBM_PROJECTIONS_PATH

API_BASE = "http://localhost:8000"

CONSTRAINT_CATS = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]
STAT_OPTIONS = CONSTRAINT_CATS.copy()


def _init_session_state() -> None:
    defaults: Dict[str, Any] = {
        "draft_roster": [],  # list of {"name": str, "bid": float}
        "optimizer_result": None,
        "optimizer_error": None,
        "current_scoreboard": None,
        "current_scoreboard_error": None,
        "rosters_current_raw_current": None,  # roster projections for the selected *current* week (remaining games)
        "rosters_current_raw_current_total": None,  # roster game counts for the selected *current* week (full week)
        "projected_scoreboard": None,
        "projected_sb_error": None,
        "rosters_current_raw": None,
        "rosters_current_raw_total": None,
        "power_rankings": None,
        "power_rankings_error": None,
        "transactions": None,
        "transactions_error": None,
        "ai_commentary_text": None,
        "ai_commentary_error": None,
        "ai_commentary_matchup_key": None,
        "ai_current_commentary_text": None,
        "ai_current_commentary_error": None,
        "ai_current_commentary_matchup_key": None,
        "weekly_recap_text": None,
        "weekly_recap_error": None,
        "weekly_recap_week": None,
        # Separate from the selectbox key (`weekly_recap_week`) to avoid Streamlit widget-key mutation errors.
        "weekly_recap_week_last_generated": None,
        "league_settings": None,
        "season_stats": None,
        "season_stats_error": None,
        "season_commentary_text": None,
        "season_commentary_error": None,
        "season_commentary_weeks_key": None,
        "league_settings_error": None,
        "draft_projection_names": None,  # list[str] from uploaded BBM file
        "draft_names_file_id": None,  # hash / file id to detect new upload
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


def _player_names_from_projection_bytes(data: bytes, filename: str = "") -> List[str]:
    """Read unique player names from a BBM-style Excel upload (expects a Name column)."""
    df = pd.read_excel(io.BytesIO(data))
    if df is None or df.empty:
        return []
    name_col = None
    for cand in ("Name", "Player", "name", "player"):
        if cand in df.columns:
            name_col = cand
            break
    if name_col is None:
        for c in df.columns:
            if str(c).strip().lower() in ("name", "player"):
                name_col = c
                break
    if name_col is None:
        raise ValueError(
            "Could not find a player name column. Expected a column named Name or Player "
            f"(columns seen: {list(df.columns)[:12]}{'…' if len(df.columns) > 12 else ''})."
        )
    s = df[name_col].dropna().astype(str).str.strip()
    s = s[s != ""]
    names = sorted(set(s.unique().tolist()), key=str.lower)
    return names


def _ensure_league_settings() -> None:
    """Fetch ESPN league settings once per session for the sidebar (and Season tab)."""
    if st.session_state.get("league_settings") is not None:
        return
    try:
        with _http_client() as client:
            r = client.get("/league/settings")
            r.raise_for_status()
            st.session_state.league_settings = r.json()
            st.session_state.league_settings_error = None
    except Exception as e:
        st.session_state.league_settings = None
        st.session_state.league_settings_error = _friendly_api_error(e)


def _render_league_sidebar() -> None:
    """ESPN league settings in the left sidebar (not draft optimizer options)."""
    with st.sidebar:
        st.subheader("League settings")
        if st.session_state.get("league_settings_error") and st.session_state.get("league_settings") is None:
            st.warning(st.session_state.league_settings_error)
            if st.button("Retry", key="btn_sidebar_league_retry"):
                st.session_state.league_settings_error = None
                _ensure_league_settings()
                st.rerun()
        else:
            s = st.session_state.league_settings or {}
            name = s.get("name") or "League"
            st.markdown(f"**{name}**")
            rows = [
                ("Teams", s.get("team_count")),
                ("Scoring", s.get("scoring_type")),
                ("Regular season weeks", s.get("reg_season_count")),
                ("Playoff teams", s.get("playoff_team_count")),
                ("Playoff matchup length (periods)", s.get("playoff_matchup_period_length")),
                ("FAAB", s.get("faab")),
                ("Acquisition budget", s.get("acquisition_budget")),
                ("Current matchup period", s.get("current_week")),
            ]
            for label, val in rows:
                if val is not None and val != "":
                    st.caption(f"{label}")
                    st.text(str(val))
            if st.button("Refresh league settings", key="btn_sidebar_league_refresh"):
                try:
                    with _http_client() as client:
                        r = client.get("/league/settings")
                        r.raise_for_status()
                        st.session_state.league_settings = r.json()
                        st.session_state.league_settings_error = None
                except Exception as e:
                    st.session_state.league_settings_error = _friendly_api_error(e)
                st.rerun()


def _http_client() -> httpx.Client:
    return httpx.Client(base_url=API_BASE, timeout=120.0)


def _friendly_api_error(exc: BaseException) -> str:
    """Turn connection errors into actionable hints (API must be running separately)."""
    if isinstance(exc, httpx.ConnectError):
        return (
            f"Cannot connect to the API at {API_BASE}. "
            "Start the FastAPI server in another terminal, then try again. "
            "Example: uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --reload"
        )
    if isinstance(exc, httpx.TimeoutException):
        return (
            f"Request to `{API_BASE}` timed out. If the server is running, "
            "it may be busy calling ESPN; try again."
        )
    return str(exc)


def _wl_badge_html(result: str) -> str:
    r = (result or "").strip().upper()
    if r == "W":
        color = "#16a34a"
    elif r == "L":
        color = "#dc2626"
    else:
        color = "#6b7280"
    return (
        f'<span style="display:inline-block;min-width:1.35em;text-align:center;'
        f"background:{color};color:white;font-weight:700;padding:1px 7px;"
        f'border-radius:999px;font-size:0.78rem;line-height:1.2;">{r}</span>'
    )


def _change_display(val: Any) -> str:
    s = str(val) if val is not None else ""
    s_stripped = s.strip()
    if s_stripped.startswith("+"):
        return f"▲ {s_stripped}"
    if s_stripped.startswith("-"):
        return f"▼ {s_stripped}"
    return s


def _group_matchups(rows: List[Dict[str, Any]]) -> List[Tuple[str, str, List[Dict[str, Any]]]]:
    """Return list of (home_team, away_team, list of stat rows for that matchup)."""
    seen: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    order: List[Tuple[str, str]] = []
    for row in rows:
        h = row.get("home_team")
        a = row.get("away_team")
        if h is None or a is None:
            continue
        key = (h, a)
        if key not in seen:
            seen[key] = []
            order.append(key)
        seen[key].append(row)
    return [(h, a, seen[(h, a)]) for h, a in order]


def tab_draft_optimizer() -> None:
    st.header("Draft Optimizer")

    uploaded = st.file_uploader(
        "Season BBM projections (.xls / .xlsx) — optional, overrides the default projections",
        type=["xls", "xlsx"],
        key="bbm_season_file",
    )

    if uploaded is None:
        if st.session_state.get("draft_names_file_id") != "__default__":
            default_path = Path(BBM_PROJECTIONS_PATH)
            if default_path.exists():
                try:
                    st.session_state.draft_projection_names = _player_names_from_projection_bytes(
                        default_path.read_bytes(), default_path.name
                    )
                    st.session_state.draft_names_file_id = "__default__"
                except Exception as e:
                    st.session_state.draft_projection_names = None
                    st.session_state.draft_names_file_id = None
                    st.warning(f"Could not read player names for autocomplete: {e}")
            else:
                st.session_state.draft_projection_names = None
                st.session_state.draft_names_file_id = None
    else:
        raw = uploaded.getvalue()
        fid = getattr(uploaded, "file_id", None) or hashlib.sha256(raw).hexdigest()
        if st.session_state.get("draft_names_file_id") != fid:
            try:
                st.session_state.draft_projection_names = _player_names_from_projection_bytes(
                    raw, uploaded.name or ""
                )
                st.session_state.draft_names_file_id = fid
            except Exception as e:
                st.session_state.draft_projection_names = None
                st.session_state.draft_names_file_id = fid
                st.warning(f"Could not read player names for autocomplete: {e}")

    with st.expander("⚙️ Budget & draft parameters", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            budget = st.number_input("Budget", min_value=1.0, value=200.0, step=1.0, key="draft_budget")
            roster_size = st.number_input("Roster Size", min_value=1, value=13, step=1, key="draft_roster_size")
            games_per_week = st.number_input(
                "Games Per Week", min_value=0.1, value=3.0, step=0.1, key="draft_gpw"
            )
            min_games_threshold = st.number_input(
                "Min Games Threshold", min_value=0.0, value=55.0, step=1.0, key="draft_min_games"
            )
        with c2:
            percentile = st.slider(
                "Percentile", min_value=0.5, max_value=1.0, value=0.75, step=0.01, key="draft_pct"
            )
            value_col = st.selectbox("Value Column", options=["$", "Value", "Bid"], index=0, key="draft_value_col")
            favorite_team = st.text_input("Favorite Team (optional)", value="", key="draft_fav_team")
            favorite_team = favorite_team.strip() or None

    with st.expander("🎯 Optimizer constraints", expanded=True):
        categories = st.multiselect(
            "Constraint Categories",
            options=CONSTRAINT_CATS,
            default=["PTS", "REB", "AST", "STL", "BLK"],
            key="draft_constraint_cats",
        )
        stat_to_maximize = st.selectbox(
            "Stat to Maximize",
            options=STAT_OPTIONS,
            index=STAT_OPTIONS.index("3PM") if "3PM" in STAT_OPTIONS else 0,
            key="draft_stat_max",
        )

    with st.expander("🚫 Excluded players"):
        excluded_raw = st.text_area("One player per line", height=120, value="", key="draft_excluded")
        exclude_players = [ln.strip() for ln in excluded_raw.splitlines() if ln.strip()]

    st.subheader("📋 Current Roster")
    names_all = st.session_state.get("draft_projection_names") or []
    new_name = ""
    new_bid = 1.0
    add = False

    if names_all:
        st.caption(
            f"Choose a player from your uploaded projections ({len(names_all)} players). "
            "Filter narrows the dropdown; in the dropdown you can also type to search."
        )
        st.text_input(
            "Filter list",
            key="draft_player_filter",
            placeholder="Type to filter, e.g. lebron",
            label_visibility="collapsed",
        )
        q = (st.session_state.get("draft_player_filter") or "").strip().lower()
        if q:
            filtered = [n for n in names_all if q in n.lower()]
            if len(filtered) > 400:
                filtered = filtered[:400]
                st.caption("Showing first 400 matches — refine the filter.")
        else:
            filtered = names_all[:400]
            if len(names_all) > 400:
                st.caption("Showing first 400 players — use the filter to find anyone.")

        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            choice = st.selectbox(
                "Player",
                ["— Select —"] + filtered,
                key="draft_player_pick",
                label_visibility="collapsed",
            )
        with c2:
            new_bid = st.number_input("Bid", min_value=0.0, value=1.0, step=1.0, key="draft_new_bid")
        with c3:
            add = st.button("Add Player", key="draft_btn_add_player")

        if choice and not str(choice).startswith("—"):
            new_name = str(choice).strip()

        with st.expander("Manual name (optional)", expanded=False):
            st.caption("Use only if the picker does not list the player; spelling should match the projections file.")
            manual = st.text_input("Exact player name", key="draft_new_name_manual", label_visibility="visible")
            if manual.strip():
                new_name = manual.strip()
    else:
        st.caption("Player name autocomplete is unavailable — enter names manually below.")
        c1, c2, c3 = st.columns([2, 1, 1])
        with c1:
            new_name = st.text_input("Player name", key="draft_new_name", label_visibility="collapsed")
        with c2:
            new_bid = st.number_input("Bid", min_value=0.0, value=1.0, step=1.0, key="draft_new_bid_fallback")
        with c3:
            add = st.button("Add Player", key="draft_btn_add_player_fallback")

    if add and new_name.strip():
        st.session_state.draft_roster.append(
            {"name": new_name.strip(), "bid": float(new_bid)}
        )
        if "draft_player_pick" in st.session_state:
            st.session_state.draft_player_pick = "— Select —"
        st.rerun()

    if st.session_state.draft_roster:
        roster_df = pd.DataFrame(st.session_state.draft_roster)
        st.dataframe(roster_df, use_container_width=True, hide_index=True)
    else:
        st.caption("No players added yet.")

    b1, b2 = st.columns(2)
    with b1:
        if st.button("Clear Roster"):
            st.session_state.draft_roster = []
            st.session_state.optimizer_result = None
            st.session_state.optimizer_error = None
            st.rerun()
    with b2:
        optimize = st.button("🔍 Optimize", type="primary")

    if optimize:
        if not categories:
            st.warning("Select at least one constraint category.")
        else:
            payload = {
                "exclude_players": exclude_players or None,
                "games_per_week": float(games_per_week),
                "initial_budget": float(budget),
                "year": None,
                "roster_size": int(roster_size),
                "minimum_value_players": 3,
                "favorite_team": favorite_team,
                "favorite_team_representation": 1,
                "minimum_game_threshold": float(min_games_threshold),
                "value_col": value_col,
                "categories": categories,
                "percentile": float(percentile),
                "stat_to_maximize": stat_to_maximize,
                "draft_picks": [
                    {"name": r["name"], "bid": float(r["bid"])}
                    for r in st.session_state.draft_roster
                ],
            }
            try:
                files: Dict[str, Any] = {"data": (None, json.dumps(payload))}
                if uploaded is not None:
                    file_body = uploaded.getvalue()
                    fname = uploaded.name or "bbm.xlsx"
                    files["bbm_file"] = (fname, file_body, "application/octet-stream")
                with _http_client() as client:
                    r = client.post("/optimizer/optimize", files=files)
                r.raise_for_status()
                rows = r.json()
                df = pd.DataFrame(rows)
                # Columns: Name, Pos, Team, $, and * PW
                base_cols = [c for c in ["Name", "Pos", "Team", "$"] if c in df.columns]
                pw_cols = [c for c in df.columns if str(c).endswith(" PW")]
                show_cols = base_cols + pw_cols
                show_cols = [c for c in show_cols if c in df.columns]
                if show_cols:
                    df = df[show_cols]
                st.session_state.optimizer_result = df
                st.session_state.optimizer_error = None
            except Exception as e:
                st.session_state.optimizer_result = None
                msg = _friendly_api_error(e)
                st.session_state.optimizer_error = msg
                st.error(msg)

    if st.session_state.optimizer_error and not optimize:
        st.error(st.session_state.optimizer_error)

    if st.session_state.optimizer_result is not None:
        st.subheader("Optimization result")
        st.dataframe(st.session_state.optimizer_result, use_container_width=True)


def tab_in_season() -> None:
    st.header("In-Season Dashboard")

    # Custom visual styling for all matchup sections.
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600&family=Bebas+Neue&display=swap');

.pg-card, .pg-card *,
.pg-matchup-table, .pg-matchup-table *,
.pg-ai-box, .pg-ai-box *,
.pg-scoreline, .pg-scoreline * {
  font-family: "DM Sans", system-ui, -apple-system, Segoe UI, Roboto, sans-serif !important;
}

html, body {
  background: #0d1117 !important;
}

.pg-card {
  background: #0b1220;
  border: 1px solid #1c2333;
  border-radius: 14px;
  padding: 14px 12px;
  margin: 10px 0;
}

.pg-matchup-table {
  width: 100%;
  border-collapse: collapse;
}

.pg-matchup-table thead th {
  padding: 6px 8px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
  color: #9ca3af;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  font-size: 12px;
}

.pg-stat-header { text-align: left; width: 110px; }

.pg-team-header {
  text-align: center !important;
  color: #e6edf3 !important;
  font-family: "Bebas Neue", sans-serif !important;
  font-size: 32px;
  letter-spacing: 0;
  text-transform: none;
  border-bottom: 0 !important;
  padding-bottom: 10px !important;
}

.pg-stat-cell {
  padding: 6px 8px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  color: #e6edf3;
  text-align: left;
  font-weight: 600;
  width: 110px;
}

.pg-team-cell {
  padding: 6px 8px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  text-align: center;
}

.pg-matchup-table tbody tr:nth-child(odd) { background: #161b22; }
.pg-matchup-table tbody tr:nth-child(even) { background: #1c2333; }

.pg-cell-center { text-align: center; line-height: 1.2; }

.pg-wl-stack {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 3px;
}

.pg-conf-text {
  font-size: 0.78rem;
  font-weight: 600;
  margin-top: 3px;
}
.pg-conf-green { color: #22c55e; }
.pg-conf-yellow { color: #f59e0b; }
.pg-conf-red { color: #ef4444; }

.pg-scoreline {
  display: flex;
  justify-content: center;
  align-items: baseline;
  gap: 14px;
  margin: 6px 0 0;
}
.pg-score-number {
  font-family: "Bebas Neue", sans-serif;
  font-size: 64px;
  font-weight: 700;
  line-height: 1;
}
.pg-score-win { color: #22c55e; }
.pg-score-loss { color: #94a3b8; }
.pg-score-sep { color: #64748b; font-size: 52px; }
.pg-scoremeta {
  text-align: center;
  color: #e6edf3;
  opacity: 0.85;
  margin-top: -8px;
  font-size: 14px;
}

.pg-ai-box {
  background: #0b1220;
  border-left: 3px solid #cc0000;
  border: 1px solid rgba(204,0,0,0.35);
  border-radius: 12px;
  padding: 14px 16px;
  margin-top: 12px;
}
.pg-ai-label {
  font-style: italic;
  font-variant: all-small-caps;
  letter-spacing: 0.10em;
  font-size: 12px;
  color: #e6edf3;
  opacity: 0.95;
  margin-bottom: 8px;
}
.pg-ai-text {
  color: #e6edf3;
  white-space: normal;
  line-height: 1.45;
}
</style>
""",
        unsafe_allow_html=True,
    )

    projection_source = st.radio(
        "Projection Source",
        options=["Upload BBM File", "Last 15 Days", "Last 30 Days"],
        index=0,
    )

    projections_param: str
    projections_label: str
    weekly = None
    if projection_source == "Upload BBM File":
        projections_param = "BBM"
        projections_label = "Basketball Monster weekly projections"
        weekly = st.file_uploader(
            "Weekly BBM projections (.xls / .xlsx)",
            type=["xls", "xlsx"],
            key="bbm_weekly_file",
        )
    elif projection_source == "Last 15 Days":
        projections_param = "15"
        projections_label = "last 15 days of performance"
    else:
        projections_param = "30"
        projections_label = "last 30 days of performance"

    # "Current Matchup Week" is a bounded discrete set: choose based on today's date.
    # (We derive options from the same week range mapping used by the backend.)
    from backend.league.data_feed import MATCHUP_WEEKS_2025_26

    # Only allow weeks that have completed (end date <= today).
    week_options_all = sorted(int(w) for w in MATCHUP_WEEKS_2025_26.keys())
    today = date.today()
    week_options: List[int] = []
    for w in week_options_all:
        meta_w = MATCHUP_WEEKS_2025_26.get(int(w), {}) or {}
        end_s = meta_w.get("end")
        try:
            end_d = date.fromisoformat(str(end_s)) if end_s else None
        except Exception:
            end_d = None
        if end_d is not None and end_d <= today:
            week_options.append(int(w))
    if not week_options:
        week_options = week_options_all
    today = date.today()
    default_week = week_options[-1]
    for w in week_options:
        meta = MATCHUP_WEEKS_2025_26[w]
        start_s = meta.get("start")
        end_s = meta.get("end")
        if not start_s or not end_s:
            continue
        start_d = date.fromisoformat(str(start_s))
        end_d = date.fromisoformat(str(end_s))
        if start_d <= today <= end_d:
            default_week = w
            break
        if today < start_d:
            default_week = week_options[0]
            break
        default_week = w  # keep updating to "most recently started"

    matchup_week = st.selectbox(
        "Matchup Week",
        options=week_options,
        index=week_options.index(default_week),
        key="sb_projected_week",
    )

    # Used for "as-of" simulation of how far through the matchup week we are.
    # Drives the games_played/completion_factor that blends confidence.
    as_of_date = st.date_input("Run as of", value=date.today())

    # Legacy variable used by the old "Current Matchup" section code (kept to avoid refactors).
    current_week = matchup_week

    st.subheader("📊 Matchup")
    st.caption(
        f"Projected for matchup week {matchup_week} (using roster projections). "
        f"Confidence is blended using matchup completion as of {as_of_date}."
    )
    if st.button("Load matchup", key="btn_projected_sb"):
        try:
            with _http_client() as client:
                week_meta = MATCHUP_WEEKS_2025_26.get(int(matchup_week))
                week_end = week_meta.get("end") if week_meta else None
                week_start_total = week_meta.get("start") if week_meta else None
                week_start_remaining = as_of_date.isoformat()
                if not week_end or not week_start_total:
                    raise RuntimeError("Missing matchup week metadata for projected week.")

                if projection_source == "Upload BBM File":
                    if weekly is None:
                        st.warning("Upload a weekly BBM file first.")
                        return
                    pr = client.post(
                        "/rosters/current",
                        files={
                            "bbm_file": (
                                weekly.name or "weekly.xlsx",
                                weekly.getvalue(),
                                "application/octet-stream",
                            ),
                        },
                        params={"projections": projections_param},
                        data={
                            "current_matchup_period": str(int(matchup_week)),
                            "week_start_date": week_start_remaining,
                            "week_end_date": week_end,
                        },
                    )
                    pr2 = client.post(
                        "/rosters/current",
                        files={
                            "bbm_file": (
                                weekly.name or "weekly.xlsx",
                                weekly.getvalue(),
                                "application/octet-stream",
                            ),
                        },
                        params={"projections": projections_param},
                        data={
                            "current_matchup_period": str(int(matchup_week)),
                            "week_start_date": week_start_total,
                            "week_end_date": week_end,
                        },
                    )
                else:
                    # For last-N windows, do not upload a file; just request the window.
                    pr = client.post(
                        "/rosters/current",
                        params={"projections": projections_param},
                        data={
                            "current_matchup_period": str(int(matchup_week)),
                            "week_start_date": week_start_remaining,
                            "week_end_date": week_end,
                        },
                    )
                    pr2 = client.post(
                        "/rosters/current",
                        params={"projections": projections_param},
                        data={
                            "current_matchup_period": str(int(matchup_week)),
                            "week_start_date": week_start_total,
                            "week_end_date": week_end,
                        },
                    )

                pr.raise_for_status()
                st.session_state.rosters_current_raw = pr.json()
                pr2.raise_for_status()
                st.session_state.rosters_current_raw_total = pr2.json()

                qs = {"current_matchup_period": int(matchup_week), "projections": projections_param}
                sb = client.get("/projected-scoreboard", params=qs)
                sb.raise_for_status()

                df_sb = pd.DataFrame(sb.json())
                st.session_state.projected_scoreboard = df_sb.to_dict(orient="records")
                st.session_state.projected_sb_error = None
        except Exception as e:
            st.session_state.projected_scoreboard = None
            st.session_state.rosters_current_raw_total = None
            msg = _friendly_api_error(e)
            st.session_state.projected_sb_error = msg
            st.error(msg)

    if st.session_state.get("projected_sb_error"):
        st.error(st.session_state.projected_sb_error)

    rows = st.session_state.projected_scoreboard
    if rows:
        df_sb = pd.DataFrame(rows)
        if not df_sb.empty:
            df_sb["matchup"] = df_sb["home_team"].astype(str) + " vs " + df_sb["away_team"].astype(str)
            matchup_labels = sorted(df_sb["matchup"].dropna().unique().tolist())

            selected_matchup = st.selectbox(
                "Select matchup",
                matchup_labels,
                key="sb_selected_matchup",
            )

            sel = df_sb[df_sb["matchup"] == selected_matchup].copy()
            home_team = str(sel["home_team"].iloc[0])
            away_team = str(sel["away_team"].iloc[0])

            # W/L/T tally across the 9 categories (using home team's perspective)
            home_wins = int((sel["projected_home_result"] == "W").sum())
            away_wins = int((sel["projected_home_result"] == "L").sum())
            ties = int((sel["projected_home_result"] == "T").sum())

            # Progress / live status (driven by roster num_games_left as of the selected date).
            is_live = False
            progress_disp = "Progress: —"

            # Confidence with late-week completion blend.
            # We compute completion using remaining-vs-total game counts from the roster data already loaded.
            try:
                remaining_df = pd.DataFrame(st.session_state.get("rosters_current_raw") or [])
                total_df = pd.DataFrame(st.session_state.get("rosters_current_raw_total") or [])
                if (
                    not remaining_df.empty
                    and not total_df.empty
                    and "team_name" in remaining_df.columns
                    and "team_name" in total_df.columns
                    and "num_games_left" in remaining_df.columns
                    and "num_games_left" in total_df.columns
                ):
                    teams = {home_team, away_team}
                    rem_games = pd.to_numeric(
                        remaining_df[remaining_df["team_name"].astype(str).isin(teams)]["num_games_left"],
                        errors="coerce",
                    ).fillna(0).sum()
                    total_games = pd.to_numeric(
                        total_df[total_df["team_name"].astype(str).isin(teams)]["num_games_left"],
                        errors="coerce",
                    ).fillna(0).sum()
                    games_played = max(float(total_games) - float(rem_games), 0.0)
                    total_games_int = int(round(float(total_games))) if float(total_games) > 0 else 1
                    games_played_int = int(round(games_played))
                    is_live = float(rem_games) > 0.0
                    completion_factor = (float(games_played) / float(total_games)) if float(total_games) > 0 else 1.0
                    progress_disp = (
                        f"Progress: {games_played_int}/{total_games_int} games played "
                        f"({completion_factor * 100.0:.0f}% complete; {'LIVE' if is_live else 'COMPLETE'})"
                    )

                    with _http_client() as client:
                        conf = client.get(
                            "/matchup-confidence",
                            params={
                                "current_matchup_period": int(matchup_week),
                                "projections": projections_param,
                                "games_played": games_played_int,
                                "total_games": total_games_int,
                            },
                        )
                        conf.raise_for_status()
                        df_conf = pd.DataFrame(conf.json())

                    if not df_conf.empty:
                        df_conf["stat"] = df_conf["stat"].astype(str).str.upper()
                        df_conf_f = df_conf[
                            (df_conf["home_team"].astype(str) == str(home_team))
                            & (df_conf["away_team"].astype(str) == str(away_team))
                        ][["home_team", "away_team", "stat", "home_confidence_pct", "away_confidence_pct"]]
                        sel = sel.merge(
                            df_conf_f,
                            on=["home_team", "away_team", "stat"],
                            how="left",
                        )
            except Exception:
                # If confidence fetch fails, keep rendering without confidence.
                pass

            if "home_confidence_pct" not in sel.columns:
                sel["home_confidence_pct"] = None
            if "away_confidence_pct" not in sel.columns:
                sel["away_confidence_pct"] = None

            # Overall matchup confidence: average confidence_pct across categories the winner team is projected to WIN.
            if "home_confidence_pct" in sel.columns and "away_confidence_pct" in sel.columns:
                winner_avg: Optional[float] = None
                if home_wins > away_wins:
                    win_mask = sel["projected_home_result"] == "W"
                    vals = pd.to_numeric(sel.loc[win_mask, "home_confidence_pct"], errors="coerce").dropna()
                    winner_avg = float(vals.mean()) if not vals.empty else None
                elif away_wins > home_wins:
                    win_mask = sel["projected_away_result"] == "W"
                    vals = pd.to_numeric(sel.loc[win_mask, "away_confidence_pct"], errors="coerce").dropna()
                    winner_avg = float(vals.mean()) if not vals.empty else None
                else:
                    # Overall tie: average both sides' category wins.
                    home_mask = sel["projected_home_result"] == "W"
                    away_mask = sel["projected_away_result"] == "W"
                    vals_home = pd.to_numeric(sel.loc[home_mask, "home_confidence_pct"], errors="coerce").dropna()
                    vals_away = pd.to_numeric(sel.loc[away_mask, "away_confidence_pct"], errors="coerce").dropna()
                    vals = pd.concat([vals_home, vals_away], ignore_index=True)
                    winner_avg = float(vals.mean()) if not vals.empty else None

                winner_avg_disp = f"{winner_avg:.0f}%" if winner_avg is not None else "—"
            else:
                winner_avg_disp = "—"

            if home_wins > away_wins:
                win_score, loss_score = home_wins, away_wins
            elif away_wins > home_wins:
                win_score, loss_score = away_wins, home_wins
            else:
                win_score, loss_score = home_wins, away_wins

            if home_wins > away_wins:
                score_html = (
                    f"<div class='pg-scoreline'>"
                    f"<span class='pg-score-number pg-score-win'>{home_wins}</span>"
                    f"<span class='pg-score-sep'>-</span>"
                    f"<span class='pg-score-number pg-score-loss'>{away_wins}</span>"
                    f"</div>"
                    f"<div class='pg-scoremeta'>Projected record: {home_team} {home_wins}-{away_wins} {away_team} "
                    f"(avg confidence: {winner_avg_disp})<br/>{progress_disp}</div>"
                )
            elif away_wins > home_wins:
                score_html = (
                    f"<div class='pg-scoreline'>"
                    f"<span class='pg-score-number pg-score-loss'>{home_wins}</span>"
                    f"<span class='pg-score-sep'>-</span>"
                    f"<span class='pg-score-number pg-score-win'>{away_wins}</span>"
                    f"</div>"
                    f"<div class='pg-scoremeta'>Projected record: {home_team} {home_wins}-{away_wins} {away_team} "
                    f"(avg confidence: {winner_avg_disp})<br/>{progress_disp}</div>"
                )
            else:
                score_html = (
                    f"<div class='pg-scoreline'>"
                    f"<span class='pg-score-number pg-score-loss'>{home_wins}</span>"
                    f"<span class='pg-score-sep'>-</span>"
                    f"<span class='pg-score-number pg-score-loss'>{away_wins}</span>"
                    f"</div>"
                    f"<div class='pg-scoremeta'>Projected record (Ties: {ties}): {home_team} {home_wins}-{away_wins} {away_team} "
                    f"(avg confidence: {winner_avg_disp})<br/>{progress_disp}</div>"
                )

            st.markdown(score_html, unsafe_allow_html=True)

            stat_order = ["PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"]
            ord_map = {s: i for i, s in enumerate(stat_order)}
            sel["_ord"] = sel["stat"].map(ord_map).fillna(999).astype(int)
            sel = sel.sort_values("_ord").drop(columns=["_ord"])

            pct_stats = {"FG%", "FT%"}

            def _fmt_value(stat: str, v: Any) -> str:
                if v is None or pd.isna(v):
                    return ""
                x = float(v)
                if stat in pct_stats:
                    return f"{(x * 100.0):.2f}%"
                return f"{x:.2f}"

            home_col = home_team
            away_col = away_team

            def _conf_indicator(conf_pct: Any) -> str:
                if conf_pct is None or pd.isna(conf_pct):
                    return ""
                try:
                    c = float(conf_pct)
                except Exception:
                    return ""
                if c > 65:
                    cls = "pg-conf-green"
                elif c >= 40:
                    cls = "pg-conf-yellow"
                else:
                    cls = "pg-conf-red"
                return f"<div class='pg-conf-text {cls}'>{c:.0f}%</div>"

            def _bg_for_result(res: Any) -> str:
                r = (res or "").strip().upper()
                if r == "W":
                    return "#16a34a"
                if r == "L":
                    return "#dc2626"
                return "#6b7280"

            home_conf = (
                sel["home_confidence_pct"] if "home_confidence_pct" in sel.columns else pd.Series([None] * len(sel))
            )
            away_conf = (
                sel["away_confidence_pct"] if "away_confidence_pct" in sel.columns else pd.Series([None] * len(sel))
            )

            # Render as HTML table so the badge + confidence indicator are actually interpreted.
            html = []
            html.append("<div class='pg-card pg-matchup-card'>")
            html.append(
                "<table class='pg-matchup-table'>"
                "<thead>"
                "<tr>"
                "<th class='pg-stat-header'>Stat</th>"
                f"<th class='pg-team-header'>{home_col}</th>"
                f"<th class='pg-team-header'>{away_col}</th>"
                "</tr>"
                "</thead><tbody>"
            )

            for s, hv, hr, hc, av, ar, ac in zip(
                sel["stat"],
                sel["projected_home_score"],
                sel["projected_home_result"],
                home_conf,
                sel["projected_away_score"],
                sel["projected_away_result"],
                away_conf,
            ):
                s_str = str(s)
                value_home = _fmt_value(s_str, hv)
                value_away = _fmt_value(s_str, av)

                badge_home = _wl_badge_html((hr or "").strip().upper())
                badge_away = _wl_badge_html((ar or "").strip().upper())

                conf_home = _conf_indicator(hc)
                conf_away = _conf_indicator(ac)

                home_cell = (
                    f"<div class='pg-cell-center'>"
                    f"{value_home}<br/>"
                    f"<div class='pg-wl-stack'>{badge_home}{conf_home}</div>"
                    f"</div>"
                )
                away_cell = (
                    f"<div class='pg-cell-center'>"
                    f"{value_away}<br/>"
                    f"<div class='pg-wl-stack'>{badge_away}{conf_away}</div>"
                    f"</div>"
                )

                html.append(
                    "<tr>"
                    f"<td class='pg-stat-cell'>{s_str}</td>"
                    f"<td class='pg-team-cell'>{home_cell}</td>"
                    f"<td class='pg-team-cell'>{away_cell}</td>"
                    "</tr>"
                )

            html.append("</tbody></table>")
            html.append("</div>")
            st.markdown("".join(html), unsafe_allow_html=True)

            st.divider()

            if st.button("Get AI Commentary", key="btn_ai_commentary"):
                try:
                    matchup_rows: List[Dict[str, Any]] = []
                    for _, r in sel.iterrows():
                        stat = r.get("stat")
                        home_score = r.get("projected_home_score")
                        away_score = r.get("projected_away_score")
                        result = r.get("projected_home_result")  # home-perspective result
                        # confidence_pct should represent "how confident the winner likely hits"
                        home_conf = r.get("home_confidence_pct")
                        away_conf = r.get("away_confidence_pct")
                        conf = None
                        if result == "W":
                            conf = home_conf
                        elif result == "L":
                            conf = away_conf
                        elif result == "T":
                            # tie: take the higher-confidence side if available
                            vals = [v for v in [home_conf, away_conf] if v is not None]
                            conf = max(vals) if vals else None

                        matchup_rows.append(
                            {
                                "stat": stat,
                                "home_score": home_score,
                                "away_score": away_score,
                                "result": result,
                                "confidence_pct": conf,
                            }
                        )

                    payload = {
                        "home_team": home_team,
                        "away_team": away_team,
                        "matchup_data": matchup_rows,
                    }
                    payload["is_live"] = bool(is_live)

                    # Pull the two teams' player projection rows from the already-loaded
                    # roster data (no extra API calls).
                    rosters_raw = st.session_state.get("rosters_current_raw") or []
                    roster_df = pd.DataFrame(rosters_raw)

                    def _as_float(v: Any) -> float:
                        try:
                            if v is None or pd.isna(v):
                                return 0.0
                            return float(v)
                        except Exception:
                            return 0.0

                    def _team_roster(team: str) -> List[Dict[str, Any]]:
                        if roster_df.empty or "team_name" not in roster_df.columns or "player_name" not in roster_df.columns:
                            return []
                        df = roster_df[roster_df["team_name"].astype(str) == str(team)].copy()
                        if df.empty:
                            return []

                        suffix = projections_param if projections_param == "BBM" else f"Last {projections_param}"

                        out: List[Dict[str, Any]] = []
                        for _, pr in df.iterrows():
                            fgm = _as_float(pr.get(f"Projected FGM {suffix}"))
                            fga = _as_float(pr.get(f"Projected FGA {suffix}"))
                            ftm = _as_float(pr.get(f"Projected FTM {suffix}"))
                            fta = _as_float(pr.get(f"Projected FTA {suffix}"))

                            fg_pct = (fgm / fga) if fga > 0 else 0.0
                            ft_pct = (ftm / fta) if fta > 0 else 0.0

                            out.append(
                                {
                                    "player_name": str(pr.get("player_name", "")).strip(),
                                    "pts": _as_float(pr.get(f"Projected PTS {suffix}")),
                                    "reb": _as_float(pr.get(f"Projected REB {suffix}")),
                                    "ast": _as_float(pr.get(f"Projected AST {suffix}")),
                                    "stl": _as_float(pr.get(f"Projected STL {suffix}")),
                                    "blk": _as_float(pr.get(f"Projected BLK {suffix}")),
                                    "3pm": _as_float(pr.get(f"Projected 3PM {suffix}")),
                                    "games_left": int(round(_as_float(pr.get("num_games_left")))) if pr.get("num_games_left") is not None else None,
                                    "fg_pct": fg_pct,
                                    "ft_pct": ft_pct,
                                    "to": _as_float(pr.get(f"Projected TO {suffix}")),
                                }
                            )
                        return out

                    payload["home_roster"] = _team_roster(home_team)
                    payload["away_roster"] = _team_roster(away_team)

                    payload["projections"] = projections_param

                    with _http_client() as client:
                        resp = client.post("/matchup-commentary", json=payload)
                        if resp.status_code != 200:
                            try:
                                detail = resp.json().get("detail")
                            except Exception:
                                detail = None
                            detail = detail or resp.text or f"HTTP {resp.status_code}"
                            raise RuntimeError(detail)
                        data = resp.json()

                    st.session_state.ai_commentary_text = data.get("commentary")
                    st.session_state.ai_commentary_error = None
                    st.session_state.ai_commentary_matchup_key = selected_matchup
                except Exception as e:
                    st.session_state.ai_commentary_text = None
                    st.session_state.ai_commentary_error = str(e)
                    st.error(st.session_state.ai_commentary_error)

            # Render commentary if it matches the current selection.
            if (
                st.session_state.get("ai_commentary_text")
                and st.session_state.get("ai_commentary_matchup_key") == selected_matchup
            ):
                safe_text = st.session_state.ai_commentary_text or ""
                safe_text_html = html_lib.escape(safe_text).replace("\n", "<br/>")
                st.markdown(
                    f"<div class='pg-ai-box'>"
                    f"<div class='pg-ai-label'>Fantasy Analysis</div>"
                    f"<div class='pg-ai-text'>{safe_text_html}</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            if st.session_state.get("ai_commentary_error"):
                st.error(st.session_state.ai_commentary_error)

    st.subheader("🏆 Power Rankings")
    if st.button("Load power rankings", key="btn_power"):
        try:
            weeks_list = list(range(1, int(matchup_week) + 1))
            weeks_param = ",".join(str(w) for w in weeks_list)
            with _http_client() as client:
                r = client.get("/power-rankings", params={"weeks": weeks_param})
                r.raise_for_status()
                st.session_state.power_rankings = r.json()
                st.session_state.power_rankings_error = None
        except Exception as e:
            st.session_state.power_rankings = None
            msg = _friendly_api_error(e)
            st.session_state.power_rankings_error = msg
            st.error(msg)

    if st.session_state.get("power_rankings_error"):
        st.error(st.session_state.power_rankings_error)

    pr = st.session_state.power_rankings
    if pr:
        df = pd.DataFrame(pr)

        stat_keys = [
            ("pts_rank", "PTS"),
            ("reb_rank", "REB"),
            ("ast_rank", "AST"),
            ("stl_rank", "STL"),
            ("blk_rank", "BLK"),
            ("3pm_rank", "3PM"),
            ("fg_pct_rank", "FG%"),
            ("ft_pct_rank", "FT%"),
            ("to_rank", "TO"),
        ]

        def _rank_pill(val: Any) -> str:
            if val is None or pd.isna(val):
                return "<span style='opacity:0.6;'>—</span>"
            try:
                r = int(val)
            except Exception:
                return "<span style='opacity:0.6;'>—</span>"
            if r <= 3:
                bg = "rgba(34,197,94,0.18)"
                fg = "#22c55e"
                bd = "rgba(34,197,94,0.35)"
            elif r <= 7:
                bg = "rgba(245,158,11,0.16)"
                fg = "#f59e0b"
                bd = "rgba(245,158,11,0.35)"
            else:
                bg = "rgba(239,68,68,0.14)"
                fg = "#ef4444"
                bd = "rgba(239,68,68,0.30)"
            return (
                f"<span style='display:inline-block;padding:2px 8px;border-radius:999px;"
                f"border:1px solid {bd};background:{bg};color:{fg};font-weight:800;font-size:0.78rem;'>#{r}</span>"
            )

        def _change_arrow(v: Any) -> str:
            try:
                x = int(v)
            except Exception:
                x = 0
            if x > 0:
                return f"<span style='color:#22c55e;font-weight:900;'>▲{x}</span>"
            if x < 0:
                return f"<span style='color:#ef4444;font-weight:900;'>▼{abs(x)}</span>"
            return "<span style='color:#9ca3af;font-weight:800;'>—</span>"

        # Render as HTML so pills display properly.
        cols = ["rank", "team", "composite_score", "rank_change"]
        for k, _lbl in stat_keys:
            if k in df.columns:
                cols.append(k)

        view = df[cols].copy()
        view["composite_score"] = pd.to_numeric(view["composite_score"], errors="coerce").round(3)
        view["rank_change"] = view["rank_change"].apply(_change_arrow)
        for k, _lbl in stat_keys:
            if k in view.columns:
                view[k] = view[k].apply(_rank_pill)

        headers = [
            ("rank", "Rank"),
            ("team", "Team"),
            ("composite_score", "Score"),
            ("rank_change", "Δ"),
        ] + [(k, lbl) for k, lbl in stat_keys if k in view.columns]

        html_parts: List[str] = []
        html_parts.append("<div class='pg-card'>")
        html_parts.append("<table class='pg-matchup-table'>")
        html_parts.append("<thead><tr>")
        for _k, lbl in headers:
            html_parts.append(f"<th style='text-align:center;'>{html_lib.escape(lbl)}</th>")
        html_parts.append("</tr></thead><tbody>")
        for _, row in view.iterrows():
            html_parts.append("<tr>")
            for k, _lbl in headers:
                val = row.get(k)
                if k in {"team"}:
                    cell = html_lib.escape(str(val))
                elif k == "composite_score":
                    cell = html_lib.escape("" if val is None or pd.isna(val) else f"{float(val):.3f}")
                elif k == "rank":
                    cell = html_lib.escape(str(val))
                else:
                    # already HTML (pills / arrows)
                    cell = str(val) if val is not None else ""
                html_parts.append(f"<td class='pg-team-cell'>{cell}</td>")
            html_parts.append("</tr>")
        html_parts.append("</tbody></table></div>")
        st.markdown("".join(html_parts), unsafe_allow_html=True)

    st.subheader("🔄 Transactions")
    default_end = date.today()
    default_start = default_end - timedelta(days=7)
    dr = st.date_input(
        "Date range",
        value=(default_start, default_end),
    )
    if st.button("Fetch transactions", key="btn_tx"):
        if not isinstance(dr, tuple) or len(dr) != 2:
            st.warning("Select a start and end date.")
        else:
            start_d, end_d = dr
            try:
                params = {
                    "start": start_d.isoformat(),
                    "end": end_d.isoformat(),
                }
                with _http_client() as client:
                    r = client.get("/transactions", params=params)
                    r.raise_for_status()
                    st.session_state.transactions = r.json()
                    st.session_state.transactions_error = None
            except Exception as e:
                st.session_state.transactions = None
                msg = _friendly_api_error(e)
                st.session_state.transactions_error = msg
                st.error(msg)

    if st.session_state.get("transactions_error"):
        st.error(st.session_state.transactions_error)

    tx = st.session_state.transactions
    if tx:
        st.dataframe(pd.DataFrame(tx), use_container_width=True)


def tab_weekly_recap() -> None:
    st.header("📰 Weekly Recap")

    # Minimal styling to match the AI commentary card.
    st.markdown(
        """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;600&family=Bebas+Neue&display=swap');

.pg-ai-box {
  background: #0b1220;
  border-left: 3px solid #cc0000;
  border: 1px solid rgba(204,0,0,0.35);
  border-radius: 12px;
  padding: 14px 16px;
  margin-top: 12px;
}

.pg-ai-label {
  font-style: italic;
  font-variant: all-small-caps;
  letter-spacing: 0.10em;
  font-size: 12px;
  color: #e6edf3;
  opacity: 0.95;
  margin-bottom: 8px;
}

.pg-ai-text {
  color: #e6edf3;
  white-space: normal;
  line-height: 1.45;
}

.pg-recap-header {
  color: #e6edf3;
  font-weight: 900;
  font-size: 1.1rem;
  margin-top: 10px;
  margin-bottom: 6px;
}
</style>
""",
        unsafe_allow_html=True,
    )

    from backend.league.data_feed import MATCHUP_WEEKS_2025_26

    week_options = sorted(int(w) for w in MATCHUP_WEEKS_2025_26.keys())
    # Guard against `st.session_state["weekly_recap_week"]` being None/invalid (can happen on first load).
    cur = st.session_state.get("weekly_recap_week")
    if cur is None or (isinstance(cur, int) and cur not in week_options):
        st.session_state.weekly_recap_week = week_options[-1] if week_options else 1

    selected_week = st.selectbox("Select Week", options=week_options, key="weekly_recap_week")
    selected_week_int = int(selected_week) if selected_week is not None else (week_options[-1] if week_options else 1)
    meta = MATCHUP_WEEKS_2025_26.get(selected_week_int, {}) or {}
    week_start = meta.get("start")
    week_end = meta.get("end")

    if st.button("Generate Recap", key="btn_weekly_recap"):
        if not week_start or not week_end:
            st.session_state.weekly_recap_text = None
            st.session_state.weekly_recap_error = "Missing week date metadata in MATCHUP_WEEKS_2025_26."
        else:
            try:
                st.session_state.weekly_recap_text = None
                st.session_state.weekly_recap_error = None

                with _http_client() as client:
                    r0 = client.get("/league/settings")
                    r0.raise_for_status()
                    league_settings = r0.json()

                    r1 = client.get("/league/standings")
                    r1.raise_for_status()
                    standings = r1.json()

                    weeks_list = list(range(1, int(selected_week_int) + 1))
                    weeks_param = ",".join(str(w) for w in weeks_list)
                    r2 = client.get("/power-rankings", params={"weeks": weeks_param})
                    r2.raise_for_status()
                    power_rankings = r2.json()

                    r3 = client.get(
                        "/transactions",
                        params={"start": str(week_start), "end": str(week_end)},
                    )
                    r3.raise_for_status()
                    transactions = r3.json()

                    r4 = client.get("/scoreboard/current", params={"scoring_period": int(selected_week_int)})
                    r4.raise_for_status()
                    scoreboard = r4.json()

                    payload = {
                        "week": int(selected_week_int),
                        "league_settings": league_settings,
                        "standings": standings,
                        "power_rankings": power_rankings,
                        "transactions": transactions,
                        "scoreboard": scoreboard,
                        "week_dates": {"start": str(week_start), "end": str(week_end)},
                    }

                    resp = client.post("/league-recap", json=payload)
                    if resp.status_code != 200:
                        try:
                            detail = resp.json().get("detail")
                        except Exception:
                            detail = None
                        detail = detail or resp.text or f"HTTP {resp.status_code}"
                        raise RuntimeError(detail)
                    data = resp.json()

                st.session_state.weekly_recap_text = data.get("recap")
                st.session_state.weekly_recap_error = None
                st.session_state.weekly_recap_week_last_generated = int(selected_week_int)
            except Exception as e:
                st.session_state.weekly_recap_text = None
                st.session_state.weekly_recap_error = _friendly_api_error(e)
                st.error(st.session_state.weekly_recap_error)

    if st.session_state.get("weekly_recap_error"):
        st.error(st.session_state.weekly_recap_error)

    if (
        st.session_state.get("weekly_recap_text")
        and st.session_state.get("weekly_recap_week_last_generated") == int(selected_week_int)
    ):
        safe_text = st.session_state.weekly_recap_text or ""

        section_headers = [
            "HEADLINE",
            "RESULTS",
            "MOVE OF THE WEEK",
            "POWER RANKINGS RECAP",
            "LOOKING AHEAD",
        ]

        def _render_recap_html(text: str) -> str:
            lines = text.splitlines()
            parts: List[str] = ["<div class='pg-ai-box'>", "<div class='pg-ai-label'>Weekly Recap</div>"]
            for line in lines:
                raw = line.strip()
                if not raw:
                    parts.append("<br/>")
                    continue
                upper = raw.upper()
                matched_header = None
                for header in section_headers:
                    if upper.startswith(header):
                        matched_header = header
                        break
                if matched_header:
                    rest = raw[len(matched_header) :].lstrip(":- ").strip()
                    parts.append(f"<div class='pg-recap-header'>{html_lib.escape(matched_header)}</div>")
                    if rest:
                        parts.append(f"<div class='pg-ai-text'>{html_lib.escape(rest)}</div>")
                else:
                    parts.append(f"<div class='pg-ai-text'>{html_lib.escape(raw)}</div>")
            parts.append("</div>")
            return "".join(parts)

        st.markdown(_render_recap_html(safe_text), unsafe_allow_html=True)


def tab_season() -> None:
    st.header("🏆 Season")

    # Reuse the same card styling as other commentary areas.
    st.markdown(
        """
<style>
.pg-card {
  background: #0b1220;
  border: 1px solid #1c2333;
  border-radius: 14px;
  padding: 14px 12px;
  margin: 10px 0;
}
</style>
""",
        unsafe_allow_html=True,
    )

    # League settings are loaded in `main()` for the sidebar; retry here if still missing.
    if st.session_state.get("league_settings") is None:
        _ensure_league_settings()
    if st.session_state.get("league_settings") is None:
        err = st.session_state.get("league_settings_error") or "League settings unavailable."
        st.error(err)
        if st.button("Retry loading league settings", key="btn_season_retry_settings"):
            st.session_state.league_settings_error = None
            _ensure_league_settings()
            st.rerun()
        return

    settings = st.session_state.league_settings or {}
    reg_weeks = int(settings.get("reg_season_count") or 0)
    playoff_teams = int(settings.get("playoff_team_count") or 0)
    current_week = int(settings.get("current_week") or 0)

    # Phase banner.
    if reg_weeks > 0 and current_week > reg_weeks:
        playoff_week = max(1, current_week - reg_weeks)
        banner = f"🏆 Playoffs — Week {playoff_week} of playoffs"
    elif reg_weeks > 0 and current_week > reg_weeks * 0.5:
        banner = f"📅 Mid Season — Week {current_week} of {reg_weeks} regular season weeks"
    else:
        banner = f"🌱 Early Season — Week {current_week} of {reg_weeks or '—'}"

    st.info(banner)

    week_opts = list(range(1, 23))
    default_weeks = [w for w in week_opts if current_week and w <= current_week] or week_opts
    selected_weeks = st.multiselect(
        "Weeks to include",
        options=week_opts,
        default=default_weeks,
        key="season_weeks_multiselect",
    )

    if st.button("Load Season Stats", key="btn_load_season_stats"):
        try:
            if not selected_weeks:
                raise RuntimeError("Select at least one week.")
            weeks_param = ",".join(str(int(w)) for w in selected_weeks)
            with _http_client() as client:
                r = client.get("/season-stats", params={"weeks": weeks_param})
                r.raise_for_status()
                st.session_state.season_stats = r.json()
            st.session_state.season_stats_error = None
        except Exception as e:
            st.session_state.season_stats = None
            st.session_state.season_stats_error = _friendly_api_error(e)
            st.error(st.session_state.season_stats_error)

    if st.session_state.get("season_stats_error"):
        st.error(st.session_state.season_stats_error)

    stats_rows = st.session_state.get("season_stats")
    if not stats_rows:
        return

    df = pd.DataFrame(stats_rows)
    if df.empty or "Team" not in df.columns:
        st.warning("Season stats payload is empty or missing 'Team'.")
        return

    # Section 1 — League Standings
    st.subheader("📊 League Standings")
    stand_cols = ["Team", "Actual Wins", "Actual Losses", "Actual Ties", "Actual Win %"]
    st_df = df.copy()
    for c in ["Actual Win %"]:
        if c in st_df.columns:
            st_df[c] = pd.to_numeric(st_df[c], errors="coerce")
    st_df = st_df.sort_values("Actual Win %", ascending=False) if "Actual Win %" in st_df.columns else st_df
    st_df = st_df.reset_index(drop=True)
    st_df.insert(0, "Rank", st_df.index + 1)
    st_display = st_df[[c for c in ["Rank"] + stand_cols if c in st_df.columns]].copy()

    def _highlight_standings(sr: pd.Series) -> List[str]:
        rank = int(sr.get("Rank") or 0)
        n = len(st_display)
        if playoff_teams and rank <= playoff_teams:
            return ["background-color: rgba(34,197,94,0.12)"] * len(sr)
        if n >= 2 and rank > n - 2:
            return ["background-color: rgba(239,68,68,0.10)"] * len(sr)
        return [""] * len(sr)

    try:
        st.dataframe(st_display.style.apply(_highlight_standings, axis=1), use_container_width=True)
    except Exception:
        st.dataframe(st_display, use_container_width=True)

    # Section 2 — All-Play Standings
    st.subheader("🌐 All-Play Standings")
    ap_cols = ["Team", "Total Wins", "Total Losses", "Total Ties", "Total Win %"]
    ap_df = df.copy()
    if "Total Win %" in ap_df.columns:
        ap_df["Total Win %"] = pd.to_numeric(ap_df["Total Win %"], errors="coerce")
        ap_df = ap_df.sort_values("Total Win %", ascending=False)
    ap_df = ap_df.reset_index(drop=True)
    ap_df.insert(0, "All-Play Rank", ap_df.index + 1)

    # Join actual rank from standings.
    actual_rank_map = dict(zip(st_display["Team"], st_display["Rank"])) if "Team" in st_display.columns else {}
    ap_df["Actual Rank"] = ap_df["Team"].map(actual_rank_map)
    ap_df["Note"] = ""
    try:
        diffs = (pd.to_numeric(ap_df["All-Play Rank"], errors="coerce") - pd.to_numeric(ap_df["Actual Rank"], errors="coerce")).abs()
        # If actual rank is better (smaller) than all-play by >=3 => lucky.
        ap_df.loc[(ap_df["Actual Rank"].notna()) & ((ap_df["Actual Rank"] + 3) <= ap_df["All-Play Rank"]), "Note"] = "🍀 Lucky"
        ap_df.loc[(ap_df["Actual Rank"].notna()) & ((ap_df["All-Play Rank"] + 3) <= ap_df["Actual Rank"]), "Note"] = "😤 Unlucky"
    except Exception:
        pass

    ap_display = ap_df[[c for c in ["All-Play Rank"] + ap_cols + ["Note"] if c in ap_df.columns]].copy()
    st.dataframe(ap_display, use_container_width=True)

    # Section 3 — Stat Leaders (team averages/totals from universe wins output)
    st.subheader("🎯 Stat Leaders")
    leader_cols = ["Team", "PTS", "REB", "AST", "STL", "BLK", "3PM", "TO", "FG%", "FT%"]
    ld = df[[c for c in leader_cols if c in df.columns]].copy()
    if "Team" in ld.columns:
        ld = ld.set_index("Team")

    try:
        sty = ld.style
        for c in [c for c in ld.columns if c != "TO"]:
            sty = sty.background_gradient(subset=[c], cmap="Greens")
        if "TO" in ld.columns:
            sty = sty.background_gradient(subset=["TO"], cmap="Greens_r")
        st.dataframe(sty, use_container_width=True)
    except Exception:
        st.dataframe(ld.reset_index(), use_container_width=True)

    # Section 4 — Luck Index
    st.subheader("🍀 Luck Index")
    li = df.copy()
    for c in ["Actual Win %", "Total Win %"]:
        if c in li.columns:
            li[c] = pd.to_numeric(li[c], errors="coerce")
    if "Actual Win %" in li.columns and "Total Win %" in li.columns:
        li["Win % Ratio"] = (li["Actual Win %"] / li["Total Win %"]).replace([float("inf"), -float("inf")], pd.NA)
    else:
        li["Win % Ratio"] = pd.NA

    def _luck_label(x: Any) -> str:
        try:
            v = float(x)
        except Exception:
            return "—"
        if v >= 1.15:
            return "🍀 Very Lucky"
        if v >= 1.0:
            return "😊 Slightly Lucky"
        if v >= 0.85:
            return "😤 Slightly Unlucky"
        return "💀 Very Unlucky"

    li["Label"] = li["Win % Ratio"].apply(_luck_label)
    li_display_cols = ["Team", "Actual Win %", "Total Win %", "Win % Ratio", "Label"]
    li_disp = li[[c for c in li_display_cols if c in li.columns]].copy()
    if "Win % Ratio" in li_disp.columns:
        li_disp = li_disp.sort_values("Win % Ratio", ascending=False)
    st.dataframe(li_disp.reset_index(drop=True), use_container_width=True)

    # Section 5 — Season Commentary
    st.subheader("🤖 Season Commentary")
    if st.button("Generate Season Commentary", key="btn_season_commentary"):
        try:
            weeks_played = len(selected_weeks)
            payload = {
                "season_stats": stats_rows,
                "weeks_played": int(weeks_played),
                "league_settings": settings,
            }
            with _http_client() as client:
                r = client.post("/season-commentary", json=payload)
                r.raise_for_status()
                data = r.json()
            st.session_state.season_commentary_text = data.get("commentary")
            st.session_state.season_commentary_error = None
            st.session_state.season_commentary_weeks_key = ",".join(str(int(w)) for w in selected_weeks)
        except Exception as e:
            st.session_state.season_commentary_text = None
            st.session_state.season_commentary_error = _friendly_api_error(e)
            st.error(st.session_state.season_commentary_error)

    if st.session_state.get("season_commentary_error"):
        st.error(st.session_state.season_commentary_error)

    weeks_key = ",".join(str(int(w)) for w in selected_weeks)
    if (
        st.session_state.get("season_commentary_text")
        and st.session_state.get("season_commentary_weeks_key") == weeks_key
    ):
        safe_text = st.session_state.season_commentary_text or ""
        safe_text_html = html_lib.escape(safe_text).replace("\n", "<br/>")
        st.markdown(
            f"<div class='pg-ai-box'>"
            f"<div class='pg-ai-label'>Fantasy Analysis</div>"
            f"<div class='pg-ai-text'>{safe_text_html}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


def main() -> None:
    st.set_page_config(
        page_title="PatriotGames Fantasy",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _init_session_state()
    _ensure_league_settings()
    _render_league_sidebar()

    st.title("PatriotGames Fantasy")
    st.caption(f"API: `{API_BASE}` — run the backend in a separate terminal: `uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --reload`")

    tab1, tab2, tab3, tab4 = st.tabs(["Draft Optimizer", "In-Season Dashboard", "📰 Weekly Recap", "🏆 Season"])
    with tab1:
        tab_draft_optimizer()
    with tab2:
        tab_in_season()
    with tab3:
        tab_weekly_recap()
    with tab4:
        tab_season()


if __name__ == "__main__":
    main()
