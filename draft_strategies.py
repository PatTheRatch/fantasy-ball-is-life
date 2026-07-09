"""
Draft plan strategies — the diversity mechanism for the Draft Room portfolio.

Implements the "Plan strategy -> solver parameters" map from
``docs/specs/DRAFT_ROOM.md`` (§4, amendment 3). Its whole job is to make saved
plans *genuinely different* from one another: Aisha's review found that the
existing ``generate_multiple_plans`` only cycles the percentile target and bans
one top player, keeping the same category set every time, so plans ended up
sharing 8-10 of 13 players. Real diversity comes from varying **which categories
a plan competes in** (a "punt" is literally dropping that category from the
constraints) plus how budget is concentrated.

This module is deliberately **pure** — no cvxpy, no pandas, no ESPN. A plan is
turned into a roster by an injected ``solve_fn`` (see ``generate_portfolio``), so
the diversity logic is unit-testable offline while the actual optimize/ESPN call
stays behind the boundary. The real ``solve_fn`` (built on ``OptimizeLineup``)
lives with the engine and is exercised by the gated integration test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence

# The 9 categories, canonical order. TO is inverted (lower is better) and is
# already negated inside the optimizer.
CATEGORIES: tuple[str, ...] = (
    "PTS", "REB", "AST", "STL", "BLK", "3PM", "FG%", "FT%", "TO",
)
COUNTING_CATS: tuple[str, ...] = ("PTS", "REB", "AST", "STL", "BLK", "3PM")
PERCENT_CATS: tuple[str, ...] = ("FG%", "FT%")

# Strategy shape identifiers (D8).
BALANCED = "balanced"
PUNT_ONE = "punt_one"
PUNT_MULTIPLE = "punt_multiple"
STARS_AND_SCRUBS = "stars_and_scrubs"
SPREAD_VALUE = "spread_value"

# Representative percentile band per shape (spec §4 table). The config stores a
# single value (the midpoint by default); tests assert it lands inside the band.
STRATEGY_PERCENTILE_BANDS: dict[str, tuple[float, float]] = {
    BALANCED: (0.65, 0.75),
    PUNT_ONE: (0.72, 0.80),
    PUNT_MULTIPLE: (0.75, 0.82),
    STARS_AND_SCRUBS: (0.55, 0.65),
    SPREAD_VALUE: (0.66, 0.70),
}

# ``minimum_value_players`` is the optimizer's count of required $1 roster slots
# (players whose Value == 1 — replacement-level fills). More $1 slots = a more
# top-heavy "stars & scrubs" build; fewer = a flatter "spread value" build.
# NOTE: this corrects the spec §4 wording, which had stars & scrubs as *fewer*
# value players — per the actual constraint it is *more* $1 fills.
STRATEGY_MIN_VALUE_PLAYERS: dict[str, int] = {
    BALANCED: 3,
    PUNT_ONE: 3,
    PUNT_MULTIPLE: 4,
    STARS_AND_SCRUBS: 6,
    SPREAD_VALUE: 1,
}


def _band_midpoint(shape: str) -> float:
    lo, hi = STRATEGY_PERCENTILE_BANDS[shape]
    return round((lo + hi) / 2, 3)


@dataclass(frozen=True)
class PlanConfig:
    """One plan's parameterization — a recipe the optimizer can execute."""

    label: str
    shape: str
    constrained_categories: tuple[str, ...]
    percentile: float
    minimum_value_players: int
    stat_to_maximize: str
    ban_top_price: bool = False
    punts: tuple[str, ...] = ()

    def to_optimizer_kwargs(self) -> dict:
        """Map to the knobs the engine consumes (``OptimizeLineup`` /
        ``set_requirements`` / ``optimize_roster``)."""
        return {
            "categories": list(self.constrained_categories),
            "percentile": self.percentile,
            "minimum_value_players": self.minimum_value_players,
            "stat_to_maximize": self.stat_to_maximize,
            "ban_top_price": self.ban_top_price,
        }


def _validate(shape: str, categories: Sequence[str], stat_to_maximize: str) -> None:
    bad = [c for c in categories if c not in CATEGORIES]
    if bad:
        raise ValueError(f"unknown categories {bad}; must be within {CATEGORIES}")
    if not categories:
        raise ValueError(f"{shape}: constrained_categories cannot be empty")
    if stat_to_maximize not in COUNTING_CATS:
        raise ValueError(
            f"stat_to_maximize={stat_to_maximize!r} must be a counting category "
            f"{COUNTING_CATS} (maximizing a percentage/turnover cat is undefined)"
        )
    if stat_to_maximize in [c for c in CATEGORIES if c not in categories]:
        raise ValueError(
            f"{shape}: cannot maximize {stat_to_maximize} while punting it"
        )


def balanced_config(stat_to_maximize: str = "PTS", label: str = "Balanced") -> PlanConfig:
    _validate(BALANCED, CATEGORIES, stat_to_maximize)
    return PlanConfig(
        label=label,
        shape=BALANCED,
        constrained_categories=CATEGORIES,
        percentile=_band_midpoint(BALANCED),
        minimum_value_players=STRATEGY_MIN_VALUE_PLAYERS[BALANCED],
        stat_to_maximize=stat_to_maximize,
    )


