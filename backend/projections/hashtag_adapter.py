"""HashtagAdapter — Hashtag Basketball projection source (P-5).

Accepts two input modes per the spec:
  1. **CSV/Excel file** — if HashTag's premium tier exports one
  2. **Pasted table** — user copies the projections table from browser
     into a textarea; adapter parses tab/whitespace-delimited text

Format is unconfirmed (spec caveat, 2026-07-08).  The adapter is
column-tolerant: it detects Hashtag-style headers by looking for the
familiar set of fantasy-stat column names regardless of case/spacing.
``detect()`` returns high confidence when enough signature columns are
present; ``parse()`` maps whatever columns it finds to canonical
``PlayerProjection`` fields, defaulting missing columns to 0.
"""

from __future__ import annotations

import io
from typing import Any, Optional

import pandas as pd

from backend.projections.adapter import PlayerProjection, ProjectionAdapter


# ---------------------------------------------------------------------------
# Column signatures — case-insensitive, whitespace-tolerant
# ---------------------------------------------------------------------------

# Columns that strongly signal "this is Hashtag Basketball"
_HASHTAG_SIGNATURE = frozenset({
    "player", "team", "pos", "gp", "min",
    "pts", "3pm", "reb", "ast", "stl", "blk",
    "fg%", "ft%", "to",
})


# ---------------------------------------------------------------------------
# Mapping: Hashtag column name (lowercase, stripped) → PlayerProjection attr
# ---------------------------------------------------------------------------

_COLUMN_MAP: dict[str, tuple[str, bool]] = {
    # (PlayerProjection attr name, is_percentage)
    "pts":     ("pts_pg", False),
    "reb":     ("reb_pg", False),
    "ast":     ("ast_pg", False),
    "stl":     ("stl_pg", False),
    "blk":     ("blk_pg", False),
    "3pm":     ("tpm_pg", False),
    "to":      ("to_pg", False),
    "fg%":     ("fg_pct", True),
    "ft%":     ("ft_pct", True),
    "fgm":     ("fgm_pg", False),   # not stored directly; used to derive
    "fga":     ("fga_pg", False),
    "ftm":     ("ftm_pg", False),   # not stored directly
    "fta":     ("fta_pg", False),
}

# Columns with alternate names
_ALIASES: dict[str, str] = {
    "gp": "games",
    "g":  "games",
    "min": "minutes",
    "minutes": "minutes",
    "mpg": "minutes",
    "turnovers": "to",
    "threes": "3pm",
    "3pt": "3pm",
    "points": "pts",
    "rebounds": "reb",
    "assists": "ast",
    "steals": "stl",
    "blocks": "blk",
}


# ---------------------------------------------------------------------------
# HashtagAdapter
# ---------------------------------------------------------------------------

