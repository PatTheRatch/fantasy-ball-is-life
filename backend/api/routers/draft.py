"""Draft Room endpoints + private pool helpers."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, List, Literal, Optional

import pandas as pd
from backend.draft import auction_sim as auction_mc
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.deps import _df_records
from backend.draft.engine import (
    PlanSnapshot,
    apply_pick,
    build_initial_snapshot,
    pick_fallback,
    plan_id_for,
    relax_plan,
    triage_player,
)
from backend.draft.optimizer import OptimizeLineup
from backend.draft.strategies import (
    PlanConfig,
    build_plan_configs,
    custom_config,
    generate_portfolio,
)
from backend.draft import auction_sim as auction_mc


def _load_season_projections() -> Optional[list]:
    """Load active season projections from the framework store.

    Returns ``list[PlayerProjection]`` or ``None`` (fall through to
    the optimizer's legacy on-disk BBM_PROJECTIONS_PATH read).
    P-8: wires P-3's optimizer consumer swap into production.
    """
    try:
        from backend.projections import get_active_projections
        rows = get_active_projections("season")
        return rows if rows else None
    except Exception:
        return None
router = APIRouter(tags=["draft"])

class DraftPickEntry(BaseModel):
    player_key: str
    price: float = 0
    team_id: str = "you"
    is_user: bool = False


class DraftTargetPlayer(BaseModel):
    """A "make sure I get this player" prep-time favorite (not a real pick —
    doesn't touch the real picks log or budget). Every generated plan is built
    as if this player is already on the user's roster, at `expected_price` if
    given, else their own projected $ value. Ignored once the same player_key
    shows up for real in `picks` (won or lost) — the real outcome wins."""

    player_key: str
    expected_price: Optional[float] = None


class DraftPoolParams(BaseModel):
    """Optimizer knobs shared by /draft/plans, /draft/pick, /draft/triage, and
    /draft/relax — this is the "what am I actually optimizing for" surface."""

    # Capped at the spec's D8 target (docs/specs/DRAFT_ROOM.md) — the ESPN
    # integration audit (docs/ESPN_INTEGRATION_AUDIT.md) flagged an existing
    # endpoint's unbounded plan count as unbounded live-ESPN-call exposure;
    # this is the same shape of parameter, bounded from the start.
    n_plans: int = Field(default=10, ge=1, le=10)
    initial_budget: float = 200
    roster_size: int = 13
    minimum_game_threshold: float = 20
    # None -> config.GAMES_PER_WEEK (3.5, the constant locked in
    # docs/specs/MC_DRAFT_TARGETS.md §2.7). Was a hardcoded 3.0 here, which
    # silently disagreed with /optimizer/optimize and the MC spec.
    games_per_week: Optional[float] = None
    minimum_value_players: int = 3
    year: Optional[int] = None

    # Who prices each player. "bbm" is the uploaded projections file's own $
    # column (unchanged default). "forge" is Forge Value -- PatriotGames' own
    # projection-derived valuation (player_values.calculate_player_values),
    # scaled to this league's real team count (live ESPN settings) and this
    # draft's roster size/budget instead of trusting an external $ column.
    value_source: Literal["bbm", "forge"] = "bbm"

    # Team construction (engine support already existed; this is the plumbing
    # that was missing to actually drive it).
    exclude_players: List[str] = Field(default_factory=list)
    favorite_team: Optional[str] = None
    favorite_team_representation: int = 1
    target_players: List[DraftTargetPlayer] = Field(default_factory=list)

    # What to optimize for (draft_strategies.build_plan_configs' user knobs).
    target_categories: Optional[List[str]] = None
    base_percentile: Optional[float] = None
    stat_to_maximize: Optional[str] = None


class DraftPlansBody(DraftPoolParams):
    picks: List[DraftPickEntry] = Field(default_factory=list)


class CustomPlanBody(DraftPoolParams):
    """One hand-tuned plan, solved and returned standalone -- the "build your
    own, save it" flow (Patrick, 2026-07-10), as opposed to /draft/plans'
    fixed 10-plan recipe. Every solver knob is set directly by the caller
    rather than picked from a strategy shape."""

    picks: List[DraftPickEntry] = Field(default_factory=list)
    label: str
    constrained_categories: List[str]
    percentile: float
    stat_to_maximize: str
    ban_top_price: bool = False


class AuctionSimulationBody(DraftPoolParams):
    """Monte Carlo auction-value simulation request.

    ``players`` is optional so callers can either provide a normalized projection
    pool directly or let the backend use the same optimizer pool as /draft/plans.
    """

    picks: List[DraftPickEntry] = Field(default_factory=list)
    players: Optional[List[dict[str, Any]]] = None
    managers: Optional[List[dict[str, Any]]] = None
    n_managers: int = Field(default=12, ge=2, le=20)
    n_simulations: int = Field(default=500, ge=1, le=5000)
    seed: int = 7
    max_centers: int = Field(default=3, ge=1, le=8)
    use_model_values: bool = True
    dollar_one_players: Optional[int] = Field(default=None, ge=0)
    category_weights: Optional[dict[str, float]] = None
    star_exponent: float = Field(default=1.40, gt=0)
    return_sales: bool = False
    sales_limit: int = Field(default=500, ge=0, le=10000)


class DraftPickBody(DraftPoolParams):
    picks: List[DraftPickEntry]  # full updated list, including the new pick (undo-safe; §6)
    new_pick: DraftPickEntry
    prior_plans: List[dict]  # the `plans` array from the last /draft/plans or /draft/pick response


def _config_to_public(cfg: PlanConfig) -> dict:
    return {
        "label": cfg.label,
        "shape": cfg.shape,
        "constrained_categories": list(cfg.constrained_categories),
        "percentile": cfg.percentile,
        "minimum_value_players": cfg.minimum_value_players,
        "stat_to_maximize": cfg.stat_to_maximize,
        "ban_top_price": cfg.ban_top_price,
        "punts": list(cfg.punts),
    }


def _config_from_public(d: dict) -> PlanConfig:
    return PlanConfig(
        label=d["label"],
        shape=d["shape"],
        constrained_categories=tuple(d["constrained_categories"]),
        percentile=d["percentile"],
        minimum_value_players=d["minimum_value_players"],
        stat_to_maximize=d["stat_to_maximize"],
        ban_top_price=bool(d.get("ban_top_price", False)),
        punts=tuple(d.get("punts", ())),
    )


def _snapshot_from_public(d: dict) -> PlanSnapshot:
    return PlanSnapshot(
        plan_id=d["plan_id"],
        config=_config_from_public(d["config"]),
        roster=tuple(d["roster"]),
        health=d["health"],
        health_reason=d.get("health_reason"),
    )


def _build_pool_context(picks: List[DraftPickEntry], params: DraftPoolParams):
    """Everything a plan solve or the value board needs about the current draft
    state: who's off the board entirely (drafted by anyone) vs. who's on the
    user's own roster (charges budget, doesn't shrink the pool differently).
    """
    rival_keys = [p.player_key for p in picks if not p.is_user]
    user_picks = [p for p in picks if p.is_user]
    picked_keys = {p.player_key for p in user_picks}
    # Once a target player shows up for real (won or lost), the real pick wins —
    # applying the target on top would double-charge budget or fight the
    # exclude list. Only still-undecided targets get pre-locked into plans.
    decided_keys = picked_keys | set(rival_keys)
    candidate_targets = [t for t in params.target_players if t.player_key not in decided_keys]

    # P-8: load active season projections from the framework store.
    # Falls through to legacy BBM_PROJECTIONS_PATH when no upload exists.
    season_rows = _load_season_projections()

    def make_base_optimizer() -> OptimizeLineup:
        """No target_players applied — the pool as constrained by exclude/
        favorite-team/real picks only. Used both to resolve target validity/
        default price and to build the value board (draft_player never mutates
        player_data_df, so it's identical whichever way it's used for that)."""
        opt = OptimizeLineup(
            exclude_players=list(rival_keys) + list(params.exclude_players),
            games_per_week=params.games_per_week,
            initial_budget=params.initial_budget,
            year=params.year,
            roster_size=params.roster_size,
            minimum_value_players=params.minimum_value_players,
            minimum_game_threshold=params.minimum_game_threshold,
            favorite_team=params.favorite_team,
            favorite_team_representation=params.favorite_team_representation,
            value_col="Value",
            value_source=params.value_source,
            projections_rows=season_rows,
        )
        for p in user_picks:
            opt.draft_player(p.player_key, p.price)
        return opt

    # Resolve target validity + default price ONCE against the pool. A target
    # can legitimately not exist in player_data_df (below the games threshold,
    # the engine's own hardcoded do-not-draft list, a typo) — skip it and
    # report it rather than crash every solve with an unhelpful pandas index
    # error, matching this app's "never freeze on a bad input" principle.
    resolved_targets: List[tuple] = []
    skipped_target_keys: List[str] = []
    template: Optional[OptimizeLineup] = None
    try:
        template = make_base_optimizer()
        pool_names = template.player_data_df["Name"].str.lower()
        for t in candidate_targets:
            match = template.player_data_df.loc[pool_names == t.player_key]
            if match.empty:
                skipped_target_keys.append(t.player_key)
                continue
            price = t.expected_price if t.expected_price is not None else float(match["$"].iloc[0])
            resolved_targets.append((t.player_key, price))
    except Exception:
        skipped_target_keys.extend(t.player_key for t in candidate_targets)

    owned_keys = picked_keys | {key for key, _ in resolved_targets}

    def make_optimizer() -> OptimizeLineup:
        opt = make_base_optimizer()
        for key, price in resolved_targets:
            opt.draft_player(key, price)
        return opt

    def _solve(cfg: PlanConfig):
        opt = make_optimizer()
        # Category targets now default to Monte Carlo (simulated drafts of the
        # current pool), which needs no ESPN league history — only the projected
        # player pool the optimizer already holds. Constructing OptimizeLineup
        # still needs a live MyLeague for the draft board, so this path remains
        # unreachable from a no-network sandbox, but target-setting itself no
        # longer depends on get_universe_wins.
        opt.set_requirements(list(cfg.constrained_categories), percentile=cfg.percentile)
        try:
            res = opt.optimize_roster(cfg.stat_to_maximize)
        except ValueError:
            return None
        return res

    def solve_fn(cfg: PlanConfig) -> Optional[list[str]]:
        res = _solve(cfg)
        return list(res["Name"].str.lower()) if res is not None else None

    def solve_with_score_fn(cfg: PlanConfig) -> Optional[tuple[list[str], float]]:
        """Used only by /draft/relax's iterative sweep (draft_engine.relax_plan) —
        same solve, plus the resulting objective so candidate relaxations can be
        ranked without shadow prices (Gate 2)."""
        res = _solve(cfg)
        if res is None:
            return None
        score = float(res[f"{cfg.stat_to_maximize} PW"].sum())
        return list(res["Name"].str.lower()), score

    # Reuse the template pool (no solve) from target-resolution above to read
    # each player's fair "$" value and full stat line for the value board /
    # roster rows / next_target — the "solver-free floor" from §4/§6, and the
    # per-player data D5 locks in (Projected $ value, VOR/rank, all 9 category
    # contributions).
    value_lookup: Dict[str, float] = {}
    player_row_lookup: Dict[str, dict] = {}
    try:
        if template is None:
            template = make_base_optimizer()
        df = template.player_data_df
        value_lookup = dict(zip(df["Name"].str.lower(), df["$"]))
        for _, row in df.iterrows():
            key = str(row["Name"]).lower()
            player_row_lookup[key] = {
                "pos": row.get("Pos"),
                "team": row.get("Team"),
                "value": round(float(row["$"]), 1),
                "pts": round(float(row["PTS"]), 1),
                "reb": round(float(row["REB"]), 1),
                "ast": round(float(row["AST"]), 1),
                "stl": round(float(row["STL"]), 1),
                "blk": round(float(row["BLK"]), 1),
                "tpm": round(float(row["3PM"]), 1),
                "fg_pct": round(float(row["FG%"]), 3),
                "ft_pct": round(float(row["FT%"]), 3),
                # calculate_stats() negates TO (lower-is-better in the solver's
                # objective math); re-negate for a normal positive display value.
                "to": round(float(-row["TO"]), 1),
            }
    except Exception:
        pass  # value board / roster enrichment degrades to bare keys rather than failing the whole request

    all_drafted_keys = owned_keys | set(rival_keys)
    return (
        solve_fn,
        solve_with_score_fn,
        value_lookup,
        player_row_lookup,
        owned_keys,
        all_drafted_keys,
        skipped_target_keys,
    )


def _player_public(key: str, value_lookup: Dict[str, float], player_row_lookup: Dict[str, dict]) -> dict:
    row = player_row_lookup.get(key, {})
    return {"player_key": key, "max_bid": round(value_lookup.get(key, 0.0)), **row}


def _value_board(
    value_lookup: Dict[str, float],
    player_row_lookup: Dict[str, dict],
    all_drafted_keys: set,
    limit: int = 20,
) -> List[dict]:
    available = [(k, v) for k, v in value_lookup.items() if k not in all_drafted_keys]
    available.sort(key=lambda kv: kv[1], reverse=True)
    return [_player_public(k, value_lookup, player_row_lookup) for k, _ in available[:limit]]


def _snapshot_to_public(
    snap: PlanSnapshot,
    owned_keys: set,
    value_lookup: Dict[str, float],
    player_row_lookup: Dict[str, dict],
) -> dict:
    next_target = None
    if snap.health == "alive":
        candidates = [p for p in snap.roster if p not in owned_keys]
        if candidates:
            best = max(candidates, key=lambda p: value_lookup.get(p, 0.0))
            next_target = _player_public(best, value_lookup, player_row_lookup)
    return {
        "plan_id": snap.plan_id,
        "label": snap.config.label,
        "shape": snap.config.shape,
        "config": _config_to_public(snap.config),
        "roster": list(snap.roster),
        "players": [_player_public(p, value_lookup, player_row_lookup) for p in snap.roster],
        "health": snap.health,
        "health_reason": snap.health_reason,
        "next_target": next_target,
    }


def _fallback_public(plans: List[PlanSnapshot], public_plans: List[dict]) -> Optional[dict]:
    """The top still-Alive plan's recommended nomination (spec §4 warm-cache
    `fallback_next`) — reuses each plan's already-computed `next_target` rather
    than recomputing it, so this always agrees with what `plans` shows."""
    fb = pick_fallback(plans)
    if fb is None:
        return None
    fb_public = next(p for p in public_plans if p["plan_id"] == fb.plan_id)
    target = fb_public["next_target"]
    return {
        "plan_id": fb.plan_id,
        "label": fb.config.label,
        "player_key": target["player_key"] if target else None,
        "max_bid": target["max_bid"] if target else None,
    }


@router.post("/draft/auction-sim")
def draft_auction_sim(body: AuctionSimulationBody) -> dict:
    """Monte Carlo auction-price distributions.

    This is backend-only scaffolding for now: simulate the room with generic or
    caller-provided manager philosophies, then return each player's sale-price
    distribution and likely buyer archetype.
    """
    try:
        if body.players is not None:
            pool_df = pd.DataFrame(body.players)
        else:
            drafted_keys = [p.player_key for p in body.picks]
            opt = OptimizeLineup(
                exclude_players=drafted_keys,
                games_per_week=body.games_per_week,
                initial_budget=body.initial_budget,
                year=body.year,
                roster_size=body.roster_size,
                minimum_value_players=body.minimum_value_players,
                minimum_game_threshold=body.minimum_game_threshold,
                value_col="Value",
                projections_rows=_load_season_projections(),
            )
            pool_df = opt._mc_pool_df()

        if body.managers is None:
            profiles = auction_mc.default_manager_profiles(body.n_managers)
        else:
            profiles = [
                auction_mc.ManagerProfile.from_mapping(raw, idx)
                for idx, raw in enumerate(body.managers)
            ]

        summary, sales = auction_mc.simulate_auction_prices(
            pool_df,
            manager_profiles=profiles,
            n_simulations=body.n_simulations,
            budget=body.initial_budget,
            roster_size=body.roster_size,
            max_centers=body.max_centers,
            rng_seed=body.seed,
            use_model_values=body.use_model_values,
            dollar_one_players=body.dollar_one_players,
            category_weights=body.category_weights,
            star_exponent=body.star_exponent,
            return_sales=body.return_sales,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    sales_out = []
    if body.return_sales and sales is not None:
        sales_out = _df_records(sales.head(body.sales_limit))

    return {
        "settings": {
            "n_simulations": body.n_simulations,
            "n_managers": len(profiles),
            "budget": body.initial_budget,
            "roster_size": body.roster_size,
            "seed": body.seed,
            "use_model_values": body.use_model_values,
            "dollar_one_players": body.dollar_one_players,
            "star_exponent": body.star_exponent,
        },
        "manager_profiles": [asdict(p) for p in profiles],
        "summary": _df_records(summary),
        "sales": sales_out,
    }


@router.post("/draft/plans")
def draft_plans(body: DraftPlansBody) -> dict:
    """Generate the initial saved-plan portfolio (spec §2 criterion 4 / §4).
    Solves each strategy config (draft_strategies.build_plan_configs) against
    the current pool, keeps only the diverse, feasible subset
    (draft_strategies.generate_portfolio), and returns the full snapshot the
    client renders from — including the solver-free value-board floor."""
    solve_fn, _, value_lookup, player_row_lookup, owned_keys, all_drafted_keys, skipped_targets = _build_pool_context(
        body.picks, body
    )

    try:
        configs = build_plan_configs(
            body.n_plans,
            target_categories=body.target_categories,
            base_percentile=body.base_percentile,
            stat_to_maximize=body.stat_to_maximize,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        plans = generate_portfolio(configs, solve_fn, limit=body.n_plans)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    snapshots = build_initial_snapshot(plans)
    public_plans = [_snapshot_to_public(s, owned_keys, value_lookup, player_row_lookup) for s in snapshots]

    return {
        "plans": public_plans,
        "fallback_next": _fallback_public(snapshots, public_plans),
        "value_board": _value_board(value_lookup, player_row_lookup, all_drafted_keys),
        "skipped_targets": skipped_targets,
    }


@router.post("/draft/plans/custom")
def draft_plans_custom(body: CustomPlanBody) -> dict:
    """Solve one fully user-specified config and return it standalone -- the
    counterpart to /draft/plans' fixed 10-plan recipe, for the "build your
    own, save it" flow. Doesn't touch or know about the rest of the client's
    working portfolio; the caller merges the result in on success."""
    solve_fn, _, value_lookup, player_row_lookup, owned_keys, all_drafted_keys, skipped_targets = _build_pool_context(
        body.picks, body
    )

    try:
        cfg = custom_config(
            label=body.label,
            categories=body.constrained_categories,
            percentile=body.percentile,
            stat_to_maximize=body.stat_to_maximize,
            minimum_value_players=body.minimum_value_players,
            ban_top_price=body.ban_top_price,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    try:
        roster = solve_fn(cfg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    if not roster:
        raise HTTPException(
            status_code=422,
            detail="no feasible roster for this configuration against the current pool",
        )

    snap = PlanSnapshot(plan_id=plan_id_for(cfg), config=cfg, roster=tuple(roster), health="alive")
    public = _snapshot_to_public(snap, owned_keys, value_lookup, player_row_lookup)

    return {
        "plan": public,
        "value_board": _value_board(value_lookup, player_row_lookup, all_drafted_keys),
        "skipped_targets": skipped_targets,
    }


@router.post("/draft/pick")
def draft_pick(body: DraftPickBody) -> dict:
    """Log a pick and recompute (spec §4 per-pick execution model): O(1)
    health check on every saved plan, targeted re-solve only for the plans the
    pick broke (normally 0-2, not all `n_plans`). This is the "warm cache" that
    makes auto-advance (§2 criterion 5) instant and keeps the recommendation
    surface from ever going empty (§2 criterion 2)."""
    solve_fn, _, value_lookup, player_row_lookup, owned_keys, all_drafted_keys, skipped_targets = _build_pool_context(
        body.picks, body
    )

    try:
        prior = [_snapshot_from_public(d) for d in body.prior_plans]
    except (KeyError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"malformed prior_plans entry: {e}") from e

    try:
        updated = apply_pick(prior, body.new_pick.player_key, solve_fn)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    public_plans = [_snapshot_to_public(s, owned_keys, value_lookup, player_row_lookup) for s in updated]

    return {
        "plans": public_plans,
        "fallback_next": _fallback_public(updated, public_plans),
        "value_board": _value_board(value_lookup, player_row_lookup, all_drafted_keys),
        "skipped_targets": skipped_targets,
    }


class DraftTriageBody(DraftPoolParams):
    picks: List[DraftPickEntry] = Field(default_factory=list)
    prior_plans: List[dict]
    player_key: str


@router.post("/draft/triage")
def draft_triage(body: DraftTriageBody) -> dict:
    """On-the-block triage (spec §2 criterion 3 / §4). Classifies the player
    the user set as "on the block" against the portfolio the client already
    has — Relevant (in >=1 still-Alive plan, or a top-of-board value target)
    vs. Safe to pass. No solve; reads the already-computed snapshot, same as
    the spec's "<1s, no fresh solve" requirement."""
    _, _, value_lookup, player_row_lookup, owned_keys, all_drafted_keys, _ = _build_pool_context(body.picks, body)

    try:
        prior = [_snapshot_from_public(d) for d in body.prior_plans]
    except (KeyError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"malformed prior_plans entry: {e}") from e

    # "Not a value target" (spec §2 criterion 3's Safe-to-pass clause) is
    # defined as: not among the best remaining players by raw value, using
    # the same solver-free value board shown elsewhere in the UI.
    value_target_keys = frozenset(
        p["player_key"] for p in _value_board(value_lookup, player_row_lookup, all_drafted_keys, limit=10)
    )

    result = triage_player(body.player_key, prior, frozenset(owned_keys), value_lookup, value_target_keys)
    return {
        "player_key": result.player_key,
        "relevant": result.relevant,
        "in_plans": list(result.in_plans),
        "max_bid": result.max_bid,
        "reason": result.reason,
    }


