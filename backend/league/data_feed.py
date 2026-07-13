"""
ESPN Fantasy NBA: Barkley/Woj/Stephen A. Commentary Toolkit
===========================================================

What this does
--------------
- Connects to your ESPN fantasy basketball league (H2H Cats or Points)
- Pulls league meta, standings, schedules, rosters (by date), and transactions
- Builds tidy DataFrames for analysis
- Computes storylines: streaks, stream volume, FAAB heat, trade momentum,
  category edges, schedule difficulty, and matchup drama meters
- Emits a single JSON snapshot + CSVs and a ready-to-use prompt text file
  that you can paste into ChatGPT to generate spicy commentary

Setup
-----
1) pip install -U espn-api pandas numpy python-dateutil pytz
2) If your league is private, capture cookies from espn.com:
   - SWID: looks like {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
   - ESPN_S2: long hex string
3) Set league and credentials in `config.py` (or env: ESPN_LEAGUE_ID, ESPN_SEASON, ESPN_SWID, ESPN_S2)
4) Run: python espn-fantasy-comm-toolkit.py --since 2025-10-01 --to today

Notes
-----
- Works best on current season; historical seasons supported for some endpoints.
- If your league is public, you can omit SWID and ESPN_S2.
- This script saves outputs to ./league_<LEAGUE_ID>/latest/

"""
from __future__ import annotations
import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from typing import List, Optional, Dict, Any, Tuple, Iterable
import re
import unicodedata

import numpy as np
import pandas as pd
from dateutil import parser as dtparser
import pytz
from rapidfuzz import process, fuzz
import re
from typing import Optional
import numpy as np
import pandas as pd
from rapidfuzz import process, fuzz
import hashlib
import json

from dataclasses import dataclass
from typing import Literal, Optional

import numpy as np
import pandas as pd

try:
    from espn_api.basketball import League
except Exception as e:
    raise SystemExit(
        "You need the `espn-api` package. Install with: pip install espn-api"
    )

from backend.league.gateway import espn_get, install_espn_timeout_patch

# Every ESPN call in this module (and anything built on `connect()`/`League`)
# goes through espn-api's internal `requests.get`, which has no timeout. Patch
# it before any request can fire.
install_espn_timeout_patch()

from backend.config import (
    BBM_PROJECTIONS_PATH,
    ESPN_S2,
    LEAGUE_ID,
    PLAYER_RANKINGS_DIR,
    SEASON,
    SWID,
    WEEKLY_PROJECTIONS_DEFAULT_PATH,
)

LONDON_TZ = pytz.timezone("Europe/London")

VALUE_COLS_LONG = ["pV", "3V", "rV", "aV", "sV", "bV", "fg%V", "ft%V", "toV", "League Value"]
VALUE_COLS_WEEKLY = [
    "pV_weekly_proj", "3V_weekly_proj", "rV_weekly_proj", "aV_weekly_proj",
    "sV_weekly_proj", "bV_weekly_proj", "fg%V_weekly_proj", "ft%V_weekly_proj",
    "toV_weekly_proj", "League Value_weekly_proj"
]

MATCHUP_WEEKS_2025_26 = {
    1:  {"start": "2025-10-21", "end": "2025-10-26"},
    2:  {"start": "2025-10-27", "end": "2025-11-02"},
    3:  {"start": "2025-11-03", "end": "2025-11-09"},
    4:  {"start": "2025-11-10", "end": "2025-11-16"},
    5:  {"start": "2025-11-17", "end": "2025-11-23"},
    6:  {"start": "2025-11-24", "end": "2025-11-30"},
    7:  {"start": "2025-12-01", "end": "2025-12-07"},
    8:  {"start": "2025-12-08", "end": "2025-12-14"},
    9:  {"start": "2025-12-15", "end": "2025-12-21"},
    10: {"start": "2025-12-22", "end": "2025-12-28"},
    11: {"start": "2025-12-29", "end": "2026-01-04"},
    12: {"start": "2026-01-05", "end": "2026-01-11"},
    13: {"start": "2026-01-12", "end": "2026-01-18"},
    14: {"start": "2026-01-19", "end": "2026-01-25"},
    15: {"start": "2026-01-26", "end": "2026-02-01"},
    16: {"start": "2026-02-02", "end": "2026-02-08"},
    17: {"start": "2026-02-09", "end": "2026-02-22"},  # All-Star break week (extended)
    18: {"start": "2026-02-23", "end": "2026-03-01"},
    19: {"start": "2026-03-02", "end": "2026-03-08"},
    20: {"start": "2026-03-09", "end": "2026-03-15"}, # Playoff week
    21: {"start": "2026-03-16", "end": "2026-03-22"}, # Playoff week
    22: {"start": "2026-03-23", "end": "2026-03-29"}, # Championship week
}

# Categories where a lower value wins the head-to-head. Every other scoring
# category is higher-is-better. Turnovers are stored as natural positive counts
# throughout the data layer; direction is applied at comparison time only.
LOWER_IS_BETTER_STATS = {"TO"}


def category_result(stat: str, home_score, away_score) -> tuple[str, str]:
    """Return ``(home_result, away_result)`` as 'W'/'L'/'T' for one category.

    ``TO`` is lower-is-better; all other categories are higher-is-better.
    Non-comparable values (e.g. NaN) tie, matching the prior inline behavior.
    """
    if stat in LOWER_IS_BETTER_STATS:
        if home_score < away_score:
            return "W", "L"
        if home_score > away_score:
            return "L", "W"
        return "T", "T"
    if home_score > away_score:
        return "W", "L"
    if home_score < away_score:
        return "L", "W"
    return "T", "T"


@dataclass
class ESPNHandles:
    league: League

@dataclass(frozen=True)
class ProjectionConfig:
    # Stats we need to build raw totals and %s
    counting_stats: tuple[str, ...] = (
        "PTS", "BLK", "AST", "STL", "REB", "3PM",
        "FTA", "FTM", "FGM", "FGA", "TO",
    )

    # The 9-cat stats we score matchup results on
    result_stats: tuple[str, ...] = (
        "PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO"
    )

# --------------------------- HELPERS ----------------------------------------
def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _parse_date(s: str) -> date:
    if s.lower() == "today":
        return datetime.now(LONDON_TZ).date()
    return dtparser.parse(s).date()