class HashtagAdapter:
    """Normalise Hashtag Basketball projection tables.

    ``source_id="hashtag"``, ``supported_horizons=["season"]``.
    Hashtag publishes full-season projections; weekly splits are
    not part of their standard export.
    """

    source_id: str = "hashtag"
    supported_horizons: list[str] = ["season"]

    # ---- protocol -----------------------------------------------------

    def detect(self, file: Any = None, *, raw_df: Optional[pd.DataFrame] = None) -> float:
        """Sniff columns.  Returns 0.9+ if Hashtag signature present."""
        df = _resolve_input(file, raw_df)
        if df is None:
            return 0.0
        cols_lower = {str(c).strip().lower() for c in df.columns}
        hits = len(_HASHTAG_SIGNATURE & cols_lower)
        if hits >= 8:
            return 0.95
        if hits >= 5:
            return 0.7
        return 0.0

    def parse(
        self,
        file: Any = None,
        *,
        raw_df: Optional[pd.DataFrame] = None,
        pasted_text: Optional[str] = None,
    ) -> list[PlayerProjection]:
        """Normalise into canonical ``PlayerProjection`` rows.

        Accepts ``raw_df`` (already-parsed file), ``file`` (path/file-like),
        or ``pasted_text`` (whitespace-delimited text from the user's
        clipboard — the browser textarea mode).
        """
        from backend.league.data_feed import normalize_name

        df = _resolve_input(file, raw_df, pasted_text)
        if df is None:
            raise ValueError(
                "HashtagAdapter.parse() requires `raw_df`, `file`, or `pasted_text`"
            )

        # Normalise column names: lowercase, strip whitespace
        df = df.copy()
        df.columns = [str(c).strip().lower() for c in df.columns]

        # ---- detect player-name column ----
        name_col = None
        for candidate in ("player", "name", "player name"):
            if candidate in df.columns:
                name_col = candidate
                break
        if name_col is None:
            raise ValueError(
                "Could not find a player-name column in Hashtag data. "
                "Expected 'Player' or 'Name'."
            )

        # ---- map columns to PlayerProjection attrs ----
        mapped: dict[str, str] = {}       # canonical_col → proj_attr
        is_pct: dict[str, bool] = {}      # whether the value is a percentage
        for col in df.columns:
            key = col.lower().strip()
            # apply aliases
            key = _ALIASES.get(key, key)
            if key in _COLUMN_MAP:
                attr, pct = _COLUMN_MAP[key]
                mapped[col] = attr
                is_pct[col] = pct

        # ---- extract games / minutes ----
        games_col = None
        for c in ("gp", "g", "games"):
            if c in df.columns:
                games_col = c
                break
        minutes_col = None
        for c in ("min", "minutes", "mpg"):
            if c in df.columns:
                minutes_col = c
                break

        # ---- build rows ----
        results: list[PlayerProjection] = []
        for _, row in df.iterrows():
            name = str(row.get(name_col, "") or "")
            if not name or not name.strip() or name.lower() == "nan":
                continue

            player_key = normalize_name(name)

            # Initialize with defaults
            pts_pg = reb_pg = ast_pg = stl_pg = blk_pg = 0.0
            tpm_pg = to_pg = fga_pg = fta_pg = 0.0
            fg_pct: Optional[float] = None
            ft_pct: Optional[float] = None

            for src_col, attr in mapped.items():
                val = _safe_float(row.get(src_col))
                if is_pct.get(src_col):
                    # Hashtag stores percentages as e.g. 45.2 (not 0.452)
                    val = val / 100.0 if val > 1 else val
                if attr == "pts_pg":    pts_pg = val
                elif attr == "reb_pg":  reb_pg = val
                elif attr == "ast_pg":  ast_pg = val
                elif attr == "stl_pg":  stl_pg = val
                elif attr == "blk_pg":  blk_pg = val
                elif attr == "tpm_pg":  tpm_pg = val
                elif attr == "to_pg":   to_pg = val
                elif attr == "fga_pg":  fga_pg = val
                elif attr == "fta_pg":  fta_pg = val
                elif attr == "fg_pct":  fg_pct = val
                elif attr == "ft_pct":  ft_pct = val

            # Derived: try FGM from FG% * FGA if not directly provided
            teams: Optional[str] = None
            for tcol in ("team", "nba team"):
                if tcol in df.columns:
                    tv = row.get(tcol)
                    if pd.notna(tv) and str(tv).strip():
                        teams = str(tv).strip()
                        break

            pos_list: list[str] = []
            for pcol in ("pos", "position", "positions"):
                if pcol in df.columns:
                    pv = str(row.get(pcol, "") or "")
                    if pv.strip():
                        pos_list = [x.strip() for x in pv.replace(",", " ").split() if x.strip()]
                        break

            games: Optional[float] = None
            if games_col:
                gv = _safe_float(row.get(games_col))
                games = gv if gv > 0 else None

            minutes_pg: Optional[float] = None
            if minutes_col:
                mv = _safe_float(row.get(minutes_col))
                minutes_pg = mv if mv > 0 else None

            results.append(PlayerProjection(
                player_key=player_key,
                display_name=name,
                team=teams,
                positions=pos_list,
                games=games,
                minutes_pg=minutes_pg,
                pts_pg=pts_pg, reb_pg=reb_pg, ast_pg=ast_pg,
                stl_pg=stl_pg, blk_pg=blk_pg,
                tpm_pg=tpm_pg, to_pg=to_pg,
                fga_pg=fga_pg, fta_pg=fta_pg,
                fg_pct=fg_pct, ft_pct=ft_pct,
            ))

        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_input(
    file: Any = None,
    raw_df: Optional[pd.DataFrame] = None,
    pasted_text: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """Resolve whatever input the caller passed into a DataFrame."""
    if raw_df is not None:
        return raw_df.copy()
    if pasted_text is not None:
        return _parse_pasted(pasted_text)
    if file is not None:
        if isinstance(file, (str, bytes)):
            return pd.read_excel(file, dtype=str) if str(file).endswith((".xls", ".xlsx")) else pd.read_csv(file, sep=None, dtype=str)
        return pd.read_csv(file, sep=None, dtype=str)  # file-like, try CSV
    return None


def _parse_pasted(text: str) -> pd.DataFrame:
    """Parse whitespace/tab-delimited text into a DataFrame.

    Hashtag's browser table is typically tab-delimited with a header row,
    but may use variable whitespace.  We detect the separator by checking
    for tabs first, then falling back to whitespace.
    """
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if len(lines) < 2:
        raise ValueError("Pasted text must have at least a header row and one data row.")

    sep = "\t" if "\t" in lines[0] else r"\s+"
    return pd.read_csv(
        io.StringIO(text),
        sep=sep,
        dtype=str,
        engine="python",
    )


def _safe_float(val: Any) -> float:
    """Coerce a value to float, returning 0.0 on failure."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
