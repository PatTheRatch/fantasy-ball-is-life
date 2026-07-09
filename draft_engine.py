"""
Draft Room engine — the per-pick recompute loop from docs/specs/DRAFT_ROOM.md
§4 (the "warm cache" / never-freeze mechanism).

Pure module: no cvxpy/pandas/ESPN import. A plan's roster is produced by an
injected ``solve_fn`` (same DI pattern as ``draft_strategies.generate_portfolio``),
so the health-check + selective-resolve logic is unit-testable offline. The real
``solve_fn`` (built on ``OptimizeLineup`` against the live pick pool) lives in
``api.py``.

Implementation note on the API surface: docs/specs/DRAFT_ROOM.md §4 names
``/draft/{id}/...`` endpoints, implying a server-held session. The same section's
Gate-1 resolution commits to a *stateless* backend with client-held state (D12).
This module reconciles the two: instead of a server session keyed by id, the
client resends its last response (``prior_plans``) with each new pick, and the
server does the O(1) health check against that instead of anything persisted.
No session store, no `{id}` — flagged as a documented simplification for
Aisha's next review, not a silent deviation from the approved spec.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from draft_strategies import Plan, PlanConfig, SolveFn


@dataclass(frozen=True)
class PlanSnapshot:
    """One saved plan's current state — the unit the client renders from."""

    plan_id: str
    config: PlanConfig
    roster: tuple[str, ...]
    health: str  # "alive" | "broken"
    health_reason: Optional[str] = None


def plan_id_for(config: PlanConfig) -> str:
    """Stable slug derived from the label, so it survives round-tripping
    through a client that only echoes back plan_id + label, not the full
    config. Kept to lowercase alphanumerics + underscores."""
    import re

    slug = config.label.lower().replace("+", " and ")
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return slug


def build_initial_snapshot(plans: Sequence[Plan]) -> list[PlanSnapshot]:
    """Wrap a freshly solved ``draft_strategies`` portfolio into snapshots.
    Every plan here is feasible by construction (``generate_portfolio`` already
    dropped anything infeasible), so health starts Alive."""
    return [
        PlanSnapshot(plan_id=plan_id_for(p.config), config=p.config, roster=tuple(p.roster), health="alive")
        for p in plans
    ]


def apply_pick(
    prior_plans: Sequence[PlanSnapshot],
    drafted_player_key: str,
    solve_fn: SolveFn,
) -> list[PlanSnapshot]:
    """The per-pick recompute (spec §4): an O(1) health check on every plan
    (does its roster contain the player who was just drafted?), then a
    **targeted** re-solve only for the plans that pick actually broke.
    Diversity (draft_strategies) means this is normally 0-2 plans, not all 10.
    """
    updated: list[PlanSnapshot] = []
    for plan in prior_plans:
        if drafted_player_key not in plan.roster:
            # Unaffected: nothing in this plan's target roster changed, so its
            # health and cached roster are still valid without a re-solve.
            updated.append(plan)
            continue

        new_roster = solve_fn(plan.config)
        if new_roster:
            updated.append(PlanSnapshot(plan.plan_id, plan.config, tuple(new_roster), "alive"))
        else:
            updated.append(
                PlanSnapshot(
                    plan.plan_id, plan.config, (), "broken",
                    health_reason=f"lost {drafted_player_key}, no feasible replacement under this plan",
                )
            )
    return updated


def pick_fallback(plans: Sequence[PlanSnapshot]) -> Optional[PlanSnapshot]:
    """The always-available next move (spec §2 criterion 2/5): the first
    still-Alive plan, in the portfolio's original ranked order. Never returns
    None unless every saved plan is Broken (the §4 relaxation path)."""
    for plan in plans:
        if plan.health == "alive":
            return plan
    return None
