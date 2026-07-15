"""On-disk projection store + manifest (P-2, updated P-6).

``data/projections/`` gitignored directory.  One parquet file per
``ProjectionSet``, with a ``manifest.json`` that tracks active sets
per horizon.

Atomic ingest (§6 of the spec): write parquet to a temp path in the
same directory, then ``os.replace`` into place before updating the
manifest.

P-6 semantic updates (post-merge review, 2026-07-14):
  - ``ProjectionSet.week`` scopes ``horizon='week'`` sets to a matchup
    period; ``load_active('week', current_week=...)`` only honors a set
    when its week matches the caller's current week.
  - Virtual ESPN sentinel ``ESPN_VIRTUAL_SET_ID`` — selecting it as
    active tells the registry to call ``EspnAdapter`` live instead of
    loading a parquet.
  - ``clear_horizon()`` resets a horizon to its default (ESPN for week,
    nothing for season).
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import pandas as pd

from backend.projections.adapter import PlayerProjection

# ---------------------------------------------------------------------------
# Root directory (relative to repo root; must be gitignored)
# ---------------------------------------------------------------------------

DEFAULT_STORE_DIR = Path("data/projections")
MANIFEST_FILENAME = "manifest.json"

# Sentinel: activating this set_id means "use ESPN live" for the week horizon.
ESPN_VIRTUAL_SET_ID = "espn-live"

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ProjectionSet metadata (spec §3 + P-6 `week` field)
# ---------------------------------------------------------------------------

@dataclass
class ProjectionSet:
    """Metadata for one ingested projection set."""

    set_id: str                              # uuid, or ESPN_VIRTUAL_SET_ID
    source: str                              # "bbm" | "espn" | "hashtag" | "internal" | "custom"
    horizon: str                             # "season" | "week"
    uploaded_at: str                         # ISO-8601 UTC
    filename: Optional[str] = None           # original filename (None for non-file sources)
    row_count: int = 0
    matched_count: int = 0
    unmatched_players: list[str] = field(default_factory=list)
    week: Optional[int] = None              # P-6: matchup week (for horizon='week')


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------

@dataclass
class _Manifest:
    active: dict[str, Optional[str]]   # horizon -> set_id
    sets: list[ProjectionSet]          # all known sets, newest first

    @classmethod
    def empty(cls) -> "_Manifest":
        return cls(active={}, sets=[])

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "active": self.active,
            "sets": [
                {
                    "set_id": s.set_id,
                    "source": s.source,
                    "horizon": s.horizon,
                    "uploaded_at": s.uploaded_at,
                    "filename": s.filename,
                    "row_count": s.row_count,
                    "matched_count": s.matched_count,
                    "unmatched_players": s.unmatched_players,
                    "week": s.week,
                }
                for s in self.sets
            ],
        }

    @classmethod
    def from_jsonable(cls, data: dict[str, Any]) -> "_Manifest":
        sets = [
            ProjectionSet(
                set_id=s["set_id"],
                source=s["source"],
                horizon=s["horizon"],
                uploaded_at=s["uploaded_at"],
                filename=s.get("filename"),
                row_count=s.get("row_count", 0),
                matched_count=s.get("matched_count", 0),
                unmatched_players=s.get("unmatched_players", []),
                week=s.get("week"),
            )
            for s in data.get("sets", [])
        ]
        return cls(active=data.get("active", {}), sets=sets)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class ProjectionStore:
    """CRUD for on-disk projection sets.

    Thread-safe only for single-process use (FastAPI async workers share
    the same filesystem).  Atomic writes for parquet ingest.
    """

    def __init__(self, store_dir: Path = DEFAULT_STORE_DIR) -> None:
        self.dir = Path(store_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.dir / MANIFEST_FILENAME
        self._manifest = self._load_manifest()

    # ---- manifest I/O ------------------------------------------------

    def _load_manifest(self) -> _Manifest:
        if not self._manifest_path.exists():
            return _Manifest.empty()
        try:
            data = json.loads(self._manifest_path.read_text())
            return _Manifest.from_jsonable(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            return _Manifest.empty()

    def _save_manifest(self) -> None:
        self._manifest_path.write_text(
            json.dumps(self._manifest.to_jsonable(), indent=2, default=str)
        )

    # ---- ingest -------------------------------------------------------

    def save_set(
        self,
        rows: list[PlayerProjection],
        source: str,
        horizon: str,
        *,
        filename: Optional[str] = None,
        uploaded_at: Optional[str] = None,
        matched_count: int = 0,
        unmatched_players: Optional[Sequence[str]] = None,
        week: Optional[int] = None,
    ) -> ProjectionSet:
        """Persist canonical projection rows as parquet.  Atomic write.

        For ``horizon='week'``, the ``week`` field scopes this set to a
        specific matchup period.  When omitted, the caller should pass it
        explicitly (the router defaults it from the ESPN matchup period).
        """
        if uploaded_at is None:
            uploaded_at = datetime.now(timezone.utc).isoformat()

        set_id = uuid.uuid4().hex
        parquet_filename = f"{source}_{horizon}_{set_id}.parquet"
        tmp_path = self.dir / (parquet_filename + ".tmp")
        final_path = self.dir / parquet_filename

        # ---- convert to DataFrame, write parquet -----------------
        df = _rows_to_dataframe(rows)
        df.to_parquet(tmp_path, index=False)
        os.replace(tmp_path, final_path)  # atomic

        # ---- update manifest -------------------------------------
        pset = ProjectionSet(
            set_id=set_id,
            source=source,
            horizon=horizon,
            uploaded_at=uploaded_at,
            filename=filename,
            row_count=len(rows),
            matched_count=matched_count,
            unmatched_players=list(unmatched_players or []),
            week=week,
        )
        self._manifest.sets.insert(0, pset)
        self._manifest.active[horizon] = set_id
        self._save_manifest()
        return pset

    # ---- load --------------------------------------------------------

    def load_set(self, set_id: str) -> Optional[list[PlayerProjection]]:
        """Load a specific set by ID.

        The virtual ESPN set returns ``None`` (the registry calls
        ``EspnAdapter`` live instead of reading a parquet).
        """
        if set_id == ESPN_VIRTUAL_SET_ID:
            return None  # special-cased by the registry
        for s in self._manifest.sets:
            if s.set_id == set_id:
                fname = f"{s.source}_{s.horizon}_{set_id}.parquet"
                path = self.dir / fname
                if not path.exists():
                    return None
                df = pd.read_parquet(path)
                return _dataframe_to_rows(df)
        return None

    def load_active(
        self,
        horizon: str,
        current_week: Optional[int] = None,
    ) -> Optional[list[PlayerProjection]]:
        """Load the currently-active set for ``horizon``, if any.

        P-6 week-scoping: for ``horizon='week'``, the active set is
        only honored when ``current_week`` is provided and matches the
        set's ``week`` field.  If no set is active or the week doesn't
        match, returns ``None`` (caller falls through to ESPN).
        """
        active_id = self._manifest.active.get(horizon)
        if not active_id:
            return None

        # Virtual ESPN sentinel — don't load a file
        if active_id == ESPN_VIRTUAL_SET_ID:
            return None

        # Week-scoped check
        if horizon == "week" and current_week is not None:
            active_set = self._find_set(active_id)
            if active_set is not None and active_set.week != current_week:
                return None  # week mismatch → fall through

        return self.load_set(active_id)

    # ---- list ---------------------------------------------------------

    def list_sets(
        self,
        source: Optional[str] = None,
        horizon: Optional[str] = None,
    ) -> list[ProjectionSet]:
        """List all uploaded sets, optionally filtered.

        P-6: virtual ESPN set is included when ``source=None`` or
        ``source='espn'`` and ``horizon='week'``.
        """
        result = list(self._manifest.sets)
        # Always include the virtual ESPN set for the week horizon
        if (source is None or source == "espn") and (horizon is None or horizon == "week"):
            # Check if it's already in the manifest (from a prior clear)
            if not any(s.set_id == ESPN_VIRTUAL_SET_ID for s in result):
                result.insert(0, ProjectionSet(
                    set_id=ESPN_VIRTUAL_SET_ID,
                    source="espn",
                    horizon="week",
                    uploaded_at="",  # always available
                    filename=None,
                    week=None,       # not week-scoped
                ))
        if source:
            result = [s for s in result if s.source == source]
        if horizon:
            result = [s for s in result if s.horizon == horizon]
        return result

    # ---- activate -----------------------------------------------------

    def set_active(self, set_id: str) -> bool:
        """Promote a set to active.

        ``ESPN_VIRTUAL_SET_ID`` is always accepted (no file needed).
        Returns True on success.
        """
        if set_id == ESPN_VIRTUAL_SET_ID:
            self._manifest.active["week"] = ESPN_VIRTUAL_SET_ID
            self._save_manifest()
            return True
        for s in self._manifest.sets:
            if s.set_id == set_id:
                self._manifest.active[s.horizon] = set_id
                self._save_manifest()
                return True
        return False

    # ---- clear ---------------------------------------------------------

    def clear_horizon(self, horizon: str) -> bool:
        """Reset a horizon to its default (ESPN for week, none for season).

        P-6: this is the "clear" affordance — after clearing, the
        registry falls through to live ESPN (week) or the optimizer's
        legacy disk read (season, documented at the router level).
        """
        if horizon == "week":
            self._manifest.active["week"] = ESPN_VIRTUAL_SET_ID
            self._save_manifest()
            return True
        # For season: reset to nothing (legacy BBM_PROJECTIONS_PATH)
        self._manifest.active.pop(horizon, None)
        self._save_manifest()
        return True

    # ---- helpers -------------------------------------------------------

    def _find_set(self, set_id: str) -> Optional[ProjectionSet]:
        for s in self._manifest.sets:
            if s.set_id == set_id:
                return s
        return None


# ---------------------------------------------------------------------------
# DataFrame ↔ list[PlayerProjection] round-trip
# ---------------------------------------------------------------------------

def _rows_to_dataframe(rows: list[PlayerProjection]) -> pd.DataFrame:
    """Convert canonical rows → parquet-safe DataFrame.

    ``positions`` (list[str]) is serialised as a pipe-joined string
    so parquet round-trips cleanly.
    """
    records = []
    for r in rows:
        records.append({
            "player_key": r.player_key,
            "display_name": r.display_name,
            "team": r.team,
            "positions": "|".join(r.positions) if r.positions else "",
            "games": r.games,
            "minutes_pg": r.minutes_pg,
            "pts_pg": r.pts_pg,
            "reb_pg": r.reb_pg,
            "ast_pg": r.ast_pg,
            "stl_pg": r.stl_pg,
            "blk_pg": r.blk_pg,
            "tpm_pg": r.tpm_pg,
            "to_pg": r.to_pg,
            "fga_pg": r.fga_pg,
            "fta_pg": r.fta_pg,
            "fg_pct": r.fg_pct,
            "ft_pct": r.ft_pct,
            "value": r.value,
            "injury_status": r.injury_status,
            "roster_team": r.roster_team,
        })
    return pd.DataFrame(records)


def _dataframe_to_rows(df: pd.DataFrame) -> list[PlayerProjection]:
    """Convert parquet DataFrame back to canonical rows."""
    rows: list[PlayerProjection] = []
    for _, rec in df.iterrows():
        pos_str = str(rec.get("positions", "") or "")
        positions = [p.strip() for p in pos_str.split("|") if p.strip()]
        rows.append(PlayerProjection(
            player_key=str(rec.get("player_key", "") or ""),
            display_name=str(rec.get("display_name", "") or ""),
            team=rec.get("team") if pd.notna(rec.get("team")) else None,
            positions=positions,
            games=float(rec["games"]) if pd.notna(rec.get("games")) else None,
            minutes_pg=float(rec["minutes_pg"]) if pd.notna(rec.get("minutes_pg")) else None,
            pts_pg=float(rec.get("pts_pg", 0) or 0),
            reb_pg=float(rec.get("reb_pg", 0) or 0),
            ast_pg=float(rec.get("ast_pg", 0) or 0),
            stl_pg=float(rec.get("stl_pg", 0) or 0),
            blk_pg=float(rec.get("blk_pg", 0) or 0),
            tpm_pg=float(rec.get("tpm_pg", 0) or 0),
            to_pg=float(rec.get("to_pg", 0) or 0),
            fga_pg=float(rec.get("fga_pg", 0) or 0),
            fta_pg=float(rec.get("fta_pg", 0) or 0),
            fg_pct=float(rec["fg_pct"]) if pd.notna(rec.get("fg_pct")) else None,
            ft_pct=float(rec["ft_pct"]) if pd.notna(rec.get("ft_pct")) else None,
            value=float(rec["value"]) if pd.notna(rec.get("value")) else None,
            injury_status=str(rec.get("injury_status")) if pd.notna(rec.get("injury_status")) else None,
            roster_team=str(rec.get("roster_team")) if pd.notna(rec.get("roster_team")) else None,
        ))
    return rows