def normalize_name(name: str) -> str:
    if pd.isna(name):
        return ""
    # remove accents
    name = unicodedata.normalize("NFKD", str(name))
    name = "".join(ch for ch in name if not unicodedata.combining(ch))
    # lowercase
    name = name.lower()
    # remove periods & extra spaces
    name = re.sub(r"[.']", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def fuzzy_map_names(source_names, target_names, score_cutoff=90):
    """
    For each name in source_names, find best match in target_names.
    Returns a DataFrame with: source, target, score
    """
    target_list = list(target_names)
    matches = []
    for s in source_names:
        if not s:  # empty string
            matches.append((s, None, 0.0))
            continue
        match = process.extractOne(s, target_list, scorer=fuzz.ratio)
        if match is None:
            matches.append((s, None, 0.0))
        else:
            best_name, score, _ = match
            if score >= score_cutoff:
                matches.append((s, best_name, score))
            else:
                matches.append((s, None, score))
    return pd.DataFrame(matches, columns=["player_clean", "proj_name_clean_fuzzy", "match_score"])



def _date_range(start: date, end: date) -> List[date]:
    d = start
    out = []
    while d <= end:
        out.append(d)
        d = d + timedelta(days=1)
    return out


# --------------------------- DATA LAYER -------------------------------------

def connect() -> ESPNHandles:
    """Return (possibly cached) league handles for the configured league.

    When running inside an HTTP request with the request-scoped cache middleware
    active (``ESPNRequestCacheMiddleware``), only the first call constructs a
    new ``League`` (4 ESPN requests); subsequent ``connect()`` calls inside the
    same request reuse the cached handles.
    """
    from backend.league.cache import get_request_cache

    cache = get_request_cache()
    if cache is not None:
        existing = cache.get(LEAGUE_ID, SEASON)
        if existing is not None:
            return existing

    league = League(
        league_id=LEAGUE_ID,
        year=SEASON,
        espn_s2=ESPN_S2,
        swid=SWID,
    )
    handles = ESPNHandles(league=league)

    if cache is not None:
        cache.put(LEAGUE_ID, SEASON, handles)

    return handles


def pull_league_meta(h: ESPNHandles) -> Dict[str, Any]:
    l = h.league
    scoring = getattr(l, "scoringType", None) or l.settings.scoring_type
    return {
        "league_id": l.league_id,
        "season": l.year,
        "league_name": l.settings.name,
        "teams": len(l.teams),
        "scoring_type": scoring,
        "reg_season_weeks": l.settings.reg_season_count,
        "playoff_teams": l.settings.playoff_team_count,
        "trade_deadline": l.settings.trade_deadline,
        "acquisition_type": l.settings.faab,  # FREEAGENT | WAIVERS
        "acquisition_budget": l.settings.acquisition_budget,
    }


def teams_df(h: ESPNHandles) -> pd.DataFrame:
    rows = []
    for t in h.league.teams:
        rows.append({
            "team_id": t.team_id,
            "team_name": t.team_name,
            "owners": t.owners[0]['firstName'] if t.owners else None,
            "division_id": getattr(t, "division_id", None),
            "wins": t.wins,
            "losses": t.losses,
            "ties": t.ties,
            "moves": t.acquisitions,
            "trades": t.trades,
            "drops": t.drops,
            "standing": t.standing,
            # "streak_length": t.streak_length,
            # "streak_type": t.streak_type,  # WIN/LOSS/NONE
            "final_standing": getattr(t, "final_standing", None),
        })
    return pd.DataFrame(rows)


def summarize_moves(trans_df: pd.DataFrame) -> pd.DataFrame:
    df = add_direction_column(trans_df)

    # We only know direction for add/drop rows right now
    df_dir = df[~df["direction"].isna()].copy()

    def agg_move(group: pd.DataFrame) -> pd.Series:
        out = {}
        out["date"] = group["date"].iloc[0]
        out["team_id"] = group["team_id"].iloc[0]
        out["team_name"] = group["team_name"].iloc[0]
        out["activity_id"] = group["activity_id"].iloc[0]

        # Who came and went?
        added = group[group["direction"] == 1]
        dropped = group[group["direction"] == -1]

        out["added_players"] = list(added["player"])
        out["dropped_players"] = list(dropped["player"])

        # Long-term net values
        for col in VALUE_COLS_LONG:
            # sum(direction * value) = added - dropped
            out[f"net_{col}"] = (pd.to_numeric(group[col]) * group["direction"]).sum()
            out[f"added_{col}"] = added[col].sum()
            out[f"dropped_{col}"] = dropped[col].sum()

        # Weekly net values
        """for col in VALUE_COLS_WEEKLY:
            out[f"net_{col}"] = (pd.to_numeric(group[col]) * group["direction"]).sum()
            out[f"added_{col}"] = added[col].sum()
            out[f"dropped_{col}"] = dropped[col].sum()"""

        # Simple “headline” scores for quick takes
        out["net_pV_long_term"] = out["net_League Value"]
        # out["net_pV_this_week"] = out["net_League Value_weekly_proj"]

        return pd.Series(out)

    df_dir['team_id2'] = df_dir['team_id']  # workaround for pandas bug
    df_dir['team_name2'] = df_dir['team_name']  # workaround for pandas bug
    df_dir['activity_id2'] = df_dir['activity_id']  # workaround for pandas bug
    moves_df = (
        df_dir
        .groupby(["team_id2", "team_name2", "activity_id2"], as_index=False)
        .apply(agg_move)
        .reset_index(drop=True)
    )

    # Optional: classify the move direction for quick filtering
    #moves_df["short_term_result"] = np.where(
    #    moves_df["net_pV_this_week"] > 0, "upgrade",
    #    np.where(moves_df["net_pV_this_week"] < 0, "downgrade", "neutral")
    #)
    moves_df["long_term_result"] = np.where(
        moves_df["net_pV_long_term"] > 0, "upgrade",
        np.where(moves_df["net_pV_long_term"] < 0, "downgrade", "neutral")
    )

    return moves_df


def add_bbm_projections(
    rosters_df: pd.DataFrame,
    bbm_df: pd.DataFrame,
    *,
    fuzzy_threshold: int = 80,
    weekly_projections: bool = False
) -> pd.DataFrame:
    """
    Attach BBM weekly projections to `rosters_df` using fuzzy name matching.

    Adds columns:
        PTS BBM, 3PM BBM, REB BBM, AST BBM, STL BBM, BLK BBM,
        FGA BBM, FTA BBM, TO BBM, FGM BBM, FTM BBM
    and
        Projected <STAT> BBM  (same values, but following your projection naming pattern)
    """

    rosters = rosters_df.copy()
    bbm_ = bbm_df.copy()

    # --- name normalisation for matching ---
    def normalize_name(name: Optional[str]) -> str:
        if not isinstance(name, str):
            return ""
        name = name.lower()
        name = re.sub(r"[^a-z\s]", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name

    rosters["name_norm"] = rosters["player_name"].map(normalize_name)
    bbm_["name_norm"] = bbm_["Name"].map(normalize_name)

    # columns we need from BBM (these are in your CSV)
    if weekly_projections:
        stats_cols = ["g", "p/g", "3/g", "r/g", "a/g", "s/g", "b/g",
                      "fg%", "fga/g", "ft%", "fta/g", "to/g"]
    else:
        bbm_.rename(columns={
                    'p': 'p/g',
                    '3': '3/g',
                    'r': 'r/g',
                    'a': 'a/g',
                    's': 's/g',
                    'b': 'b/g',
                    'fga': 'fga/g',
                    'fta': 'fta/g',
                    'to': 'to/g',}, inplace=True)
        stats_cols = ["g", "p/g", "3/g", "r/g", "a/g", "s/g", "b/g",
                      "fg%", "fga/g", "ft%", "fta/g", "to/g"]



    for col in stats_cols:
        if col not in bbm_.columns:
            raise KeyError(f"Expected BBM column '{col}' not found in projections file")

    bbm_names = bbm_["name_norm"].tolist()

    # pre-create columns on roster
    for col in stats_cols:
        rosters[col] = np.nan

    # --- fuzzy match each roster player to BBM Name ---
    for idx, row in rosters.iterrows():
        q = row["name_norm"]
        if not q:
            continue

        match = process.extractOne(q, bbm_names, scorer=fuzz.WRatio)
        if match is None:
            continue

        candidate_name_norm, score, match_idx = match
        if score < fuzzy_threshold:
            # no confident match; leave zeros
            continue

        bbm_row = bbm_.iloc[match_idx]
        for col in stats_cols:
            rosters.at[idx, col] = bbm_row.get(col, np.nan)

    # --- numeric cleanup ---
    for col in stats_cols:
        rosters[col] = pd.to_numeric(rosters[col], errors="coerce").fillna(0.0)

    g = rosters["g"]

    if weekly_projections:
        g = rosters["g"]
    else:
        g = 1

    # per-game * games  -> weekly totals
    pts_total   = g * rosters["p/g"]
    threes_tot  = g * rosters["3/g"]
    reb_total   = g * rosters["r/g"]
    ast_total   = g * rosters["a/g"]
    stl_total   = g * rosters["s/g"]
    blk_total   = g * rosters["b/g"]
    fga_total   = g * rosters["fga/g"]
    fta_total   = g * rosters["fta/g"]
    to_total    = g * rosters["to/g"]

    # FGM / FTM from percentages & attempts
    fgm_total   = rosters["fg%"] * rosters["fga/g"] * g
    ftm_total   = rosters["ft%"] * rosters["fta/g"] * g

    # --- attach BBM totals ---
    rosters["PTS BBM"] = pts_total
    rosters["3PM BBM"] = threes_tot
    rosters["REB BBM"] = reb_total
    rosters["AST BBM"] = ast_total
    rosters["STL BBM"] = stl_total
    rosters["BLK BBM"] = blk_total
    rosters["FGA BBM"] = fga_total
    rosters["FTA BBM"] = fta_total
    rosters["TO BBM"]  = to_total
    rosters["FGM BBM"] = fgm_total
    rosters["FTM BBM"] = ftm_total

    # --- "Projected <STAT> BBM" columns (same pattern as Last 15 / 30) ---
    for stat in ["PTS", "3PM", "REB", "AST", "STL", "BLK",
                 "FGA", "FTA", "TO", "FGM", "FTM"]:
        src = f"{stat} BBM"
        rosters[f"Projected {stat} BBM"] = rosters[src]

    return rosters


def safe_recent_activity(h, limit=200):
    """
    Replacement for league.recent_activity() that avoids the ESPN 404 bug.
    Pulls from the LM transactions feed which is stable.
    """
    url = (
        f"https://fantasy.espn.com/apis/v3/games/fba/seasons/{h.league.year}"
        f"/segments/0/leagues/{h.league.league_id}"
        f"?view=kona_league_communication"
    )

    cookies = {}
    if h.league.espn_s2:
        cookies["espn_s2"] = h.league.espn_s2
    if h.league.swid:
        cookies["SWID"] = h.league.swid

    r = espn_get(url, cookies=cookies)
    r.raise_for_status()

    data = r.json()

    # LM communications include adds, drops, trades, waivers, league notes
    items = data.get("communication", {}).get("topics", [])
    out = []

    for item in items[:limit]:
        try:
            msg = item["messages"][0]["body"]
        except:
            msg = None

        out.append({
            "date": item.get("date", None),
            "type": item.get("type", None),
            "topics": item.get("messages", []),
            "body": msg,
        })

    return out


# Transaction types that represent real, completed player movement worth
# surfacing in the recap. Executed free-agent / waiver acquisitions, standalone
# drops, and completed (accepted / upheld) trades. Draft, future-roster /
# lineup-only, and pending / failed / canceled / declined / vetoed records are
# intentionally excluded.
RECAP_TRANSACTION_TYPES = frozenset({"FREEAGENT", "WAIVER", "TRADE_ACCEPT", "TRADE_UPHOLD"})
# Completed trades: the ACCEPT/UPHOLD records carry status + relatedTransactionId
# but an EMPTY items array. The player-level items (type "TRADE" with
# fromTeamId / toTeamId) live on the linked TRADE_PROPOSAL, which we fetch
# alongside to reconstruct who moved where.
_TRADE_COMPLETION_TYPES = frozenset({"TRADE_ACCEPT", "TRADE_UPHOLD"})
_TRADE_PROPOSAL_TYPE = "TRADE_PROPOSAL"
_EXECUTED_STATUS = "EXECUTED"
_ADD_DROP_ITEM_TYPES = frozenset({"ADD", "DROP"})


def _epoch_ms_to_iso_date(value: Any) -> Optional[str]:
    """ESPN transaction dates are epoch milliseconds; return ``YYYY-MM-DD`` (UTC)."""
    if value is None:
        return None
    try:
        seconds = int(value)
        if seconds > 10**10:  # milliseconds, not seconds
            seconds = seconds / 1000.0
        return pd.to_datetime(seconds, unit="s", utc=True).date().isoformat()
    except (TypeError, ValueError):
        try:
            return pd.to_datetime(str(value), utc=True).date().isoformat()
        except Exception:
            return None


def week_transactions(
    h: "ESPNHandles",
    scoring_period: int,
    types: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Normalized, executed player-movement transactions for one scoring period.

    In this league one ``scoringPeriodId`` equals one matchup week, so a single
    ``mTransactions2`` request returns the whole week's transactions.

    Reads ESPN's ``mTransactions2`` view — the stable transaction feed — through
    the league's own authenticated request helper (``espn_request.league_get``),
    then parses the raw JSON defensively. This replaces ``safe_recent_activity()``,
    which pulled the wrong (communication) view and read a ``League.espn_s2``
    attribute that does not exist on the basketball client, so it always raised.

    Returns one row per player movement:

    - executed FREEAGENT / WAIVER acquisitions and standalone drops
      (``action_type`` ``ADD`` / ``DROP``, owning team from ``teamId``);
    - completed trades. ESPN's ``TRADE_ACCEPT`` / ``TRADE_UPHOLD`` records carry
      the status but an empty ``items`` array; the player-level items live on the
      linked ``TRADE_PROPOSAL`` (``relatedTransactionId``). We follow that link,
      read the proposal's ``TRADE`` items, and attribute each moved player to the
      receiving team (``toTeamId``), with ``from_team_id`` as the counterparty.
      A proposal that is both accepted and upheld is counted once.

    Rows carry ``team_name`` and a stable ``activity_id`` (the fields the recap
    awards layer consumes) plus raw context (``type``, ``player``,
    ``from_team_id`` / ``to_team_id``, ``related_transaction_id``).

    Transport / auth errors from ESPN propagate so callers can distinguish an
    outage from a genuinely quiet week (the recap's capture layer turns them into
    a data-quality warning). Parse-level issues — a missing payload, a trade
    proposal absent from this week's window, an unknown player id — degrade to
    fewer rows instead.
    """
    requested = {str(t).upper() for t in (types if types is not None else RECAP_TRANSACTION_TYPES)}

    # To reconstruct completed trades we also need the proposals they link to.
    fetch_types = set(requested)
    if fetch_types & _TRADE_COMPLETION_TYPES:
        fetch_types.add(_TRADE_PROPOSAL_TYPE)

    params = {"view": "mTransactions2", "scoringPeriodId": int(scoring_period)}
    filters = {"transactions": {"filterType": {"value": sorted(fetch_types)}}}
    headers = {"x-fantasy-filter": json.dumps(filters)}

    data = h.league.espn_request.league_get(params=params, headers=headers)
    raw = [t for t in ((data or {}).get("transactions") or []) if isinstance(t, dict)]
    player_map = getattr(h.league, "player_map", {}) or {}
    team_names = {
        getattr(t, "team_id", None): getattr(t, "team_name", None)
        for t in getattr(h.league, "teams", []) or []
    }
    by_id = {t.get("id"): t for t in raw if t.get("id") is not None}

    def _player(player_id: Any) -> str:
        return player_map.get(player_id, "Unknown")

    rows: List[Dict[str, Any]] = []
    seen_trade_proposals: set = set()

    for txn in raw:
        status = str(txn.get("status") or "").upper()
        txn_type = str(txn.get("type") or "").upper()
        if status != _EXECUTED_STATUS or txn_type not in requested:
            continue

        scoring = txn.get("scoringPeriodId", scoring_period)
        date_iso = _epoch_ms_to_iso_date(txn.get("processDate") or txn.get("proposedDate"))

        if txn_type in _TRADE_COMPLETION_TYPES:
            # Follow the chain to the proposal that holds the player items.
            proposal_id = txn.get("relatedTransactionId")
            if proposal_id in seen_trade_proposals:
                continue  # accepted AND upheld -> count the trade once
            proposal = by_id.get(proposal_id)
            if not proposal:
                # Proposal is outside this week's window; can't attribute players.
                continue
            seen_trade_proposals.add(proposal_id)
            for item in proposal.get("items") or []:
                if not isinstance(item, dict):
                    continue
                player_id = item.get("playerId")
                if not player_id:  # draft-pick-only trade items carry no player
                    continue
                to_team_id = item.get("toTeamId")
                from_team_id = item.get("fromTeamId")
                rows.append(
                    {
                        "activity_id": f"txn-{scoring}-{txn.get('id')}-TRADE-{player_id}",
                        "date": date_iso,
                        "scoring_period": scoring,
                        "team_id": to_team_id,
                        "team_name": team_names.get(to_team_id),
                        "type": txn_type,
                        "action_type": "TRADE",
                        "player": _player(player_id),
                        "player_id": player_id,
                        "bid_amount": None,
                        "status": status,
                        "from_team_id": from_team_id,
                        "to_team_id": to_team_id,
                        "related_transaction_id": proposal_id,
                    }
                )
            continue

        # FREEAGENT / WAIVER: add/drop items carry the owning team at txn level.
        base_team_id = txn.get("teamId")
        for item in txn.get("items") or []:
            if not isinstance(item, dict):
                continue
            action = str(item.get("type") or "").upper()  # ADD / DROP
            if action not in _ADD_DROP_ITEM_TYPES:
                continue
            player_id = item.get("playerId")
            rows.append(
                {
                    "activity_id": f"txn-{scoring}-{txn.get('id')}-{action}-{player_id}",
                    "date": date_iso,
                    "scoring_period": scoring,
                    "team_id": base_team_id,
                    "team_name": team_names.get(base_team_id),
                    "type": txn_type,
                    "action_type": action,
                    "player": _player(player_id),
                    "player_id": player_id,
                    "bid_amount": txn.get("bidAmount"),
                    "status": status,
                    "from_team_id": item.get("fromTeamId"),
                    "to_team_id": item.get("toTeamId"),
                    "related_transaction_id": txn.get("relatedTransactionId"),
                }
            )
    return rows


def standings_df(h: ESPNHandles) -> pd.DataFrame:
    # Many fields available via team; we already include in teams_df.
    df = teams_df(h)
    df["win_pct"] = (df["wins"] + 0.5 * df["ties"]) / (df["wins"] + df["losses"] + df["ties"]).replace(0, np.nan)
    return df.sort_values(["win_pct", "wins"], ascending=False)


def add_projections(player_df, proj_df, fuzzy=False) -> pd.DataFrame:
    player_df = player_df.copy()
    player_df["player_clean"] = player_df["player_name"].map(normalize_name)
    proj_df["proj_name_clean"] = proj_df["Name"].map(normalize_name)

    if fuzzy:
        unmatched = player_df[~player_df["player_clean"].isin(proj_df["proj_name_clean"])]["player_clean"].unique()

        fuzzy_map = fuzzy_map_names(
            source_names=unmatched,
            target_names=proj_df["proj_name_clean"].unique(),
            score_cutoff=75,  # tweak as needed
        )

        print(fuzzy_map.info())

        # bring fuzzy results back onto the player_df
        player_df = player_df.merge(
            fuzzy_map,
            on="player_clean",
            how="left"
        )

        # final key: if exact didn't hit, use fuzzy
        player_df["final_proj_key"] = player_df["player_clean"]
        mask = player_df["final_proj_key"].isna() & player_df["proj_name_clean_fuzzy"].notna()
        player_df.loc[mask, "final_proj_key"] = player_df.loc[mask, "proj_name_clean_fuzzy"]

        merged = player_df.merge(
            proj_df.drop_duplicates(subset=["proj_name_clean"]),
            left_on="final_proj_key",
            right_on="proj_name_clean",
            how="left",
            suffixes=("", "_proj2")  # if needed
        )

        # clean up columns: replace nan proj fields with the fuzzy-joined ones
        #proj_cols = [col for col in proj_df.columns if col != "Name"]
        #for col in proj_cols:
        #    merged.loc[merged[col].isna(), col] = merged.loc[merged[col].isna(), f"{col}_proj2"]
        #merged = merged[[col for col in player_df.columns] + proj_cols]
        return merged

    merged = player_df.merge(
        proj_df,
        left_on="player_clean",
        right_on="proj_name_clean",
        how="left",
        suffixes=("", "_proj")
    )
    return merged


def rosters_df(h: ESPNHandles, on_date: date) -> pd.DataFrame:
    """Roster snapshot for each team on a given date."""
    rows = []
    for t in h.league.teams:
        try:
            roster = t.roster
        except Exception:
            roster = []
        for p in roster:
            rows.append({
                "date": on_date.isoformat(),
                "team_id": t.team_id,
                "team_name": t.team_name,
                "player_name": p.name,
                "pro_team": getattr(p, "proTeam", None),
                "position": ",".join(p.eligibleSlots) if getattr(p, "eligibleSlots", None) else getattr(p, "position", None),
                "injury_status": getattr(p, "injuryStatus", None),
                "on_team": True,
            })
    return pd.DataFrame(rows)


def make_activity_id(adate, bid_amount, action_tuples):
    """
    Deterministic activity id based on date + bid + actions.
    Avoids str(a) truncation and run-to-run instability.
    """
    # Keep stable fields only
    payload = {
        "date": str(adate),
        "bid_amount": bid_amount,
        "actions": sorted(
            [
                (
                    getattr(tup[0], "team_id", None) if len(tup) > 0 else None,
                    tup[1] if len(tup) > 1 else None,
                    tup[2] if len(tup) > 2 else None,
                )
                for tup in (action_tuples or [])
            ],
            key=lambda x: (x[0] or -1, x[1] or "", x[2] or ""),
        ),
    }
    s = json.dumps(payload, sort_keys=True)
    return hashlib.md5(s.encode("utf-8")).hexdigest()


# -----------------------------
# Helpers: direction + counterparty
# -----------------------------
def add_trade_fields(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    direction_map = {
        "ADDED": "IN",
        "WAIVER ADDED": "IN",
        "FREEAGENT ADDED": "IN",
        "DROPPED": "OUT",
        "WAIVER DROPPED": "OUT",
        "TRADED": "OUT",  # the team on the tuple is the sender of that player
    }
    df["direction"] = df["action_type"].map(direction_map).fillna("UNKNOWN")

    # For trades, explicitly record movement
    df["from_team_id"] = pd.NA
    df["from_team_name"] = pd.NA
    df["to_team_id"] = pd.NA
    df["to_team_name"] = pd.NA

    trade_mask = df["action_type"].eq("TRADED")
    for act_id, g in df[trade_mask].groupby("activity_id"):
        teams = g[["team_id", "team_name"]].drop_duplicates()
        if len(teams) != 2:
            df.loc[g.index, ["to_team_id","to_team_name"]] = "AMBIGUOUS"
            continue

        (t1_id, t1_name), (t2_id, t2_name) = teams.values.tolist()

        idx1 = g[g["team_id"] == t1_id].index
        idx2 = g[g["team_id"] == t2_id].index

        # players listed under team are sent BY that team TO the other team
        df.loc[idx1, ["from_team_id","from_team_name"]] = (t1_id, t1_name)
        df.loc[idx1, ["to_team_id","to_team_name"]] = (t2_id, t2_name)

        df.loc[idx2, ["from_team_id","from_team_name"]] = (t2_id, t2_name)
        df.loc[idx2, ["to_team_id","to_team_name"]] = (t1_id, t1_name)

    return df


# -----------------------------
# Helpers: attach projections via exact + fuzzy
# -----------------------------
def attach_projections(
    trans_df: pd.DataFrame,
    proj_df: pd.DataFrame,
    player_col: str = "player_clean",
    proj_name_col: str = "proj_name_clean",
    score_cutoff: int = 85,
    projection_type: str = "season",
) -> pd.DataFrame:
    """
    Generic: merge trans_df with proj_df using exact match,
    then fuzzy-map remaining names and merge again.
    Expects:
      - trans_df[player_col]
      - proj_df[proj_name_col]
      - fuzzy_map_names() returns DF with:
          player_clean, proj_name_clean_fuzzy, fuzzy_score (or similar)
    """
    trans = trans_df.copy()
    proj = proj_df.copy()

    # Exact merge
    merged = trans.merge(
        proj,
        left_on=player_col,
        right_on=proj_name_col,
        how="left",
        suffixes=("", f"_proj_exact"),
    )

    # Build fuzzy mapping for unmatched
    unmatched = merged[merged[proj_name_col].isna()][player_col].dropna().unique()
    if len(unmatched) > 0:
        fuzzy_map = fuzzy_map_names(
            source_names=unmatched,
            target_names=proj[proj_name_col].dropna().unique(),
            score_cutoff=score_cutoff,
        )

        merged = merged.merge(fuzzy_map, on=player_col, how="left")
        merged["final_proj_key"] = merged[proj_name_col]
        mask = merged["final_proj_key"].isna() & merged["proj_name_clean_fuzzy"].notna()
        merged.loc[mask, "final_proj_key"] = merged.loc[mask, "proj_name_clean_fuzzy"]

        # Merge again to attach the projection row for fuzzy matches
        proj_dedup = proj.drop_duplicates(subset=[proj_name_col])
        merged = merged.merge(
            proj_dedup,
            left_on="final_proj_key",
            right_on=proj_name_col,
            how="left",
            suffixes=("", "_proj_fuzzy"),
        )

        # Coalesce: for proj cols, use exact if present else fuzzy
        for col in proj.columns:
            if col in ("Name", proj_name_col):
                continue
            # prefer existing (exact) values
            fuzzy_col = f"{col}_proj_fuzzy"
            if fuzzy_col in merged.columns:
                merged[col] = merged[col].combine_first(merged[fuzzy_col])

    return merged


# -----------------------------
# Main: transactions_df
# -----------------------------
def transactions_df(
    h,
    start,
    end,
    season_projections_df: Optional[pd.DataFrame] = None,
):
    """
    Clean ESPN transactions into a tidy DataFrame.
    Handles:
      - epoch ms timestamps
      - add/drop/waiver/trade actions with player names
      - team objects inside the action tuples
      - date-only filtering
      - stable activity_id
      - trade direction + counterparty
      - projections attached (season + weekly)
    """
    # Pull activity
    try:
        acts = h.league.recent_activity(size=500)
    except Exception:
        acts = safe_recent_activity(h)

    start_d = pd.to_datetime(start).date()
    end_d = pd.to_datetime(end).date()

    rows = []

    for a in acts:
        # ---- Parse timestamp ----
        ts = getattr(a, "date", None)
        try:
            ts_int = int(ts)
            if ts_int > 10**10:  # ms
                ts_int = ts_int / 1000.0
            adate = pd.to_datetime(ts_int, unit="s", utc=True).date()
        except Exception:
            try:
                adate = pd.to_datetime(str(ts), utc=True).date()
            except Exception:
                continue

        # ---- Filter by date ----
        if not (start_d <= adate <= end_d):
            continue

        action_tuples = list(getattr(a, "actions", []) or [])

        # Stable activity id
        act_id = make_activity_id(adate, getattr(a, "bid_amount", None), action_tuples)

        # ---- Parse action tuples ----
        for tup in action_tuples:
            try:
                team_obj, action_type, player_name, *_ = tup
                team_name = getattr(team_obj, "team_name", None)
                team_id = getattr(team_obj, "team_id", None)
            except Exception:
                team_name = None
                team_id = None
                action_type = None
                player_name = None

            rows.append(
                {
                    "date": adate.isoformat(),
                    "team_name": team_name,
                    "team_id": team_id,
                    "action_type": action_type,
                    "player": player_name,
                    "raw_action": str(tup),
                    "bid_amount": getattr(a, "bid_amount", None),
                    "activity_id": act_id,
                }
            )

    trans_df = pd.DataFrame(rows)
    if trans_df.empty:
        return trans_df

    # Safety filter (date-only)
    trans_df = trans_df[
        trans_df["date"].apply(
            lambda d: start_d <= pd.to_datetime(d).date() <= end_d
        )
    ].reset_index(drop=True)

    # Normalize player name for projections
    trans_df["player_clean"] = trans_df["player"].map(normalize_name)

    # Add direction + counterparty for trades
    trans_df = add_trade_fields(trans_df)

    # ---- Attach Season projections (your existing function) ----
    season_proj_df = read_projections_xls(projections_df=season_projections_df)
    season_proj_df["proj_name_clean"] = season_proj_df["Name"].map(normalize_name)



    trans_df = attach_projections(
        trans_df=trans_df,
        proj_df=season_proj_df,
        player_col="player_clean",
        proj_name_col="proj_name_clean",
        score_cutoff=85,
    )

    # ---- Attach Weekly projections ----
    """weekly_proj_df = read_projections_xls("player_rankings/WeeklyProjections.xls")
    weekly_proj_df["proj_name_clean"] = weekly_proj_df["Name"].map(normalize_name)

    trans_df = attach_projections(
        trans_df=trans_df,
        proj_df=weekly_proj_df,
        player_col="player_clean",
        proj_name_col="proj_name_clean",
        score_cutoff=85,
    )"""

    # Optional: keep only the columns you care about
    # (You can add more projection fields after you see what’s useful.)
    base_cols = [
        "date",
        "activity_id",
        "team_id",
        "team_name",
        "action_type",
        "direction",
        "counterparty_team_id",
        "counterparty_team_name",
        "player",
        "player_clean",
        "bid_amount",
        "raw_action",
    ]
    keep = [c for c in base_cols if c in trans_df.columns] + [
        c for c in trans_df.columns if c not in base_cols
    ]
    trans_df = trans_df[keep]

    final_transactions_df = add_direction_column(trans_df)
    moves_df = summarize_moves(final_transactions_df)

    return moves_df


def get_projected_matchup_table(
    h: "ESPNHandles",
    *,
    week: int,
    week_end_date: Optional[str | pd.Timestamp] = None,
    scoring_period: Optional[int] = None,
    projections: str = "BBM",
    to_flipped: bool = False,
    zero_out_out_players: bool = False,
    zero_out_no_games_left: bool = True,
    config: ProjectionConfig = ProjectionConfig(),
) -> pd.DataFrame:
    """
    Build projected matchup table in the normalized format:

    Output columns (projection file):
      - week
      - team
      - opponent
      - stat
      - team_score        (projected)
      - opp_score         (projected)
      - result            ('W','L','T') from team perspective
      - source            ('projected')

    Notes:
      - Assumes get_current_scoreboard returns a matchup grid with home/away teams and stats.
      - Assumes get_current_rosters provides per-player projections columns + num_games_left + injuryStatus.
      - If your league stores TO already flipped (higher TO is better), set to_flipped=True (default).
    """

    # ---------------------------
    # 1) Pull base matchup grid + rosters
    # ---------------------------
    current_scoreboard = get_current_scoreboard(h, scoring_period=scoring_period)
    rosters = get_current_rosters(
        h,
        MATCHUP_WEEKS_2025_26[week]["start"],
        MATCHUP_WEEKS_2025_26[week]["end"],
        current_matchup_period=week,
        projections=projections,
    ).copy()

    # Validate the scoreboard has the matchup mapping we need
    required_scoreboard_cols = {"home_team", "away_team", "stat"}
    missing = required_scoreboard_cols - set(current_scoreboard.columns)
    if missing:
        raise ValueError(f"current_scoreboard missing columns: {missing}")

    # ---------------------------
    # 2) Build projection column map
    # ---------------------------
    # Example: 'Projected PTS BBM' or 'Projected PTS Last 15'
    if projections == "BBM":
        proj_col_map = {s: f"Projected {s} BBM" for s in config.counting_stats}
    else:
        proj_col_map = {s: f"Projected {s} Last {projections}" for s in config.counting_stats}

    # Validate roster contains required projection columns
    missing_proj_cols = [c for c in proj_col_map.values() if c not in rosters.columns]
    if missing_proj_cols:
        raise ValueError(
            "Rosters missing projection columns. "
            f"Expected columns like: {missing_proj_cols[:3]} ..."
        )

    # ---------------------------
    # 3) Zero-out players we don't want to count
    # ---------------------------
    if zero_out_out_players and "injuryStatus" in rosters.columns:
        out_mask = rosters["injuryStatus"].eq("OUT")
        rosters.loc[out_mask, list(proj_col_map.values())] = 0

    if zero_out_no_games_left and "num_games_left" in rosters.columns:
        no_games_mask = rosters["num_games_left"].fillna(0).eq(0)
        rosters.loc[no_games_mask, list(proj_col_map.values())] = 0

    # ---------------------------
    # 4) Aggregate projected future totals by team
    # ---------------------------
    projected_future = (
        rosters
        .groupby("team_name", as_index=False)[list(proj_col_map.values())]
        .sum()
        .rename(columns={v: k for k, v in proj_col_map.items()})  # cols become PTS, BLK, ... TO
        .rename(columns={"team_name": "team"})
    )

    future_long = projected_future.melt(
        id_vars="team", var_name="stat", value_name="future_total"
    )

    # ---------------------------
    # 5) Current totals by team/stat (from current_scoreboard)
    # ---------------------------
    # If your current_scoreboard includes current scores, use them; otherwise treat current as 0.
    # This keeps the function usable even if you generate projections "from scratch".
    has_current = {"current_home_score", "current_away_score"} <= set(current_scoreboard.columns)

    if has_current:
        home_current = (
            current_scoreboard[["home_team", "stat", "current_home_score"]]
            .rename(columns={"home_team": "team", "current_home_score": "current_score"})
        )
        away_current = (
            current_scoreboard[["away_team", "stat", "current_away_score"]]
            .rename(columns={"away_team": "team", "current_away_score": "current_score"})
        )
        current_team_stats = pd.concat([home_current, away_current], ignore_index=True)
    else:
        # If there are no current scores, start from 0 and only add future totals
        teams = pd.unique(pd.concat([current_scoreboard["home_team"], current_scoreboard["away_team"]]))
        stats = pd.unique(current_scoreboard["stat"])
        current_team_stats = pd.DataFrame(
            {"team": np.repeat(teams, len(stats)), "stat": np.tile(stats, len(teams)), "current_score": 0.0}
        )

    # ---------------------------
    # 6) Projected totals = current + future (with TO handling)
    # ---------------------------
    team_totals = current_team_stats.merge(future_long, on=["team", "stat"], how="left")
    team_totals["future_total"] = team_totals["future_total"].fillna(0.0)

    # Your league: TO already flipped => higher TO is better => treat like other stats
    # If NOT flipped (classic 9-cat), set to_flipped=False and subtract future TO.
    if to_flipped:
        team_totals["projected_score"] = team_totals["current_score"] + team_totals["future_total"]
    else:
        is_to = team_totals["stat"].eq("TO")
        team_totals["projected_score"] = team_totals["current_score"] + np.where(
            is_to, -team_totals["future_total"], team_totals["future_total"]
        )

    # ---------------------------
    # 7) Compute FG% and FT% from projected totals
    # ---------------------------
    wide = (
        team_totals.pivot_table(index="team", columns="stat", values="projected_score", aggfunc="first")
        .reset_index()
    )

    # Ensure required columns exist to compute %
    for col in ["FGM", "FGA", "FTM", "FTA"]:
        if col not in wide.columns:
            wide[col] = 0.0

    wide["FG%"] = np.where(wide["FGA"].ne(0), (wide["FGM"] / wide["FGA"]), 0.0)
    wide["FT%"] = np.where(wide["FTA"].ne(0), (wide["FTM"] / wide["FTA"]), 0.0)

    long_all = wide.melt(id_vars="team", var_name="stat", value_name="projected_score")

    # Keep only the 9 scoring cats in the final matchup table
    long_9cat = long_all[long_all["stat"].isin(config.result_stats)].copy()

    # ---------------------------
    # 8) Attach opponents and produce the normalized matchup table
    # ---------------------------
    # Build a "team -> opponent" mapping from current_scoreboard matchups
    pairs = pd.concat([
        current_scoreboard[["home_team", "away_team"]].rename(columns={"home_team": "team", "away_team": "opponent"}),
        current_scoreboard[["away_team", "home_team"]].rename(columns={"away_team": "team", "home_team": "opponent"}),
    ], ignore_index=True).drop_duplicates()

    # Expand to one row per team/stat with opponent attached
    team_stat = long_9cat.merge(pairs, on="team", how="left")

    # Now merge opponent stat scores in to get opp_score
    opp_stat = team_stat[["opponent", "stat", "projected_score"]].rename(
        columns={"opponent": "team", "projected_score": "opp_score"}
    )

    out = team_stat.merge(opp_stat, on=["team", "stat"], how="left")
    out = out.rename(columns={"projected_score": "team_score"})

    # ---------------------------
    # 9) Compute W/L/T from team perspective
    # ---------------------------
    out["result"] = np.select(
        [
            out["team_score"] > out["opp_score"],
            out["team_score"] < out["opp_score"],
        ],
        ["W", "L"],
        default="T",
    )

    out.insert(0, "week", week)
    out["source"] = "projected"

    # final column order (matches your desired standardized format)
    out = out[["week", "team", "opponent", "stat", "team_score", "opp_score", "result", "source"]]

    # Optional: stable sorting for diffs / debugging
    out = out.sort_values(["team", "stat"]).reset_index(drop=True)

    return out

def resolve_roster_week_window(
    week_start_date: Optional[str],
    week_end_date: Optional[str],
    current_matchup_period: Optional[int] = None,
    league_current_week: Optional[int] = None,
) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """Resolve the ``(start, end)`` window used to count a roster's games left.

    Explicit dates win. When either is missing it is derived from the matchup
    period (falling back to the league's current week) via
    ``MATCHUP_WEEKS_2025_26``. The previous hardcoded defaults were inverted —
    ``week_start_date`` (2026-10-15) fell *after* ``week_end_date`` (2026-04-30),
    so ``count_games_in_range`` was always false and every player reported zero
    games left. Returns pandas Timestamps (either may be ``NaT`` if a bound is
    genuinely unresolvable, e.g. an out-of-range period with no explicit date).
    """
    start = week_start_date
    end = week_end_date
    if start is None or end is None:
        period = current_matchup_period if current_matchup_period is not None else league_current_week
        meta = None
        if period is not None:
            try:
                meta = MATCHUP_WEEKS_2025_26.get(int(period))
            except (TypeError, ValueError):
                meta = None
        if meta:
            if start is None:
                start = meta["start"]
            if end is None:
                end = meta["end"]
    return pd.to_datetime(start), pd.to_datetime(end)


def get_current_rosters(
    h: ESPNHandles,
    week_start_date: Optional[str] = None,
    week_end_date: Optional[str] = None,
    bbm_path: Optional[str] = None,
    bbm_df: Optional[pd.DataFrame] = None,
    current_matchup_period: Optional[int] = None,
    projections: str = "BBM",
) -> pd.DataFrame:
    bbm_folder = str(PLAYER_RANKINGS_DIR)
    # Runtime trace: helps verify whether callers are requesting BBM vs 15/30.
    print(
        f"[get_current_rosters] projections={projections!r} current_matchup_period={current_matchup_period!r} "
        f"bbm_df_provided={bbm_df is not None} bbm_path={bbm_path!r}"
    )
    # --- Date setup ---
    # Derive a sane week window (the old hardcoded defaults were inverted, which
    # zeroed games-left for every player when the dates were omitted).
    week_start_date, week_end_date = resolve_roster_week_window(
        week_start_date,
        week_end_date,
        current_matchup_period=current_matchup_period,
        league_current_week=getattr(h.league, "currentMatchupPeriod", None),
    )

    # configurable windows / stats
    WINDOWS = [15, 30]
    BASE_STATS = ["PTS", "BLK", "AST", "STL", "3PM", "FTA", "FTM", "FGM", "FGA", "TO"]

    def get_window_stats(player_stats: dict, window: int) -> dict:
        stats_key = f"2026_last_{window}"
        window_stats = player_stats.get(stats_key, {})
        avg = window_stats.get("avg", {}) or {}

        result = {}
        for stat in BASE_STATS:
            result[stat] = avg.get(stat, 0)

        # REB = OREB + DREB
        oreb = avg.get("OREB", 0)
        dreb = avg.get("DREB", 0)
        result["REB"] = oreb + dreb

        return result

    def count_games_in_range(player) -> int:
        return sum(
            week_start_date <= pd.to_datetime(game["date"]).normalize() <= week_end_date
            for game in player.schedule.values()
        )

    team_rosters = []

    for team in h.league.teams:
        for player in team.roster:
            record = {
                "team_id": team.team_id,
                "team_name": team.team_name,
                "acquisitionType": player.acquisitionType,
                "eligibleSlots": "".join(player.eligibleSlots),
                "injuryStatus": player.injuryStatus,
                "player_name": player.name,
                "nine_cat_averages": "".join(player.nine_cat_averages),
                "playerId": player.playerId,
                "stats_last_15": player.stats.get("2026_last_15", {}),
                "stats_total": player.stats.get("2026_total", {}),
            }

            # per-window stats (Last 15, Last 30, etc.)
            for window in WINDOWS:
                window_stats = get_window_stats(player.stats, window)
                suffix = f" Last {window}"
                for key, value in window_stats.items():
                    record[f"{key}{suffix}"] = value

            record["num_games_left"] = count_games_in_range(player)
            team_rosters.append(record)

    team_rosters = pd.DataFrame(team_rosters)

    # --- Projections from Last 15 / 30 ---
    PROJECTION_STATS = ["PTS", "BLK", "AST", "STL", "REB",
                        "3PM", "FTA", "FGM", "TO", "FGA", "FTM"]

    for window in WINDOWS:
        for stat in PROJECTION_STATS:
            col = f"{stat} Last {window}"
            if col not in team_rosters.columns:
                team_rosters[col] = 0

            team_rosters[col] = pd.to_numeric(team_rosters[col], errors="coerce").fillna(0)

            proj_col = f"Projected {col}"
            if "%" not in col:
                team_rosters[proj_col] = team_rosters[col] * team_rosters["num_games_left"]
            else:
                team_rosters[proj_col] = team_rosters[col]

    # --- Optional: add BBM projections (weekly) ---
    # For "15"/"30" projections we must not read weekly BBM spreadsheets from disk.
    if projections == "BBM":
        if bbm_df is not None:
            team_rosters = add_bbm_projections(team_rosters, bbm_df, fuzzy_threshold=80)
        else:
            path = bbm_path if bbm_path is not None else WEEKLY_PROJECTIONS_DEFAULT_PATH
            if current_matchup_period is not None:
                print(f"Adding BBM projections for matchup period {current_matchup_period} from {path}")
                path = path.replace("WeeklyProjections.xls", f"Week {current_matchup_period + 1} Projections.xls")
            bbm_from_disk = pd.read_excel(path)
            team_rosters = add_bbm_projections(team_rosters, bbm_from_disk, fuzzy_threshold=80)

    return team_rosters


def get_current_scoreboard(h: ESPNHandles, scoring_period: Optional[int] = None) -> pd.DataFrame:
    current_scoreboards = []
    if scoring_period is None or scoring_period <= h.league.currentMatchupPeriod:
        matchups = h.league.box_scores(matchup_period=scoring_period)
        for matchup in matchups:
            try:
                home_team = matchup.home_team.team_name
            except:
                home_team = 'Bye'
            try:
                away_team = matchup.away_team.team_name
            except:
                away_team = 'Bye'
            for stat, stat_value in matchup.away_stats.items():
                current_scoreboards.append({
                    "away_team": away_team,
                    "home_team": home_team,
                    # Turnovers are stored as a natural positive count (fewer is
                    # better). Category direction is applied once by each consumer
                    # (recap canonical_matchups, projected W/L, frontend), not here.
                    "current_home_score": matchup.home_stats[stat].get("value"),
                    "current_away_score": matchup.away_stats[stat].get("value"),
                    "stat": stat,
                    # ESPN's own authoritative result -- 'HOME'/'AWAY'/'UNDECIDED'.
                    # Category-tally winners can disagree with this on a tie that
                    # ESPN resolves by a tiebreak rule (e.g. playoff seed); callers
                    # should prefer this field over their own tally when it's set.
                    "espn_winner": getattr(matchup, "winner", None),
                })
    else:
        matchups = h.league.scoreboard(scoring_period)
        for matchup in matchups:
            home_team = matchup.home_team.team_name
            away_team = matchup.away_team.team_name
            for stat, value in matchup.home_team.stats.items():
                current_scoreboards.append({
                    "away_team": away_team,
                    "home_team": home_team,
                    # Future/unplayed periods: ESPN does not expose live scores yet.
                    "current_home_score": 0,
                    "current_away_score": 0,
                    "stat": stat,
                    "espn_winner": getattr(matchup, "winner", None),
                })


    return pd.DataFrame(current_scoreboards)


def get_projected_scoreboard(
    h: ESPNHandles,
    week_end_date=None,
    current_matchup_period=None,
    projections='BBM',
    bbm_df=None,
) -> pd.DataFrame:
    """
    Compute projected standings and box scores for the week.

    Returns
    -------
    final_week_standings : pd.DataFrame
        Columns: ['team', 'projected_wins', 'projected_losses', 'projected_ties', 'opponent']
    final_scoreboard : pd.DataFrame
        Long format projected scores by team / stat.
        Columns: ['team', 'stat', 'projected_score', 'projected_result']
    current_scoreboard : pd.DataFrame
        Whatever get_current_scoreboard returns.
    """

    # --- Config ---
    COUNTING_STATS = ['PTS', 'BLK', 'AST', 'STL', 'REB', '3PM', 'FTA', 'FTM', 'FGM', 'FGA', 'TO']
    RESULT_STATS   = ['PTS', 'BLK', 'AST', 'STL', 'REB', '3PM', 'FT%', 'FG%', 'TO']

    # If the caller didn't provide a week_end_date, use the configured
    # matchup-week end date so `num_games_left` doesn't accidentally span
    # multiple weeks (which inflates last-N projections).
    if week_end_date is None and current_matchup_period is not None:
        meta = MATCHUP_WEEKS_2025_26.get(int(current_matchup_period))
        if meta and meta.get("end"):
            week_end_date = meta["end"]

    # --- Pull current data ---
    current_scoreboard = get_current_scoreboard(h, scoring_period=current_matchup_period)
    team_rosters = get_current_rosters(
        h,
        pd.to_datetime('now'),
        week_end_date,
        bbm_df=bbm_df,
        current_matchup_period=current_matchup_period,
        projections=projections,
    )
    team_rosters.to_csv(f"week_{current_matchup_period+1}_roster.csv", index=False)  # debug output

    # --- Build projected future stats per team (counting stats only) ---

    # map stat -> source column name
    if projections != 'BBM':
        proj_col_map = {
            stat: f'Projected {stat} Last {projections}'
            for stat in COUNTING_STATS
        }
    else:
        proj_col_map = {
            stat: f'Projected {stat} BBM'
            for stat in COUNTING_STATS
        }

    # zero out projections for OUT players in a vectorized way
    rosters = team_rosters.copy()
    out_mask = rosters['injuryStatus'] == 'OUT'
    if projections != 'BBM':
        for col in proj_col_map.values():
            rosters.loc[out_mask, col] = 0
    # zero out projections for players with no num_games_left
    no_games_mask = rosters['num_games_left'] == 0
    for col in proj_col_map.values():
        rosters.loc[no_games_mask, col] = 0

    # aggregate projections by team
    projected_future_stats = (
        rosters
        .groupby('team_name')[list(proj_col_map.values())]
        .sum()
        .reset_index()
        .rename(columns={v: k for k, v in proj_col_map.items()})  # columns become 'PTS','BLK',...,'TO'
    )

    # --- Current scores per team/stat (home + away) ---

    home_current = (
        current_scoreboard[['home_team', 'stat', 'current_home_score']]
        .rename(columns={'home_team': 'team', 'current_home_score': 'current_score'})
    )

    away_current = (
        current_scoreboard[['away_team', 'stat', 'current_away_score']]
        .rename(columns={'away_team': 'team', 'current_away_score': 'current_score'})
    )

    current_team_stats = pd.concat([home_current, away_current], ignore_index=True)

    # --- Merge current + future to get projected scores per team/stat (raw stats only) ---

    future_long = (
        projected_future_stats
        .melt(id_vars='team_name', var_name='stat', value_name='future_total')
        .rename(columns={'team_name': 'team'})
    )

    team_with_future = current_team_stats.merge(
        future_long,
        on=['team', 'stat'],
        how='left'
    )

    team_with_future['future_total'] = team_with_future['future_total'].fillna(0)

    # Turnovers are now a natural positive count (fewer is better), so the
    # projected total is simply current + future for every stat. Category
    # direction is applied when W/L is decided below, not in the sign here.
    team_with_future['projected_score'] = (
        team_with_future['current_score'] + team_with_future['future_total']
    )

    # --- Pivot to team x stat and compute FG% / FT% ---

    projected_wide = (
        team_with_future
        .pivot_table(index='team', columns='stat', values='projected_score', aggfunc='first')
        .reset_index()
    )

    # percentages from projected FGM/FGA, FTM/FTA
    projected_wide['FG%'] = projected_wide['FGM'] / projected_wide['FGA']
    projected_wide['FT%'] = projected_wide['FTM'] / projected_wide['FTA']

    # long format with all stats (including %)
    projected_long_all = projected_wide.melt(
        id_vars='team', var_name='stat', value_name='projected_score'
    )

    # --- Build projected_records_df: one row per matchup/stat with home/away projected scores ---

    proj_home = projected_long_all.rename(
        columns={'team': 'home_team', 'projected_score': 'home_projected_score'}
    )
    proj_away = projected_long_all.rename(
        columns={'team': 'away_team', 'projected_score': 'away_projected_score'}
    )

    projected_records_df = (
        current_scoreboard
        .merge(proj_home, on=['home_team', 'stat'], how='left')
        .merge(proj_away, on=['away_team', 'stat'], how='left')
    )

    # --- Final projected scoreboard with W/L/T per category ---

    final_projected_scoreboard_rows = []

    for stat in RESULT_STATS:
        stat_df = projected_records_df[projected_records_df['stat'] == stat]

        for _, row in stat_df.iterrows():
            # Determine W/L/T for this matchup & stat. Category direction
            # (TO lower-is-better, all others higher-is-better) is applied once
            # in category_result().
            home_result, away_result = category_result(
                stat, row['home_projected_score'], row['away_projected_score']
            )

            final_projected_scoreboard_rows.extend([
                {
                    "home_team": row['home_team'],
                    "away_team": row['away_team'],
                    "stat": stat,
                    "projected_home_score": row['home_projected_score'],
                    "projected_away_score": row['away_projected_score'],
                    "projected_home_result": home_result,
                    "projected_away_result": away_result,
                },
            ])

    final_scoreboard = pd.DataFrame(final_projected_scoreboard_rows)

    # --- Add opponent column (one opponent per team for this week) ---

    final_scoreboard.to_csv(f'Week {current_matchup_period}_scoreboard.csv', index=False)

    return final_scoreboard


def add_direction_column(trans_df: pd.DataFrame) -> pd.DataFrame:
    df = trans_df.copy()

    ADD_ACTIONS = {"WAIVER ADDED", "FA ADDED"}
    DROP_ACTIONS = {"DROPPED"}
    # For now, leave trades as NaN so we can handle them separately
    df["direction"] = np.select(
        [
            df["action_type"].isin(ADD_ACTIONS),
            df["action_type"].isin(DROP_ACTIONS),
        ],
        [1, -1],
        default=np.nan,  # TRADED etc.
    )
    return df

def matchups_df(h, scoring_period=None):
    try:
        matchups = h.league.box_scores(scoring_period=scoring_period)
    except Exception:
        import logging
        logging.warning(
            "matchups_df: ESPN box_scores failed, returning empty frame",
            exc_info=True,
        )
        matchups = []

    def clean_key(k: str) -> str:
        k = str(k).strip()
        k = k.replace('%', 'pct').replace('/', '_per_')
        k = k.replace(' ', '_').replace('-', '_')
        return k

    # discover all stat keys present across matchups so columns are consistent
    stat_keys = set()
    for m in matchups:
        for side in ("home_stats", "away_stats"):
            stats = getattr(m, side, {}) or {}
            stat_keys.update(stats.keys())
    stat_keys = sorted(stat_keys, key=lambda x: str(x))

    rows = []
    for m in matchups:
        base = {
            "week": scoring_period or h.league.currentMatchupPeriod,
            "is_playoffs": bool(getattr(m, "is_playoff", False)),
            "is_bye": bool(getattr(m, "is_bye", False)),
            "home_team_id": getattr(m.home_team, "team_id", None),
            "home_team": getattr(m.home_team, "team_name", None),
            "away_team_id": getattr(m.away_team, "team_id", None),
            "away_team": getattr(m.away_team, "team_name", None),
            "away_wins": m.away_wins,
            "away_losses": m.away_losses,
            "away_ties": m.away_ties,
            "home_wins": m.home_wins,
            "home_losses": m.home_losses,
            "home_ties": m.home_ties,
            "home_score": f"{m.home_wins}-{m.home_losses}-{m.home_ties}",
            "away_score": f"{m.away_wins}-{m.away_losses}-{m.away_ties}",
        }
        # add category values
        for k in stat_keys:
            ck = clean_key(k)
            hv = (getattr(m, "home_stats", {}) or {}).get(k, {})
            av = (getattr(m, "away_stats", {}) or {}).get(k, {})
            base[f"home_{ck}"] = hv.get("value")
            base[f"away_{ck}"] = av.get("value")
        rows.append(base)

    df = pd.DataFrame(rows)

    return df


# --------------------------- ANALYTICS LAYER --------------------------------

def storyline_metrics(
    teams: pd.DataFrame,
    trans: pd.DataFrame,
    roster_snaps: Optional[pd.DataFrame] = None,
    matchups: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    # -------- Wire heat (last 7 days) --------
    if trans is not None and not trans.empty:
        # robust date handling (works if date is str, date, or Timestamp)
        t = trans.copy()
        t["date"] = pd.to_datetime(t["date"]).dt.normalize()
        cutoff = (pd.Timestamp.now(tz="Europe/London") - pd.Timedelta(days=7)).normalize()
        trans7 = t[t["date"] >= pd.to_datetime(cutoff.asm8).normalize()]
        if not trans7.empty and {"team_name", "action_type"}.issubset(trans7.columns):
            out["wire_heat_last7"] = (
                (trans7[trans7['action_type'].isin(['WAIVER ADDED', 'DROPPED'])].groupby("team_name")["action_type"]
                .count() / 2)
                .sort_values(ascending=False)
                .head(5)
                .to_dict()
            )

    # -------- Closest matchups (category-aware) --------
    if matchups is not None and not matchups.empty:
        m = matchups.copy()

        # categories we’ll score
        count_cats = ["3PM", "AST", "BLK", "PTS", "REB", "STL"]
        turnover_cat = "TO"
        pct_cats = [("FGpct", "FGA", "FGM"), ("FTpct", "FTA", "FTM")]  # (pct_col, att_col, made_col)

        # thresholds that define “still in play” for a typical single slate
        swing_thresh = {"3PM": 3, "AST": 5, "BLK": 2, "PTS": 15, "REB": 8, "STL": 2, "TO": 3}
        pct_flip_thresh_makes = {"FGpct": 3, "FTpct": 3}  # ≤ X extra makes could flip the cat

        rows = []
        for idx, row in m.iterrows():
            in_play = []         # list of cat names that are close
            margins = []         # raw closeness measures (smaller is closer)

            # --- counting cats ---
            for cat in count_cats:
                hd = abs(row[f"home_{cat}"] - row[f"away_{cat}"])
                margins.append(("count", cat, hd))
                if hd <= swing_thresh[cat]:
                    in_play.append(cat)

            # --- turnovers (lower is better, but closeness is plain gap) ---
            to_gap = abs(row["home_TO"] - row["away_TO"])
            margins.append(("count", "TO", to_gap))
            if to_gap <= swing_thresh["TO"]:
                in_play.append("TO")

            # --- percentage cats: compute “makes to flip” approximation ---
            for pct_col, att_col, made_col in pct_cats:
                home_pct = float(row[f"home_{pct_col}"])
                away_pct = float(row[f"away_{pct_col}"])
                home_att = float(row[f"home_{att_col}"])
                away_att = float(row[f"away_{att_col}"])
                home_made = float(row[f"home_{made_col}"])
                away_made = float(row[f"away_{made_col}"])

                # if either side has no attempts, treat as far (needs many attempts)
                total_att = max(1.0, home_att + away_att)

                # How many extra makes for the trailing side to surpass the leader?
                # We use a linearized approximation around current attempts:
                # needed ≈ |pct_diff| * total_att
                pct_diff = abs(home_pct - away_pct)
                makes_to_flip = pct_diff * total_att

                margins.append(("pct", pct_col, makes_to_flip))
                if makes_to_flip <= pct_flip_thresh_makes[pct_col]:
                    in_play.append(pct_col)

            # ---- Build a normalized closeness index (higher = closer) ----
            # Normalize each margin by adding 1 and inverting: score = 1 / (1 + margin_norm)
            # To avoid per-week scale issues, divide by a small constant so scale feels right.
            # You can tune these divisors to your league tempo.
            norm_scores = []
            for kind, cat, val in margins:
                if kind == "pct":
                    divisor = 4.0   # ~“shots to flip”; 4 makes is moderate
                else:
                    # rough scale by stat family
                    divisor_map = {"PTS": 20, "REB": 10, "AST": 8, "3PM": 4, "STL": 3, "BLK": 3, "TO": 4}
                    divisor = divisor_map.get(cat, 8)
                margin_norm = val / divisor
                norm_scores.append(1.0 / (1.0 + margin_norm))

            closeness_index = float(np.mean(norm_scores)) if norm_scores else 0.0

            rows.append({
                "week": int(row["week"]),
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "home_wins": int(row["home_wins"]),
                "away_wins": int(row["away_wins"]),
                "closeness_index": round(closeness_index, 4),
                "cats_in_play": sorted(in_play),
            })

        close_df = pd.DataFrame(rows).sort_values("closeness_index", ascending=False).head(3)
        out["closest_matchups"] = close_df.to_dict(orient="records")

    return out


def make_prompt(meta: Dict[str, Any],
                story: Dict[str, Any],
                matchups: Optional[pd.DataFrame] = None,
                top_n: int = 3) -> str:
    """
    Build a commentary prompt (Barkley/Woj/Stephen A.) with category-level matchup drama.
    Expects matchups_df with the columns listed by the user (home_*/away_* for each stat).
    """

    def pct_flip_cost(h_made, h_att, a_made, a_att) -> int:
        """
        Approx shots needed (extra makes for the trailing side at same attempts) to flip the % category.
        Returns an integer threshold; smaller = closer.
        """
        if (h_att or 0) <= 0 and (a_att or 0) <= 0:
            return 999
        # Current pcts
        hp = h_made / h_att if h_att else 0.0
        ap = a_made / a_att if a_att else 0.0
        diff = abs(hp - ap)
        # Use mean attempts as scale for a quick 'shots-to-flip' proxy
        att = max(1, int(round((h_att + a_att) / 2)))
        # each clean make shifts pct by ~1/att
        return int(np.ceil(diff * att))

    def matchup_closeness_row(r: pd.Series) -> Dict[str, Any]:
        # Counting cats (absolute margin)
        margins = {
            "3PM": abs(r["home_3PM"] - r["away_3PM"]),
            "AST": abs(r["home_AST"] - r["away_AST"]),
            "BLK": abs(r["home_BLK"] - r["away_BLK"]),
            "PTS": abs(r["home_PTS"] - r["away_PTS"]),
            "REB": abs(r["home_REB"] - r["away_REB"]),
            "STL": abs(r["home_STL"] - r["away_STL"]),
            # TO: lower is better; closeness still uses absolute gap
            "TO": abs(r["home_TO"] - r["away_TO"]),
        }

        # Percent cats → approximate “shots to flip”
        fg_flip = pct_flip_cost(r["home_FGM"], r["home_FGA"], r["away_FGM"], r["away_FGA"])
        ft_flip = pct_flip_cost(r["home_FTM"], r["home_FTA"], r["away_FTM"], r["away_FTA"])

        # Thresholds for “close”
        thr = {"3PM": 2, "AST": 5, "BLK": 1, "PTS": 10, "REB": 5, "STL": 1, "TO": 3}
        close_flags = {k: (margins[k] <= thr[k]) for k in margins}
        close_flags["FG%"] = (fg_flip <= 3)
        close_flags["FT%"] = (ft_flip <= 3)

        # Drama score = number of close categories; tie-breaker = sum of normalized tightness
        drama_score = int(sum(close_flags.values()))

        tightness = (
            (thr["3PM"] - margins["3PM"]) / thr["3PM"] +
            (thr["AST"] - margins["AST"]) / thr["AST"] +
            (thr["BLK"] - margins["BLK"]) / thr["BLK"] +
            (thr["PTS"] - margins["PTS"]) / thr["PTS"] +
            (thr["REB"] - margins["REB"]) / thr["REB"] +
            (thr["STL"] - margins["STL"]) / thr["STL"] +
            (thr["TO"]  - margins["TO"])  / thr["TO"]  +
            (3 - fg_flip) / 3 +
            (3 - ft_flip) / 3
        )

        close_list = [k for k, v in close_flags.items() if v]

        return {
            "week": int(r["week"]),
            "home_team": r["home_team"],
            "away_team": r["away_team"],
            "scoreline": f'{int(r["home_wins"])}-{int(r["home_losses"])}-{int(r["home_ties"])} vs '
                         f'{int(r["away_wins"])}-{int(r["away_losses"])}-{int(r["away_ties"])}',
            "close_cats": close_list,
            "drama_score": drama_score,
            "tightness": float(tightness),
        }

    def pick_top_matchups(df: pd.DataFrame, n: int) -> List[Dict[str, Any]]:
        if df is None or df.empty:
            return []
        rows = [matchup_closeness_row(r) for _, r in df.iterrows()]
        # sort by drama_score desc, then tightness desc
        rows.sort(key=lambda x: (x["drama_score"], x["tightness"]), reverse=True)
        return rows[:n]

    # Header
    league_name = meta.get("league_name", f"League {meta.get('league_id')}")
    header = (
        f"League: {league_name} (ID {meta['league_id']}, {meta['season']})\n"
        f"Scoring: {meta.get('scoring_type','?')} • Teams: {meta.get('teams')}\n"
    )

    bullets = []

    # Waiver/FA heat
    if "wire_heat_last7" in story and story["wire_heat_last7"]:
        s = ", ".join([f"{k}: {v} moves" for k, v in story["wire_heat_last7"].items()])
        bullets.append(f"Last 7d wire heat — {s}.")

    # Closest matchups using category closeness
    top_games = pick_top_matchups(matchups, top_n) if matchups is not None else []
    for g in top_games:
        cats = ", ".join(g["close_cats"]) if g["close_cats"] else "—"
        bullets.append(
            f"Week {g['week']} drama ({g['drama_score']} close cats): "
            f"{g['home_team']} vs {g['away_team']} • {g['scoreline']} • Close in [{cats}]."
        )

    style = (
        "\n\nCommentary pack:\n"
        "- Open with 2–3 playful, blunt zingers in **Charles Barkley**'s voice using the bullets.\n"
        "- Drop 2 insider nuggets in **Woj** mode (transactional vibe: waivers/trades/moves).\n"
        "- Finish with a ~20s **Stephen A.** monologue tying the closest matchups and wire heat together.\n"
        "Keep every punchline grounded in the listed stats and categories."
    )

    body = "\n".join(["- " + b for b in bullets]) if bullets else "- (No current storylines computed.)"
    return header + body + style

def _normalize_season_projections_from_raw(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize BBM-style season projection sheet (same logic as former read_excel path)."""
    raw = raw.copy()
    # coerce numerics
    num_cols = ['3/g', 'p/g', 'r/g', 'a/g', 's/g', 'b/g', 'fga/g', 'ft%', 'to/g', 'fta/g', 'fg%', 'LeagV']
    num_cols_rename = {
        '3/g': '3PM',
        'p/g': 'PTS',
        'r/g': 'REB',
        'a/g': 'AST',
        's/g': 'STL',
        'b/g': 'BLK',
        'fga/g': 'FGA',
        'fta/g': 'FTA',
        'fg%': 'FG%',
        'ft%': 'FT%',
        'to/g': 'TO',
        'LeagV': 'League Value',
    }
    for c in num_cols:
        raw[c] = pd.to_numeric(raw[c], errors='coerce')

    raw = raw.rename(columns=num_cols_rename)
    # normalize names
    raw['Player Name'] = (raw['Name']
                         .str.replace(r'[\\.-]', ' ', regex=True)
                         .str.replace(r'\\s+', ' ', regex=True)
                         .str.strip()
                         .str.lower())
    # simple availability factor
    status = raw['Status'].fillna('')
    raw['availability'] = raw['Inj'].isna()  # scale to ~weekly
    return raw


def read_projections_xls(
    path: Optional[str] = None,
    projections_df: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Load and normalize season BBM projections.

    If ``projections_df`` is provided, it is normalized in place of reading from disk.
    Otherwise reads from ``path``, or ``BBM_PROJECTIONS_PATH`` when ``path`` is None.
    """
    if projections_df is not None:
        raw = projections_df.copy()
    elif path is None:
        path = BBM_PROJECTIONS_PATH
        raw = pd.read_excel(path, dtype=str)  # sheet name if needed
    else:
        raw = pd.read_excel(path, dtype=str)
    return _normalize_season_projections_from_raw(raw)


def attach_projections_to_movesets(move_sets: pd.DataFrame, proj: pd.DataFrame, cat_weights=None):
    if cat_weights is None:
        cat_weights = {'3PM':1,'PTS':1,'REB':1,'AST':1,'STL':1,'BLK':1,'FG%':1,'FT%':1,'TO':-1}
    p = proj.set_index('player_key')

    def zsum(player_list):
        keys = [normalize_name(k) for k in player_list]  # your normalize function
        sub = p.reindex(keys)
        if 'z_sum' not in sub:
            # compute simple z-sum on the fly if needed
            zs = []
            for col,w in cat_weights.items():
                # assume per-cat z exists or compute from projections baseline earlier
                zs.append(w * sub[f'z_{col}'])
            sub['z_sum'] = np.nansum(zs, axis=0)
        return float(sub['z_sum'].fillna(0).sum())

    move_sets = move_sets.copy()
    move_sets['mis_raw'] = move_sets['added_players'].apply(zsum) - move_sets['dropped_players'].apply(zsum)
    # availability-adjusted
    def zsum_av(player_list):
        keys = [normalize_name(k) for k in player_list]
        sub = p.reindex(keys)
        return float((sub['z_sum'] * sub['availability']).fillna(0).sum())
    move_sets['mis_adj'] = move_sets['added_players'].apply(zsum_av) - move_sets['dropped_players'].apply(zsum_av)
    # basic risk flag
    move_sets['risk_flag'] = move_sets['mis_adj'] < move_sets['mis_raw'] - 0.5
    return move_sets


@dataclass(frozen=True)
class MatchupFormatConfig:
    # The 9 cats to score
    result_stats: tuple[str, ...] = ("PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO")


def emit_current_matchup_table(
    current_scoreboard: pd.DataFrame,
    *,
    week: int,
    config: MatchupFormatConfig = MatchupFormatConfig(),
) -> pd.DataFrame:
    """
    Convert get_current_scoreboard() output into normalized matchup format.

    Input schema (your current_scoreboard):
      - away_team, home_team, current_home_score, current_away_score, stat

    Output schema:
      - week, team, opponent, stat, team_score, opp_score, result, source
    """

    required = {"away_team", "home_team", "current_home_score", "current_away_score", "stat"}
    missing = required - set(current_scoreboard.columns)
    if missing:
        raise ValueError(f"current_scoreboard missing required columns: {missing}")

    # Keep only the 9 cats we care about (prevents extra stats like FGM/FGA from slipping in)
    df = current_scoreboard[current_scoreboard["stat"].isin(config.result_stats)].copy()

    # Home perspective rows
    home_rows = df.rename(
        columns={
            "home_team": "team",
            "away_team": "opponent",
            "current_home_score": "team_score",
            "current_away_score": "opp_score",
        }
    )[["team", "opponent", "stat", "team_score", "opp_score"]]

    # Away perspective rows
    away_rows = df.rename(
        columns={
            "away_team": "team",
            "home_team": "opponent",
            "current_away_score": "team_score",
            "current_home_score": "opp_score",
        }
    )[["team", "opponent", "stat", "team_score", "opp_score"]]

    out = pd.concat([home_rows, away_rows], ignore_index=True)

    # Determine W/L/T from team perspective
    out["result"] = np.select(
        [out["team_score"] > out["opp_score"], out["team_score"] < out["opp_score"]],
        ["W", "L"],
        default="T",
    )

    out.insert(0, "week", week)
    out["source"] = "current"

    # Stable sort
    out = out[["week", "team", "opponent", "stat", "team_score", "opp_score", "result", "source"]]
    out = out.sort_values(["team", "stat"]).reset_index(drop=True)

    return out


def group_move_sets(trans_df, window='3min'):
    df = trans_df.copy()
    df['ts'] = pd.to_datetime(df['timestamp_utc'])
    df['bucket'] = df.groupby('team_name')['ts'].transform(lambda s: (s - s.min()).dt.total_seconds().floordiv(60).floordiv(int(window[:-3])))
    # or round to minute: s.dt.floor('min')
    gcols = ['team_name', 'bucket']
    agg = {
        'action_type': list,
        'player_name': list,
        'via': lambda s: s.mode().iat[0] if len(s) else None,
        'bid_amount': 'sum',
        'counterparty_team': lambda s: s.dropna().unique().tolist(),
        'ts': 'min'
    }
    ms = df.groupby(gcols, as_index=False).agg(agg)
    ms.rename(columns={'bid_amount':'faab_spend_total', 'ts':'timestamp_utc'}, inplace=True)
    # split players into added/dropped lists
    ms['added_players']  = [ [p for a,p in zip(at,pl) if a in ('ADD','CLAIM','TRADE_IN')]  for at,pl in zip(ms['action_type'], ms['player_name']) ]
    ms['dropped_players']= [ [p for a,p in zip(at,pl) if a in ('DROP','TRADE_OUT')] for at,pl in zip(ms['action_type'], ms['player_name']) ]
    return ms


def build_transactions_summary(moves_df: pd.DataFrame, proj_df: pd.DataFrame) -> dict:
    """
    Build compact, LLM-friendly transaction summaries from the moves_df output.
    Returns dict of DataFrames:
      - team_activity
      - top_added
      - top_dropped
      - top_move_sets
      - bottom_move_sets
    """
    if moves_df is None or moves_df.empty:
        return {
            "team_activity": pd.DataFrame(),
            "top_added": pd.DataFrame(),
            "top_dropped": pd.DataFrame(),
            "top_move_sets": pd.DataFrame(),
            "bottom_move_sets": pd.DataFrame(),
        }

    df = moves_df.copy()

    # --- Projection map (player -> League Value) ---
    proj = proj_df.copy()
    if "Name" in proj.columns and "League Value" in proj.columns:
        proj["player_clean"] = proj["Name"].map(normalize_name)
        proj["League Value"] = pd.to_numeric(proj["League Value"], errors="coerce")
        proj_map = proj.set_index("player_clean")["League Value"]
    else:
        proj_map = pd.Series(dtype=float)

    # --- Team activity summary ---
    def _len_list(x):
        return len(x) if isinstance(x, list) else 0

    df["adds_count"] = df["added_players"].apply(_len_list)
    df["drops_count"] = df["dropped_players"].apply(_len_list)
    df["net_League Value"] = pd.to_numeric(df.get("net_League Value", 0), errors="coerce").fillna(0)

    team_activity = (
        df.groupby("team_name", as_index=False)
        .agg(
            moves_count=("activity_id", "count"),
            adds=("adds_count", "sum"),
            drops=("drops_count", "sum"),
            net_league_value=("net_League Value", "sum"),
        )
        .sort_values(["moves_count", "net_league_value"], ascending=False)
    )

    # --- Top move sets (net value) ---
    move_cols = ["date", "team_name", "added_players", "dropped_players", "net_League Value", "long_term_result"]
    top_move_sets = (
        df[move_cols]
        .sort_values("net_League Value", ascending=False)
        .head(5)
        .reset_index(drop=True)
    )
    bottom_move_sets = (
        df[move_cols]
        .sort_values("net_League Value", ascending=True)
        .head(5)
        .reset_index(drop=True)
    )

    # --- Top added / dropped players by League Value ---
    def _explode_players(col_name: str, direction: str) -> pd.DataFrame:
        rows = []
        for _, row in df.iterrows():
            players = row.get(col_name, [])
            if not isinstance(players, list):
                continue
            for p in players:
                p_clean = normalize_name(p)
                lv = proj_map.get(p_clean, np.nan) if not proj_map.empty else np.nan
                rows.append({
                    "date": row.get("date"),
                    "team_name": row.get("team_name"),
                    "player": p,
                    "direction": direction,
                    "league_value": lv,
                })
        return pd.DataFrame(rows)

    added = _explode_players("added_players", "ADD")
    dropped = _explode_players("dropped_players", "DROP")

    top_added = (
        added.sort_values("league_value", ascending=False)
        .head(10)
        .reset_index(drop=True)
    ) if not added.empty else pd.DataFrame()

    top_dropped = (
        dropped.sort_values("league_value", ascending=False)
        .head(10)
        .reset_index(drop=True)
    ) if not dropped.empty else pd.DataFrame()

    return {
        "team_activity": team_activity,
        "top_added": top_added,
        "top_dropped": top_dropped,
        "top_move_sets": top_move_sets,
        "bottom_move_sets": bottom_move_sets,
    }


# --------------------------- IO ORCHESTRATION -------------------------------

def run(
    since: date,
    until: date,
    outdir: Optional[str] = None,
    week_start_date: Optional[str] = None,
    week_end_date: Optional[str] = None,
    current_matchup_period=None,
    *,
    season_projections_df: Optional[pd.DataFrame] = None,
    bbm_weekly_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    h = connect()

    cs = get_current_scoreboard(h, scoring_period=current_matchup_period)
    current_tbl = emit_current_matchup_table(cs, week=current_matchup_period)
    current_tbl.to_csv(f"Week_{current_matchup_period}_Current_Matchup_Table.csv", index=False)

    # PROJECTIONS (for same week, or next week)
    proj_tbl = get_projected_matchup_table(
        h, week=current_matchup_period + 1, scoring_period=current_matchup_period+ 1, week_end_date=week_end_date, projections="BBM", to_flipped=False
    )
    proj_tbl.to_csv(f"Week_{current_matchup_period + 1}_Projected_Matchup_Table.csv", index=False)

    meta = pull_league_meta(h)

    if outdir is None:
        outdir = os.path.join(f"league_{meta['league_id']}", "latest")
    _ensure_dir(outdir)

    # Core pulls
    teams = teams_df(h)
    standings = standings_df(h)
    # Rosters: snapshot only for `until` date by default; you can extend to the whole range
    roster = rosters_df(h, on_date=until)
    trans = transactions_df(h, start=since, end=until, season_projections_df=season_projections_df)
    matchups = matchups_df(h, scoring_period=None)

    current_roster = get_current_rosters(
        h, week_start_date, week_end_date, bbm_df=bbm_weekly_df, projections="BBM"
    )
    final_scoreboard = get_projected_scoreboard(h,
                                                                                           week_end_date=week_end_date,
                                                                                           current_matchup_period=current_matchup_period)

    # Storylines
    story = storyline_metrics(teams, trans, roster, matchups)

    # Transaction summaries (LLM-friendly)
    proj_df = read_projections_xls(projections_df=season_projections_df)
    trans_summary = build_transactions_summary(trans, proj_df)

    # Save CSVs
    teams.to_csv(os.path.join(outdir, f"{week_start_date} teams.csv"), index=False)
    standings.to_csv(os.path.join(outdir, f"{week_start_date} standings.csv"), index=False)
    roster.to_csv(os.path.join(outdir, f"{week_start_date} roster_snapshot.csv"), index=False)
    trans.to_csv(os.path.join(outdir, f"{week_start_date} transactions.csv"), index=False)
    matchups.to_csv(os.path.join(outdir, f"{week_start_date} matchups.csv"), index=False)
    final_scoreboard.to_csv(os.path.join(outdir, f"{week_start_date} projected_scoreboard.csv"), index=False)
    current_roster.to_csv(os.path.join(outdir, f"{week_start_date} current_rosters.csv"), index=False)

    # Save transaction summary tables
    trans_summary["team_activity"].to_csv(os.path.join(outdir, f"{week_start_date} transactions_team_activity.csv"), index=False)
    trans_summary["top_added"].to_csv(os.path.join(outdir, f"{week_start_date} transactions_top_added.csv"), index=False)
    trans_summary["top_dropped"].to_csv(os.path.join(outdir, f"{week_start_date} transactions_top_dropped.csv"), index=False)
    trans_summary["top_move_sets"].to_csv(os.path.join(outdir, f"{week_start_date} transactions_top_moves.csv"), index=False)
    trans_summary["bottom_move_sets"].to_csv(os.path.join(outdir, f"{week_start_date} transactions_bottom_moves.csv"), index=False)

    # Snapshot JSON & prompt
    snapshot = {
        "meta": meta,
        "story": story,
    }
    snapshot["transactions_summary"] = {
        "team_activity": trans_summary["team_activity"].to_dict(orient="records"),
        "top_added": trans_summary["top_added"].to_dict(orient="records"),
        "top_dropped": trans_summary["top_dropped"].to_dict(orient="records"),
        "top_move_sets": trans_summary["top_move_sets"].to_dict(orient="records"),
        "bottom_move_sets": trans_summary["bottom_move_sets"].to_dict(orient="records"),
    }
    with open(os.path.join(outdir, "league_snapshot.json"), "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2)

    prompt = make_prompt(meta, story)
    with open(os.path.join(outdir, "commentary_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(prompt)

    return {
        "outdir": outdir,
        "files": [
            "teams.csv",
            "standings.csv",
            "roster_snapshot.csv",
            "transactions.csv",
            "matchups.csv",
            "transactions_team_activity.csv",
            "transactions_top_added.csv",
            "transactions_top_dropped.csv",
            "transactions_top_moves.csv",
            "transactions_bottom_moves.csv",
            "league_snapshot.json",
            "commentary_prompt.txt",
        ],
    }


# --------------------------- CLI -------------------------------------------
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="ESPN Fantasy NBA commentary toolkit")
    ap.add_argument("--since", default="2025-10-01", help="Start date YYYY-MM-DD or 'today'")
    ap.add_argument("--to", dest="until", default="today", help="End date YYYY-MM-DD or 'today'")
    ap.add_argument("--outdir", default=None, help="Optional output directory")
    args = ap.parse_args()



    since = _parse_date(args.since)
    until = _parse_date(args.until)

    current_matchup_period = 21  # set to None to use current week
    week_start_date = MATCHUP_WEEKS_2025_26[current_matchup_period]["start"]
    week_end_date = MATCHUP_WEEKS_2025_26[current_matchup_period]["end"]

    info = run(since, until, args.outdir, week_start_date, week_end_date, current_matchup_period)
    print("Saved:", os.path.abspath(info["outdir"]))
    for f in info["files"]:
        print(" -", f)
