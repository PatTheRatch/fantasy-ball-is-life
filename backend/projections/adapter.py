"""Projection adapter protocol + adapter implementations.

P-1 ships with ``EspnAdapter`` — an ESPN-native, no-upload-required
projection source that turns ESPN's own rolling stat averages (Last 15 /
Last 30 day splits) into the canonical ``PlayerProjection`` shape.

Design per ``docs/specs/PROJECTION_SOURCE_FRAMEWORK.md``, Design sketch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

import pandas as pd


# ---------------------------------------------------------------------------
# Canonical schema (§3 Data model)
# ---------------------------------------------------------------------------

@dataclass
class PlayerProjection:
    """One row per player per source upload / projection set.

    The canonical shape every adapter must produce.  Consumers
    (optimizer, projected scoreboard, matchup confidence, recaps)
    read *only* these fields — never source-specific column names
    like ``p/g`` or ``３/g``.
    """

    player_key: str          # normalized name key (existing normalize_name)
    display_name: str        # as provided by the source
    team: Optional[str] = None       # NBA team code
    positions: list[str] = field(default_factory=list)  # e.g. ["PG","SG"]

    # Projected volume
    games: Optional[float] = None    # projected games in chosen horizon
    minutes_pg: Optional[float] = None

    # Per-game counting stats
    pts_pg: float = 0.0
    reb_pg: float = 0.0
    ast_pg: float = 0.0
    stl_pg: float = 0.0
    blk_pg: float = 0.0
    tpm_pg: float = 0.0     # 3PM per game
    to_pg: float = 0.0      # turnovers per game

    # Attempts needed for FG% / FT% math
    fga_pg: float = 0.0
    fta_pg: float = 0.0

    # Source percentages (may be None if the source doesn't provide them)
    fg_pct: Optional[float] = None
    ft_pct: Optional[float] = None

    # Metadata
    value: Optional[float] = None   # source's overall value/rank
    injury_status: Optional[str] = None

    # Non-canonical metadata (used by live adapters to attach context
    # that consumers need, e.g. the fantasy roster team for aggregation)
    roster_team: Optional[str] = None  # fantasy team name (ESPN adapter)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class ProjectionAdapter(Protocol):
    """A source that can turn its native format into ``PlayerProjection`` rows.

    For file-based adapters (BBM, Hashtag): ``detect()`` sniffs headers,
    ``parse()`` normalises the file.

    For live API adapters (ESPN): ``detect()`` trivially returns high
    confidence — it isn't file-based and is always available.  ``parse()``
    takes ``*args, **kwargs`` specific to the source rather than a file
    path (e.g. ESPN handles + window).  The structural protocol only
    requires that ``parse`` exist and return ``list[PlayerProjection]``;
    callers should know which adapter they hold and call it accordingly.
    """

    source_id: str
    supported_horizons: list[str]

    def detect(self, file: Any = None) -> float:
        """Sniff a file for this adapter's format.  0–1 confidence.

        Live sources that aren't file-based may return 1.0 unconditionally.
        """
        ...

    def parse(self, file: Any = None, **kwargs: Any) -> list[PlayerProjection]:
        """Normalise into canonical ``PlayerProjection`` rows.

        For file adapters ``file`` is a path or file-like.  For live
        adapters it may be ``None`` with extra keyword args carrying the
        connection context (e.g. ``handles``, ``window``, ``week_end_date``).
        """
        ...


# ---------------------------------------------------------------------------
# EspnAdapter — P-1
# ---------------------------------------------------------------------------

# Column-set needed per stat category.  REB is derived (OREB + DREB) and
# not listed here because ESPN provides OREB/DREB separately.
_BASE_STATS = ["PTS", "BLK", "AST", "STL", "3PM", "FTA", "FTM", "FGM", "FGA", "TO"]


class EspnAdapter:
    """Turn ESPN rolling-stat averages into canonical projections.

    ``horizon='week'`` only — the draft optimizer's ``horizon='season'`` need
    is structurally impossible from rolling Last-N averages (no games played
    yet at draft time — this is a hard constraint, not a TODO).

    The math is a straight port of the existing implementation at
    ``backend/league/data_feed.py:get_current_rosters()`` (~L1391–1502).

    Parameters
    ----------
    window: ``15`` or ``30`` — which rolling split to read (Last 15 / Last 30).
        Defaults to 15.  The existing UI toggle between 15/30 keeps working
        because callers pass the window explicitly.
    """

    source_id: str = "espn"
    supported_horizons: list[str] = ["week"]

    def __init__(self, window: int = 15) -> None:
        if window not in (15, 30):
            raise ValueError(f"window must be 15 or 30, got {window}")
        self.window = window

    # ---- protocol ---------------------------------------------------------

    def detect(self, file: Any = None) -> float:
        """Always available — not file-based."""
        return 1.0

    def parse(
        self,
        file: Any = None,
        *,
        handles: Any = None,        # ESPNHandles
        week_end_date: Optional[str] = None,
        week_start_date: Optional[str] = None,
        current_matchup_period: Optional[int] = None,
    ) -> list[PlayerProjection]:
        """Build projections from live ESPN roster data.

        Requires ``handles`` (``ESPNHandles``).  The other params
        control the game-counting window and are forwarded through to
        ``resolve_roster_week_window`` / ``_count_games_in_range``.

        Returns one ``PlayerProjection`` per rostered player (active
        and bench).  OUT players get zeroed projections.
        """
        # Import locally to avoid coupling the whole data_feed module at
        # adapter import time.
        from backend.league.data_feed import normalize_name, resolve_roster_week_window

        if handles is None:
            raise ValueError("EspnAdapter.parse() requires `handles` (ESPNHandles)")

        league = handles.league
        # Resolve the game-counting window
        week_start_dt, week_end_dt = resolve_roster_week_window(
            week_start_date,
            week_end_date,
            current_matchup_period=current_matchup_period,
            league_current_week=getattr(league, "currentMatchupPeriod", None),
        )

        window = self.window
        stats_key = f"2026_last_{window}"

        results: list[PlayerProjection] = []

        for team in league.teams:
            for player in team.roster:
                name = player.name
                player_key = normalize_name(name)

                # --- per-game averages from the rolling split ---
                pstats = player.stats.get(stats_key, {})
                avg = pstats.get("avg", {}) or {}

                pts_pg   = float(avg.get("PTS", 0) or 0)
                blk_pg   = float(avg.get("BLK", 0) or 0)
                ast_pg   = float(avg.get("AST", 0) or 0)
                stl_pg   = float(avg.get("STL", 0) or 0)
                tpm_pg   = float(avg.get("3PM", 0) or 0)
                fta_pg   = float(avg.get("FTA", 0) or 0)
                ftm_pg   = float(avg.get("FTM", 0) or 0)
                fgm_pg   = float(avg.get("FGM", 0) or 0)
                fga_pg   = float(avg.get("FGA", 0) or 0)
                to_pg    = float(avg.get("TO", 0) or 0)
                oreb_pg  = float(avg.get("OREB", 0) or 0)
                dreb_pg  = float(avg.get("DREB", 0) or 0)
                reb_pg   = oreb_pg + dreb_pg

                # derived percentages (may be zero if no attempts)
                fg_pct: Optional[float] = (fgm_pg / fga_pg) if fga_pg > 0 else None
                ft_pct: Optional[float] = (ftm_pg / fta_pg) if fta_pg > 0 else None

                # --- games remaining this week ---
                games = _count_games_in_range(player, week_start_dt, week_end_dt)

                # --- positions ---
                positions = list(player.eligibleSlots) if hasattr(player, "eligibleSlots") else []

                # --- injury ---
                injury = getattr(player, "injuryStatus", None)
                injury_str = str(injury) if injury else None

                proj = PlayerProjection(
                    player_key=player_key,
                    display_name=name,
                    team=getattr(player, "proTeam", None),
                    positions=positions,
                    games=float(games),
                    minutes_pg=None,      # ESPN rolling stats don't include MPG
                    pts_pg=pts_pg,
                    reb_pg=reb_pg,
                    ast_pg=ast_pg,
                    stl_pg=stl_pg,
                    blk_pg=blk_pg,
                    tpm_pg=tpm_pg,
                    to_pg=to_pg,
                    fga_pg=fga_pg,
                    fta_pg=fta_pg,
                    fg_pct=fg_pct,
                    ft_pct=ft_pct,
                    value=None,           # ESPN has no native value/rank
                    injury_status=injury_str,
                    roster_team=team.team_name,  # fantasy team for aggregation
                )

                # Zero out OUT players
                if injury_str == "OUT":
                    proj.pts_pg = 0.0
                    proj.reb_pg = 0.0
                    proj.ast_pg = 0.0
                    proj.stl_pg = 0.0
                    proj.blk_pg = 0.0
                    proj.tpm_pg = 0.0
                    proj.to_pg = 0.0
                    proj.fga_pg = 0.0
                    proj.fta_pg = 0.0
                    proj.fg_pct = None
                    proj.ft_pct = None
                    proj.games = 0.0

                results.append(proj)

        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_games_in_range(
    player: Any,
    week_start: Any,
    week_end: Any,
) -> int:
    """Count how many of a player's scheduled games fall inside the window.

    Mirrors the inner function in ``get_current_rosters()`` (~L1436–1440).
    """
    if not hasattr(player, "schedule"):
        return 0
    sched = player.schedule
    if not sched:
        return 0
    count = 0
    for game in sched.values() if isinstance(sched, dict) else sched:
        try:
            gdate = pd.to_datetime(game["date"]).normalize()
        except Exception:
            continue
        if pd.isna(week_start) or pd.isna(week_end):
            continue
        if week_start <= gdate <= week_end:
            count += 1
    return count
