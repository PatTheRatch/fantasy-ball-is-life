"""Projection-source registry (P-2, updated P-6).

Precedence (P-6 post-merge review):
  ``week``  — explicit per-request override (caller's responsibility)
              → store (week-scoped) → ESPN live
  ``season`` — store → empty (legacy optimizer disk read is P-8)

P-6: ``load_active('week')`` is week-scoped — only honored when the
set's week matches the caller's current matchup week.  ESPN is a
virtual set (``ESPN_VIRTUAL_SET_ID``) that can be selected via the
ordinary activate flow; the registry special-cases that id by calling
``EspnAdapter`` live instead of loading a parquet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from backend.projections.adapter import PlayerProjection  # circular-safe


def get_active_projections(
    horizon: str,
    *,
    handles: Any = None,
    window: int = 15,
    week_end_date: Optional[str] = None,
    week_start_date: Optional[str] = None,
    current_matchup_period: Optional[int] = None,
) -> "list[PlayerProjection]":
    """Canonical projections for ``horizon``.

    Precedence (P-6):
      ``week``  — store (week-scoped) → ESPN live
      ``season`` — store → empty (optimizer legacy disk fallback is P-8)

    For ``horizon='week'``, ``load_active`` receives
    ``current_week=current_matchup_period`` so only a set uploaded for
    this specific matchup week is honored.  Stale sets from prior weeks
    fall through to live ESPN automatically.
    """
    store = _get_store()

    # ---- check the store (week-scoped for horizon='week') ----
    current_week = current_matchup_period if horizon == "week" else None
    rows = store.load_active(horizon, current_week=current_week)
    if rows is not None:
        return rows

    # ---- fallback: live sources ----
    if horizon == "week":
        from backend.projections.adapter import EspnAdapter

        adapter = EspnAdapter(window=window)
        return adapter.parse(
            handles=handles,
            week_end_date=week_end_date,
            week_start_date=week_start_date,
            current_matchup_period=current_matchup_period,
        )

    return []


def _get_store() -> "ProjectionStore":
    """Internal: get the singleton ProjectionStore."""
    from backend.projections.store import ProjectionStore
    return ProjectionStore()
