"""
Central configuration: ESPN league identity, credentials, and projection file paths.

Override credentials with environment variables (recommended for private leagues):
  ESPN_LEAGUE_ID, ESPN_SEASON, ESPN_SWID, ESPN_S2
Paths default to files under this project's `player_rankings/` directory.
"""
from __future__ import annotations

import os
from pathlib import Path

# Repo root -- this file lives at backend/config.py, so the repo root (where
# player_rankings/ and .env live) is one level up from this file's directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

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

# --- Draft pool hygiene (previously hardcoded inside optimize_lineup.clean_player_data) ---
# These are league-owner judgment calls, not engine logic, so they live in config:
# a different league (or a future multi-league deployment) should be able to change
# them without touching engine code.

# Players never drafted regardless of projected value (injury redshirts, personal
# do-not-draft list). Lowercase full names, comma-separated in the env override.
# Per-request exclusions (DraftPoolParams.exclude_players) stack on top of this.
DO_NOT_DRAFT: list[str] = [
    s.strip().lower()
    for s in os.getenv(
        "DO_NOT_DRAFT",
        "kyrie irving,deandre ayton,kristaps porzingis,jimmy butler,jason tatum",
    ).split(",")
    if s.strip()
]

# Position corrections applied on top of the projections file, for players whose
# listed position doesn't match how this league actually slots them.
POSITION_OVERRIDES: dict[str, str] = {
    "Anthony Davis": "C",
}

# Players projected for fewer season games than this are dropped from the draft
# pool entirely (before any per-request minimum_game_threshold applies).
MIN_SEASON_GAMES_FILTER: int = int(os.getenv("MIN_SEASON_GAMES_FILTER", "25"))

# Hard cap on a single roster solve (optimize_lineup.OptimizeLineup.optimize_roster).
# cvxpy's MILP solve has no timeout by default -- discovered running the real
# Monte Carlo-derived category targets (docs/specs/MC_DRAFT_TARGETS.md) through
# the Draft Room's actual constrained solve for the first time (previously
# always bypassed in testing because the old target method needed live ESPN):
# some genuinely feasible category/percentile combinations took 8-24s+, with no
# bound. This caps it so a solve always terminates -- see docs/specs/DRAFT_ROOM.md
# §2 criterion 2 (never freeze) and Gate 1's per-pick timing budget.
SOLVER_TIME_LIMIT_SECONDS: float = float(os.getenv("SOLVER_TIME_LIMIT_SECONDS", "8"))