class DraftRelaxBody(DraftPoolParams):
    picks: List[DraftPickEntry] = Field(default_factory=list)
    prior_plans: List[dict]  # must all be Broken — this endpoint won't run otherwise
    plan_id: Optional[str] = None  # which saved plan to relax from; defaults to the first


@router.post("/draft/relax")
def draft_relax(body: DraftRelaxBody) -> dict:
    """Graceful relaxation when every saved plan is Broken (spec §2 criterion
    6). Runs the §4/§5 iterative sweep (Gate 2's resolved approach, since the
    current solver stack exposes neither shadow prices nor an infeasibility
    certificate — DRAFT_ROOM_REVIEW.md): re-solve `plan_id`'s config once per
    category with that category dropped, up to 9 solves (~36s worst case),
    and return the feasible candidate the solver could do the most with.

    This only *proposes* — per D10 (one-tap confirm), the caller applies it
    client-side rather than this endpoint mutating a server-held plan. No
    server-side caching either: the client already holds (and can re-render)
    the proposal it gets back, which is what the spec's "cached" note means
    in this stateless design (see draft_engine.py's module docstring)."""
    if not body.prior_plans:
        raise HTTPException(status_code=422, detail="prior_plans is required to relax from")

    try:
        prior = [_snapshot_from_public(d) for d in body.prior_plans]
    except (KeyError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"malformed prior_plans entry: {e}") from e

    if pick_fallback(prior) is not None:
        raise HTTPException(
            status_code=409,
            detail="at least one saved plan is still Alive; relax only applies when every plan is Broken",
        )

    base = next((p for p in prior if p.plan_id == body.plan_id), None) if body.plan_id else prior[0]
    if base is None:
        raise HTTPException(status_code=404, detail=f"no plan found for plan_id={body.plan_id!r}")

    _, solve_with_score_fn, value_lookup, player_row_lookup, owned_keys, all_drafted_keys, _ = _build_pool_context(
        body.picks, body
    )

    try:
        proposal = relax_plan(base.config, solve_with_score_fn)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    if proposal is None:
        # The wall isn't category-driven (budget/position scarcity) — the
        # value board floor (§6) is still available, this just can't help.
        return {
            "proposal": None,
            "value_board": _value_board(value_lookup, player_row_lookup, all_drafted_keys),
        }

    snap = PlanSnapshot(
        plan_id=base.plan_id + "_relaxed",
        config=proposal.config,
        roster=proposal.roster,
        health="alive",
    )
    public = _snapshot_to_public(snap, owned_keys, value_lookup, player_row_lookup)
    public["dropped_category"] = proposal.dropped_category
    public["objective_score"] = round(proposal.objective_score, 1)
    public["relaxed_from_plan_id"] = base.plan_id

    return {
        "proposal": public,
        "value_board": _value_board(value_lookup, player_row_lookup, all_drafted_keys),
    }


@router.get("/draft/players")
def draft_players_search(q: str = "") -> List[dict]:
    """Autocomplete for the Draft Room's player inputs. Same `OptimizeLineup`
    + projections pattern as `_build_pool_context`, but no picks/targets, no
    `set_requirements`/solve — just a case-insensitive substring filter over
    the projected pool's Name column, so it stays fast."""
    q = q.strip().lower()
    if len(q) < 2:
        return []
    try:
        df = OptimizeLineup(value_col="Value").player_data_df
    except Exception:
        return []
    matches = df[df["Name"].str.lower().str.contains(q, na=False)]
    return [
        {
            "player_key": str(row["Name"]).lower(),
            "pos": row.get("Pos"),
            "team": row.get("Team"),
            "value": round(float(row["$"]), 1) if pd.notna(row["$"]) else None,
        }
        for _, row in matches.head(15).iterrows()
    ]


