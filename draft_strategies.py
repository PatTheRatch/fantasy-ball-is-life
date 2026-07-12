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
#
# Shifted down ~0.35 from the original (0.65-0.82) bands, 2026-07-10: those were
# chosen without ever running a real constrained solve (this sandbox couldn't --
# the old target method needed live ESPN). Once Monte Carlo targets landed
# (docs/specs/MC_DRAFT_TARGETS.md, history-independent, so it's actually
# testable here), the real solver hit 8-24s+ per solve in the old range, some of
# it unbounded (see SOLVER_TIME_LIMIT_SECONDS in config.py, added alongside this
# for the cases that are still slow even down here). Solve difficulty near a
# MILP's feasibility boundary is not a smooth function of percentile -- sampled
# 0.30-0.75 empirically; this range was consistently fast to solve or comfortably
# within the new time limit, never outright unbounded. Relative spacing between
# shapes (punt > balanced > stars & scrubs) is unchanged from the original.
STRATEGY_PERCENTILE_BANDS: dict[str, tuple[float, float]] = {
    BALANCED: (0.30, 0.40),
    PUNT_ONE: (0.37, 0.45),
    PUNT_MULTIPLE: (0.40, 0.47),
    STARS_AND_SCRUBS: (0.20, 0.30),
    SPREAD_VALUE: (0.31, 0.35),
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


# Each shape's percentile offset from Balanced's own midpoint, derived once from
# the bands above. Lets a user-chosen confidence level ("base_percentile" — "at
# what likelihood do I want to win a category") slide the *whole* portfolio while
# preserving each shape's relative aggressiveness (a punt build still asks for
# more than Balanced; stars & scrubs still asks for less).
_SHAPE_OFFSET: dict[str, float] = {
    shape: round(_band_midpoint(shape) - _band_midpoint(BALANCED), 3)
    for shape in STRATEGY_PERCENTILE_BANDS
}
_MIN_PERCENTILE, _MAX_PERCENTILE = 0.50, 0.95


def _shape_percentile(shape: str, base_percentile: Optional[float]) -> float:
    if base_percentile is None:
        return _band_midpoint(shape)
    return round(min(_MAX_PERCENTILE, max(_MIN_PERCENTILE, base_percentile + _SHAPE_OFFSET[shape])), 3)


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


def balanced_config(
    stat_to_maximize: str = "PTS",
    label: str = "Balanced",
    categories: Sequence[str] = CATEGORIES,
    percentile: Optional[float] = None,
) -> PlanConfig:
    categories = tuple(categories)
    _validate(BALANCED, categories, stat_to_maximize)
    return PlanConfig(
        label=label,
        shape=BALANCED,
        constrained_categories=categories,
        percentile=_shape_percentile(BALANCED, percentile),
        minimum_value_players=STRATEGY_MIN_VALUE_PLAYERS[BALANCED],
        stat_to_maximize=stat_to_maximize,
    )


def punt_config(
    punts: Iterable[str],
    stat_to_maximize: str = "PTS",
    label: Optional[str] = None,
    categories: Sequence[str] = CATEGORIES,
    percentile: Optional[float] = None,
) -> PlanConfig:
    """A punt build: drop ``punts`` from ``categories`` (the competing universe,
    all 9 by default). One punt -> punt_one, two or more -> punt_multiple."""
    punts = tuple(dict.fromkeys(punts))  # de-dupe, keep order
    for p in punts:
        if p not in CATEGORIES:
            raise ValueError(f"unknown punt category {p!r}")
    shape = PUNT_ONE if len(punts) == 1 else PUNT_MULTIPLE
    kept = tuple(c for c in categories if c not in punts)
    _validate(shape, kept, stat_to_maximize)
    if label is None:
        label = "Punt " + " + ".join(punts)
    return PlanConfig(
        label=label,
        shape=shape,
        constrained_categories=kept,
        percentile=_shape_percentile(shape, percentile),
        minimum_value_players=STRATEGY_MIN_VALUE_PLAYERS[shape],
        stat_to_maximize=stat_to_maximize,
        punts=punts,
    )


def stars_and_scrubs_config(
    stat_to_maximize: str = "PTS",
    categories: Sequence[str] = CATEGORIES,
    percentile: Optional[float] = None,
) -> PlanConfig:
    categories = tuple(categories)
    _validate(STARS_AND_SCRUBS, categories, stat_to_maximize)
    return PlanConfig(
        label="Stars & scrubs",
        shape=STARS_AND_SCRUBS,
        constrained_categories=categories,
        percentile=_shape_percentile(STARS_AND_SCRUBS, percentile),
        minimum_value_players=STRATEGY_MIN_VALUE_PLAYERS[STARS_AND_SCRUBS],
        stat_to_maximize=stat_to_maximize,
    )


def spread_value_config(
    stat_to_maximize: str = "PTS",
    categories: Sequence[str] = CATEGORIES,
    percentile: Optional[float] = None,
) -> PlanConfig:
    categories = tuple(categories)
    _validate(SPREAD_VALUE, categories, stat_to_maximize)
    return PlanConfig(
        label="Spread value",
        shape=SPREAD_VALUE,
        constrained_categories=categories,
        percentile=_shape_percentile(SPREAD_VALUE, percentile),
        minimum_value_players=STRATEGY_MIN_VALUE_PLAYERS[SPREAD_VALUE],
        stat_to_maximize=stat_to_maximize,
        ban_top_price=True,  # lift the reliance on the single priciest player
    )


def custom_config(
    label: str,
    categories: Sequence[str],
    percentile: float,
    stat_to_maximize: str,
    minimum_value_players: int = 3,
    ban_top_price: bool = False,
) -> PlanConfig:
    """A fully user-specified plan -- every knob set directly, no shape-band
    lookup. This is the "build your own, save it" path (Patrick, 2026-07-10):
    unlike ``build_plan_configs``'s fixed 10-plan recipe, the user picks their
    own category set, percentile, objective, and $1-slot count instead of a
    strategy shape choosing them.

    ``shape="custom"`` is a free-form label read only for display and for
    ``generate_portfolio``'s dedup key elsewhere in this module -- nothing
    keys off it the way ``STRATEGY_MIN_VALUE_PLAYERS``/
    ``STRATEGY_PERCENTILE_BANDS`` key off the five built-in shapes, so it's
    safe to skip those lookups entirely here.
    """
    if not label.strip():
        raise ValueError("label cannot be empty")
    categories = tuple(dict.fromkeys(categories))
    _validate("custom", categories, stat_to_maximize)
    if not (0.0 < percentile <= 1.0):
        raise ValueError(f"percentile must be in (0, 1], got {percentile}")
    if minimum_value_players < 0:
        raise ValueError("minimum_value_players cannot be negative")
    punts = tuple(c for c in CATEGORIES if c not in categories)
    return PlanConfig(
        label=label,
        shape="custom",
        constrained_categories=categories,
        percentile=round(percentile, 3),
        minimum_value_players=minimum_value_players,
        stat_to_maximize=stat_to_maximize,
        ban_top_price=ban_top_price,
        punts=punts,
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


def build_plan_configs(
    n_plans: int = 10,
    target_categories: Optional[Sequence[str]] = None,
    base_percentile: Optional[float] = None,
    stat_to_maximize: Optional[str] = None,
) -> list[PlanConfig]:
    """Build up to ``n_plans`` distinct plan configs across the strategy shapes.

    User-facing knobs (the "what am I actually optimizing for" controls):

    - ``target_categories``: which of the 9 categories to compete in at all,
      across *every* generated plan. Anything left out is treated as
      permanently punted — recipe entries that would punt an already-excluded
      category are skipped as redundant. ``None`` means all 9 (today's
      behavior, unchanged).
    - ``base_percentile``: "how likely do I want to win a category" — recenters
      every shape's percentile target around this value while preserving each
      shape's relative aggressiveness (see ``_shape_percentile``). ``None``
      keeps the original fixed bands (unchanged default behavior).
    - ``stat_to_maximize``: override the objective for every generated plan
      (must be a counting category within ``target_categories``). ``None``
      keeps each recipe entry's own default objective (unchanged behavior).

    Distinctness is enforced on the *parameterization* (shape + category set +
    percentile + $1-slot count + objective), so no two configs are identical.
    Whether the resulting *rosters* are distinct is a separate, empirical check —
    that's what ``generate_portfolio`` (with a real solver) and the integration
    test verify against live projections.
    """
    if n_plans < 1:
        raise ValueError("n_plans must be >= 1")

    if target_categories is None:
        universe = CATEGORIES
    else:
        universe = tuple(dict.fromkeys(target_categories))
        bad = [c for c in universe if c not in CATEGORIES]
        if bad:
            raise ValueError(f"unknown target_categories {bad}; must be within {CATEGORIES}")
        if not universe:
            raise ValueError("target_categories cannot be empty")

    if stat_to_maximize is not None:
        if stat_to_maximize not in COUNTING_CATS:
            raise ValueError(
                f"stat_to_maximize={stat_to_maximize!r} must be a counting category "
                f"{COUNTING_CATS} (maximizing a percentage/turnover cat is undefined)"
            )
        if stat_to_maximize not in universe:
            raise ValueError(
                f"stat_to_maximize={stat_to_maximize!r} must be one of the selected "
                f"target_categories {universe} (can't maximize a category you've punted)"
            )

    configs: list[PlanConfig] = []
    seen: set[tuple] = set()
    for kind, cats, default_obj in _DEFAULT_RECIPE:
        if len(configs) >= n_plans:
            break
        obj = stat_to_maximize or default_obj
        if obj not in COUNTING_CATS or obj not in universe:
            continue  # this recipe entry's objective isn't available under the user's category selection

        if kind == "balanced":
            cfg = balanced_config(stat_to_maximize=obj, categories=universe, percentile=base_percentile)
        elif kind == "punt":
            if any(c not in universe for c in cats):
                continue  # already excluded by target_categories — a redundant punt
            if obj in cats:
                continue  # this entry would punt the (now globally-fixed) objective — invalid, not redundant
            cfg = punt_config(cats, stat_to_maximize=obj, categories=universe, percentile=base_percentile)
        elif kind == "stars_and_scrubs":
            cfg = stars_and_scrubs_config(stat_to_maximize=obj, categories=universe, percentile=base_percentile)
        elif kind == "spread_value":
            cfg = spread_value_config(stat_to_maximize=obj, categories=universe, percentile=base_percentile)
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
