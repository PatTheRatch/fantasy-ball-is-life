"""Minimal projection-source registry (P-1).

P-1 only ships ``EspnAdapter``.  The full multi-source registry
(``BbmAdapter``, on-disk parquet store, manifest, upload endpoints) is
P-2.  ``get_active_projections()`` routes to EspnAdapter for
``horizon='week'`` and returns an empty list for all other horizons
(no adapter registered yet — P-2 fills this in).  The actual consumer
swap (projected scoreboard calling this instead of the legacy
``get_current_rosters`` path) is P-3.
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
    """Return the canonical projections for the requested horizon.

    P-1 knowledge: ``horizon='week'`` → ``EspnAdapter(window)``.  Everything
    else returns an empty list (to be filled in by P-2 / P-3).

    Parameters are forwarded through to the backing adapter — callers
    provide ESPN handles + window context.
    """
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
