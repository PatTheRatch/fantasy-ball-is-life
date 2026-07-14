"""Projection-source registry (P-2).

Precedence for each horizon:
  ``week``  — uploaded BBM set (store) → live ESPN (EspnAdapter)
  ``season`` — uploaded BBM set (store) → empty (no live source yet)

The actual consumer swap (projected scoreboard calling this instead of
the legacy ``get_current_rosters`` path) is P-3.
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

    Precedence (per horizon):
      ``week``  — store (uploaded BBM) → ESPN live Last-N
      ``season`` — store (uploaded BBM) → empty
    """
    # ---- check the store first (uploaded sets win) ----
    store = _get_store()  # defaults to data/projections/
    rows = store.load_active(horizon)
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
