"""BbmAdapter — Basketball Monster projection source (P-2).

Port of the existing ``_normalize_season_projections_from_raw`` +
``add_bbm_projections`` column-rename logic, emitting canonical
``PlayerProjection`` rows.

Handles both horizons:
  - **season**: bare columns (``p``, ``3``, ``r``, …) + ``LeagV``
  - **week**: ``/g``-suffixed columns (``p/g``, ``3/g``, …) + ``g``

``detect()`` auto-discriminates between the two by sniffing the
sheet's header columns.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from backend.projections.adapter import PlayerProjection, ProjectionAdapter


# ---------------------------------------------------------------------------
# Column signatures for auto-detection
# ---------------------------------------------------------------------------

_SEASON_SIGNATURE = frozenset({
    "p", "3", "r", "a", "s", "b", "fga", "fta", "to",
})
_WEEKLY_SIGNATURE = frozenset({
    "p/g", "3/g", "r/g", "a/g", "s/g", "b/g", "fga/g", "fta/g", "to/g",
})


# ---------------------------------------------------------------------------
# BbmAdapter
# ---------------------------------------------------------------------------

class BbmAdapter:
    """Normalise BBM season / weekly projection sheets.

    ``source_id="bbm"``, ``supported_horizons=["season", "week"]``.
    """

    source_id: str = "bbm"
    supported_horizons: list[str] = ["season", "week"]

    def __init__(self) -> None:
        pass

    # ---- protocol -----------------------------------------------------

    def detect(self, file: Any = None, *, raw_df: Optional[pd.DataFrame] = None) -> float:
        """Sniff header columns to identify a BBM sheet.

        Returns 0.95 for a confident season or weekly match, ~0 if unrecognised.
        """
        df = _resolve_df(file, raw_df)
        if df is None:
            return 0.0
        cols_lower = {c.strip().lower() for c in df.columns}

        season_hits = len(_SEASON_SIGNATURE & cols_lower)
        weekly_hits = len(_WEEKLY_SIGNATURE & cols_lower)

        if season_hits >= 7:
            return 0.95
        if weekly_hits >= 7:
            return 0.95
        return 0.0

    def parse(
        self,
        file: Any = None,
        *,
        raw_df: Optional[pd.DataFrame] = None,
        horizon: Optional[str] = None,
    ) -> list[PlayerProjection]:
        """Normalise a BBM sheet into canonical PlayerProjection rows.

        If ``horizon`` is omitted, it is inferred from the column
        signature (season vs weekly).  ``raw_df`` takes precedence
        over ``file`` (caller already read the upload bytes).
        """
        from backend.league.data_feed import normalize_name

        df = _resolve_df(file, raw_df)
        if df is None:
            raise ValueError("BbmAdapter.parse() requires `raw_df` or `file`")

        # ---- auto-detect horizon if not given --------------------
        if horizon is None:
            horizon = _infer_horizon(df.columns)

        # ---- make a copy and normalise column names --------------
        df = df.copy()
        df.columns = [c.strip() for c in df.columns]

        # Season exports: rename bare columns → /g form so the rest
        # of the normalisation is uniform.
        _SEASON_RENAME = {
            "p": "p/g", "3": "3/g", "r": "r/g", "a": "a/g",
            "s": "s/g", "b": "b/g", "fga": "fga/g", "fta": "fta/g",
            "to": "to/g",
        }
        lookup = {k.lower(): v for k, v in _SEASON_RENAME.items()}
        renamed = {}
        for col in df.columns:
            renamed[col] = lookup.get(col.lower(), col)
        df.rename(columns=renamed, inplace=True)

        # ---- normalise numeric columns ---------------------------
        num_cols = [
            "p/g", "3/g", "r/g", "a/g", "s/g", "b/g",
            "fga/g", "fta/g", "to/g", "fg%", "ft%",
        ]
        for c in num_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

        # ---- canonical column map --------------------------------
        _STAT_MAP = {
            "p/g": "pts_pg", "3/g": "tpm_pg", "r/g": "reb_pg",
            "a/g": "ast_pg", "s/g": "stl_pg", "b/g": "blk_pg",
            "fga/g": "fga_pg", "fta/g": "fta_pg", "to/g": "to_pg",
            "fg%": "fg_pct", "ft%": "ft_pct",
        }

        # ---- build PlayerProjection rows -------------------------
        results: list[PlayerProjection] = []
        for _, row in df.iterrows():
            name = str(row.get("Name", "") or "")
            if not name or not name.strip() or name.lower() == "nan":
                continue

            player_key = normalize_name(name)

            # Stats
            pts   = _f(row, "p/g")
            tpm   = _f(row, "3/g")
            reb   = _f(row, "r/g")
            ast   = _f(row, "a/g")
            stl   = _f(row, "s/g")
            blk   = _f(row, "b/g")
            fga   = _f(row, "fga/g")
            fta   = _f(row, "fta/g")
            to    = _f(row, "to/g")
            fg_p  = _f_or_none(row, "fg%")
            ft_p  = _f_or_none(row, "ft%")

            # Games: from `g` column (present in weekly, may be absent in season)
            games: Optional[float] = None
            if "g" in df.columns:
                gv = pd.to_numeric(row.get("g"), errors="coerce")
                games = float(gv) if pd.notna(gv) else None

            # Value: try LeagV first (season), then $ (weekly)
            value: Optional[float] = None
            for vcol in ("LeagV", "$"):
                if vcol in df.columns:
                    v = pd.to_numeric(row.get(vcol), errors="coerce")
                    if pd.notna(v):
                        value = float(v)
                        break

            # Injury
            injury: Optional[str] = None
            for icol in ("Inj", "Status", "injury_status"):
                if icol in df.columns:
                    inj_val = row.get(icol)
                    if pd.notna(inj_val) and str(inj_val).strip():
                        injury = str(inj_val).strip()
                        break

            # Team
            team: Optional[str] = None
            for tcol in ("Team", "NBA Team"):
                if tcol in df.columns:
                    tv = row.get(tcol)
                    if pd.notna(tv) and str(tv).strip():
                        team = str(tv).strip()
                        break

            results.append(PlayerProjection(
                player_key=player_key,
                display_name=name,
                team=team,
                positions=[],   # BBM doesn't provide positions
                games=games,
                minutes_pg=None,
                pts_pg=pts, reb_pg=reb, ast_pg=ast, stl_pg=stl,
                blk_pg=blk, tpm_pg=tpm, to_pg=to,
                fga_pg=fga, fta_pg=fta,
                fg_pct=fg_p, ft_pct=ft_p,
                value=value,
                injury_status=injury,
            ))

        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_df(
    file: Any,
    raw_df: Optional[pd.DataFrame],
) -> Optional[pd.DataFrame]:
    """Return a DataFrame from whatever the caller passed."""
    if raw_df is not None:
        return raw_df.copy()
    if file is not None:
        if isinstance(file, (str, bytes)):
            return pd.read_excel(file, dtype=str)
        return pd.read_excel(file, dtype=str)  # file-like
    return None


def _f(row, col: str) -> float:
    """Safe float accessor (0.0 on missing/NaN)."""
    try:
        return float(row.get(col, 0) or 0)
    except (ValueError, TypeError):
        return 0.0


def _f_or_none(row, col: str) -> Optional[float]:
    """Safe float accessor returning None when the column is absent or NaN."""
    try:
        v = row.get(col)
        if v is None or pd.isna(v):
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


def _infer_horizon(columns: pd.Index) -> str:
    """Guess ``season`` vs ``week`` from header column signatures."""
    cols = {c.strip().lower() for c in columns}
    if len(_SEASON_SIGNATURE & cols) >= 7:
        return "season"
    if len(_WEEKLY_SIGNATURE & cols) >= 7:
        return "week"
    return "season"  # best-effort default