def punt_config(
    punts: Iterable[str],
    stat_to_maximize: str = "PTS",
    label: Optional[str] = None,
) -> PlanConfig:
    """A punt build: drop ``punts`` from the constrained set. One punt -> punt_one,
    two or more -> punt_multiple."""
    punts = tuple(dict.fromkeys(punts))  # de-dupe, keep order
    for p in punts:
        if p not in CATEGORIES:
            raise ValueError(f"unknown punt category {p!r}")
    shape = PUNT_ONE if len(punts) == 1 else PUNT_MULTIPLE
    kept = tuple(c for c in CATEGORIES if c not in punts)
    _validate(shape, kept, stat_to_maximize)
    if label is None:
        label = "Punt " + " + ".join(punts)
    return PlanConfig(
        label=label,
        shape=shape,
        constrained_categories=kept,
        percentile=_band_midpoint(shape),
        minimum_value_players=STRATEGY_MIN_VALUE_PLAYERS[shape],
        stat_to_maximize=stat_to_maximize,
        punts=punts,
    )


def stars_and_scrubs_config(stat_to_maximize: str = "PTS") -> PlanConfig:
    _validate(STARS_AND_SCRUBS, CATEGORIES, stat_to_maximize)
    return PlanConfig(
        label="Stars & scrubs",
        shape=STARS_AND_SCRUBS,
        constrained_categories=CATEGORIES,
        percentile=_band_midpoint(STARS_AND_SCRUBS),
        minimum_value_players=STRATEGY_MIN_VALUE_PLAYERS[STARS_AND_SCRUBS],
        stat_to_maximize=stat_to_maximize,
    )


def spread_value_config(stat_to_maximize: str = "PTS") -> PlanConfig:
    _validate(SPREAD_VALUE, CATEGORIES, stat_to_maximize)
    return PlanConfig(
        label="Spread value",
        shape=SPREAD_VALUE,
        constrained_categories=CATEGORIES,
        percentile=_band_midpoint(SPREAD_VALUE),
        minimum_value_players=STRATEGY_MIN_VALUE_PLAYERS[SPREAD_VALUE],
        stat_to_maximize=stat_to_maximize,
        ban_top_price=True,  # lift the reliance on the single priciest player
    )


# Default recipe for a 10-plan portfolio (D8 target). Ordered so the most useful
# fallbacks come first; the classic single-category punts dominate.
_DEFAULT_RECIPE: tuple[tuple, ...] = (
    ("balanced", None, "PTS"),
    ("punt", ("FT%",), "PTS"),
    ("punt", ("FG%",), "3PM"),
    ("punt", ("AST",), "REB"),
    ("punt", ("3PM",), "REB"),
    ("punt", ("TO",), "PTS"),
    ("punt", ("FG%", "TO"), "3PM"),
    ("punt", ("AST", "3PM"), "BLK"),
    ("stars_and_scrubs", None, "PTS"),
    ("spread_value", None, "PTS"),
)


def build_plan_configs(n_plans: int = 10) -> list[PlanConfig]:
    """Build up to ``n_plans`` distinct plan configs across the strategy shapes.

    Distinctness is enforced on the *parameterization* (shape + category set +
    percentile + $1-slot count + objective), so no two configs are identical.
    Whether the resulting *rosters* are distinct is a separate, empirical check —
    that's what ``generate_portfolio`` (with a real solver) and the integration
    test verify against live projections.
    """
    if n_plans < 1:
        raise ValueError("n_plans must be >= 1")

    configs: list[PlanConfig] = []
    seen: set[tuple] = set()
    for kind, cats, obj in _DEFAULT_RECIPE:
        if len(configs) >= n_plans:
            break
        if kind == "balanced":
            cfg = balanced_config(stat_to_maximize=obj)
        elif kind == "punt":
            cfg = punt_config(cats, stat_to_maximize=obj)
        elif kind == "stars_and_scrubs":
            cfg = stars_and_scrubs_config(stat_to_maximize=obj)
        elif kind == "spread_value":
            cfg = spread_value_config(stat_to_maximize=obj)
        else:  # pragma: no cover - guarded by the fixed recipe
            raise ValueError(f"unknown recipe kind {kind!r}")

        key = (
            cfg.shape,
            cfg.constrained_categories,
            cfg.percentile,
            cfg.minimum_value_players,
            cfg.stat_to_maximize,
        )
        if key in seen:
            continue
        seen.add(key)
        configs.append(cfg)

    return configs


@dataclass
class Plan:
    """A config paired with the roster the solver produced for it."""

    config: PlanConfig
    roster: list[str] = field(default_factory=list)


# A solver takes a config and returns the chosen roster as a list of player keys,
# or None if the config is infeasible for the current pool.
SolveFn = Callable[[PlanConfig], Optional[Sequence[str]]]


def generate_portfolio(
    plan_configs: Sequence[PlanConfig],
    solve_fn: SolveFn,
    *,
    max_shared: int = 8,
    roster_size: int = 13,
    limit: Optional[int] = None,
) -> list[Plan]:
    """Solve each config and keep only plans whose rosters are *distinct enough*.

    A candidate is dropped if it shares more than ``max_shared`` players with an
    already-kept plan (the review's ≤8/13 diversity bar) or if the solver returns
    None (infeasible). This is the diversity-enforcement loop; injecting
    ``solve_fn`` keeps it testable without the optimizer.
    """
    kept: list[Plan] = []
    for cfg in plan_configs:
        if limit is not None and len(kept) >= limit:
            break
        roster = solve_fn(cfg)
        if not roster:
            continue
        rset = set(roster)
        if any(len(rset & set(p.roster)) > max_shared for p in kept):
            continue
        kept.append(Plan(config=cfg, roster=list(roster)))
    return kept
