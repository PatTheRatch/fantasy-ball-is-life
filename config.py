"""
Central configuration: ESPN league identity, credentials, and projection file paths.

Override credentials with environment variables (recommended for private leagues):
  ESPN_LEAGUE_ID, ESPN_SEASON, ESPN_SWID, ESPN_S2
Paths default to files under this project's `player_rankings/` directory.
"""
from __future__ import annotations

import os
from pathlib import Path

# Project root (directory containing this file)
PROJECT_ROOT = Path(__file__).resolve().parent

# --- ESPN fantasy league ---
LEAGUE_ID: int = int(os.getenv("ESPN_LEAGUE_ID", "3853870"))
SEASON: int = int(os.getenv("ESPN_SEASON", "2026"))
SWID = os.getenv("ESPN_SWID", None)
ESPN_S2 = os.getenv("ESPN_S2", None)

# --- Player rankings / projections (relative to project root) ---
PLAYER_RANKINGS_DIR = PROJECT_ROOT / "player_rankings"
BBM_PROJECTIONS_PATH = str(PLAYER_RANKINGS_DIR / "BBM_Projections.xls")
WEEKLY_PROJECTIONS_FILENAME = "WeeklyProjections.xls"
WEEKLY_PROJECTIONS_DEFAULT_PATH = str(PLAYER_RANKINGS_DIR / WEEKLY_PROJECTIONS_FILENAME)

# Default season year for `MyLeague` in the draft optimizer (may differ from ESPN_SEASON)
DRAFT_LEAGUE_YEAR_DEFAULT = int(os.getenv("DRAFT_LEAGUE_YEAR", "2025"))

# Average NBA games a team plays in a typical *playable* fantasy week.
# Scales per-game projections to per-week for draft targets and the optimizer's
# roster constraints. Derivation (see docs/specs/MC_DRAFT_TARGETS.md): 82 games /
# ~23.4 playable weeks (regular season minus the All-Star break) ~= 3.5,
# consistent with the fantasy-standard 3-4 games/week. One tunable constant;
# override via env if a league's cadence differs.
GAMES_PER_WEEK: float = float(os.getenv("GAMES_PER_WEEK", "3.5"))
