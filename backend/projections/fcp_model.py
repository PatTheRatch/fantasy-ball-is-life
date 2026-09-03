"""FCP Projections M-3b — the veteran model (v1).

Spec: ``docs/specs/FCP_PROJECTIONS.md`` §3. Projects a player's next season
from their own recent history, league-wide aging behavior, and a team-level
minutes budget.

The pipeline, in order (each step is a separate function so it can be tested
and swapped independently):

1. **Per-minute rates** — weighted across the last ``len(weights)`` seasons
   (recency × reliability), so a 2,400-minute season counts for more than a
   200-minute one at the same recency.
2. **Small-sample regression** — rates are shrunk toward the league mean by
   total minutes, so a 90-minute cameo doesn't project as a starter.
3. **Age curve** — a multiplicative adjustment fitted from league-wide
   year-over-year changes, with a documented fallback when history is thin.
4. **Minutes** — projected MPG from recent minutes, then scaled so no team
   exceeds a sane per-game minutes budget (``TEAM_MINUTES_PER_GAME``).
5. **Games played** — projected separately from availability history and
   age, so injury expectation never contaminates per-game ability. (The
   spec is explicit about this: consumers already multiply rate × games.)
6. **Percentages** — FG%/FT% are derived from projected makes and attempts,
   never averaged, because attempt volume matters.

Rookies are deliberately out of scope — they need the separate translation
model (M-5). Players with no prior season are absent from the output and
reported by the backtest harness as ``excluded_no_prediction``.

The season weights are the spec's stated defaults, NOT fitted values. The
spec is explicit that they should be "learned by backtest, not chosen by
vibes" — ``fit_season_weights()`` does that once real history is available;
until then these are documented starting points, not claims.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables (spec §3 defaults — see module docstring on the weights)
# ---------------------------------------------------------------------------

#: Recency weights, most-recent season first. Spec §3.1's stated example.
DEFAULT_SEASON_WEIGHTS: tuple[float, ...] = (0.55, 0.30, 0.15)

#: Minutes at which a player's own rates carry half the weight against the
#: league prior. Shrinkage is ``m / (m + K)`` — at K minutes a player is a
#: 50/50 blend of themselves and the league, which for a ~2,000-minute
#: starter is ~80% themselves and for a 90-minute cameo is ~15%.
SHRINKAGE_MINUTES: float = 400.0

#: Five players on the floor × 48 minutes. Teams that sum above this are
#: scaled back proportionally — "not a rotation, a clown car" (spec §3.3).
TEAM_MINUTES_PER_GAME: float = 240.0

#: A full NBA season. Used as the ceiling on projected games played.
GAMES_IN_SEASON: int = 82

#: Counting stats carried per-minute through the model. Percentages are NOT
#: here — they are derived from makes/attempts at the end (spec §3.5).
RATE_STATS: tuple[str, ...] = (
    "pts", "reb", "ast", "stl", "blk", "tpm", "tov",
    "fgm", "fga", "ftm", "fta", "tpa",
)

#: Fallback age curve — multiplicative factor on per-minute production by
#: age, normalized to 1.0 at the peak. Used only when the supplied history
#: is too thin to fit a curve (``fit_age_curve`` needs several seasons of
#: overlapping players). Shape reflects the well-established NBA arc: rise
#: into the mid-20s, a plateau through 29, gentle decline through the early
#: 30s, steeper after 34.
FALLBACK_AGE_CURVE: dict[int, float] = {
    19: 0.86, 20: 0.90, 21: 0.93, 22: 0.96, 23: 0.98, 24: 0.99,
    25: 1.00, 26: 1.00, 27: 1.00, 28: 0.995, 29: 0.99,
    30: 0.98, 31: 0.965, 32: 0.95, 33: 0.93, 34: 0.90,
    35: 0.87, 36: 0.83, 37: 0.79, 38: 0.74, 39: 0.70, 40: 0.65,
}

_MIN_AGE, _MAX_AGE = min(FALLBACK_AGE_CURVE), max(FALLBACK_AGE_CURVE)


# ---------------------------------------------------------------------------
# Assumptions (M-4 will make these editable; the model already consumes them)
# ---------------------------------------------------------------------------

@dataclass
class PlayerAssumption:
    """A manual override for one player (spec §4).

    M-4 adds the table and admin CRUD; the model consumes them now so that
    landing M-4 is a data change, not a model change. Every field is
    optional — an assumption overrides only what it sets.
    """

    person_id: int
    projected_mpg: Optional[float] = None
    projected_games: Optional[float] = None
    usage_adjustment: Optional[float] = None   # multiplicative, 1.0 = neutral
    notes: str = ""


@dataclass
class ProjectionRun:
    """Model output plus the provenance needed to explain it.

    ``projections`` is the backtest-ready frame (``person_id`` + per-game
    stats, matching ``backtest.evaluate``'s ``predictions`` contract).
    """

    target_season: int
    projections: pd.DataFrame
    age_curve: dict[int, float] = field(default_factory=dict)
    season_weights: tuple[float, ...] = DEFAULT_SEASON_WEIGHTS
    players_projected: int = 0
    players_skipped_no_history: int = 0


# ---------------------------------------------------------------------------
# 1–2. Per-minute rates, weighted and shrunk
# ---------------------------------------------------------------------------

def weighted_per_minute_rates(
    history: pd.DataFrame,
    *,
    weights: Sequence[float] = DEFAULT_SEASON_WEIGHTS,
) -> pd.DataFrame:
    """Per-minute rates per player, weighted by recency × minutes played.

    ``history`` holds prior seasons only (the caller filters). For each
    player the most recent ``len(weights)`` seasons are combined; a season's
    contribution is ``recency_weight × minutes``, so both how recent and how
    substantial a season was matter.

    Returns one row per player: ``person_id``, ``rate_<stat>`` columns,
    ``total_minutes`` (the weighted denominator, used for shrinkage), plus
    ``last_age``, ``last_mpg``, ``last_gp``, ``last_season`` and ``team``
    carried through for later stages.
    """
    if history.empty:
        return pd.DataFrame()

    df = history.sort_values(["person_id", "season"], ascending=[True, False]).copy()
    # Keep the N most recent seasons per player.
    df["_recency"] = df.groupby("person_id").cumcount()
    df = df[df["_recency"] < len(weights)].copy()
    df["_w"] = df["_recency"].map(lambda i: weights[int(i)])

    # Minutes actually played that season. `minutes` is the season total.
    df["_minutes"] = pd.to_numeric(df["minutes"], errors="coerce").fillna(0.0)
    # A season with no minutes carries no information about rates.
    df = df[df["_minutes"] > 0].copy()
    if df.empty:
        return pd.DataFrame()

    df["_weight"] = df["_w"] * df["_minutes"]

    out: dict[str, pd.Series] = {}
    grouped = df.groupby("person_id")

    for stat in RATE_STATS:
        if stat not in df.columns:
            continue
        per_game = pd.to_numeric(df[stat], errors="coerce").fillna(0.0)
        gp = pd.to_numeric(df["gp"], errors="coerce").fillna(0.0)
        # Season total for the stat, then per weighted minute.
        season_total = per_game * gp
        num = (season_total * df["_w"]).groupby(df["person_id"]).sum()
        den = (df["_minutes"] * df["_w"]).groupby(df["person_id"]).sum()
        out[f"rate_{stat}"] = num / den.replace(0, np.nan)

    rates = pd.DataFrame(out)
    rates["total_minutes"] = grouped["_weight"].sum() / grouped["_w"].sum()

    # Carry the most recent season's context forward (recency 0 == latest).
    latest = df[df["_recency"] == 0].set_index("person_id")
    for src, dst in (
        ("age", "last_age"), ("mpg", "last_mpg"),
        ("gp", "last_gp"), ("season", "last_season"),
    ):
        if src in latest.columns:
            rates[dst] = pd.to_numeric(latest[src], errors="coerce")
    if "team" in latest.columns:
        rates["team"] = latest["team"]

    # Availability history feeds the games-played model.
    rates["mean_gp"] = grouped.apply(
        lambda g: float(np.average(
            pd.to_numeric(g["gp"], errors="coerce").fillna(0.0), weights=g["_w"],
        )),
        include_groups=False,
    )

    return rates.reset_index()


def shrink_rates(
    rates: pd.DataFrame,
    *,
    shrinkage_minutes: float = SHRINKAGE_MINUTES,
) -> pd.DataFrame:
    """Regress each player's rates toward the league mean by sample size.

    ``weight = m / (m + K)``. A 2,000-minute season keeps ~83% of its own
    signal; a 90-minute one keeps ~18%. This is what stops a garbage-time
    scoring binge from projecting as a starter's rate.
    """
    if rates.empty:
        return rates

    out = rates.copy()
    minutes = out["total_minutes"].fillna(0.0)
    w = minutes / (minutes + shrinkage_minutes)

    for col in [c for c in out.columns if c.startswith("rate_")]:
        vals = out[col]
        # Minutes-weighted league mean: the prior is what a league-average
        # minute looks like, not what an average *player* looks like.
        prior = np.average(
            vals.fillna(0.0), weights=minutes.clip(lower=0.0),
        ) if minutes.sum() > 0 else vals.mean()
        out[col] = w * vals.fillna(prior) + (1.0 - w) * prior

    return out


# ---------------------------------------------------------------------------
# 3. Age curve
# ---------------------------------------------------------------------------

def _composite_rate(df: pd.DataFrame) -> pd.Series:
    """A single per-minute production number used to measure aging.

    Deliberately coarse: the age curve is one multiplicative factor applied
    to all counting rates (spec §3.2), so it needs one summary of "how much
    a player produces per minute", not nine separate curves. Turnovers are
    excluded — being older doesn't make a turnover good.
    """
    parts = [c for c in ("pts", "reb", "ast", "stl", "blk") if c in df.columns]
    gp = pd.to_numeric(df["gp"], errors="coerce").fillna(0.0)
    minutes = pd.to_numeric(df["minutes"], errors="coerce").replace(0, np.nan)
    total = sum(pd.to_numeric(df[c], errors="coerce").fillna(0.0) * gp for c in parts)
    return total / minutes


def fit_age_curve(
    history: pd.DataFrame,
    *,
    min_minutes: float = 500.0,
    min_pairs_per_age: int = 20,
) -> dict[int, float]:
    """Fit a league-wide multiplicative age curve from consecutive seasons.

    For every player-season pair at consecutive ages, take the ratio of
    per-minute composite production. The median ratio at each age transition
    is the league-wide aging effect at that age — medians rather than means
    so a handful of outlier seasons don't bend the curve.

    Ages with fewer than ``min_pairs_per_age`` observations fall back to the
    documented default rather than trusting a noisy estimate. Returns a dict
    normalized so the peak age is 1.0.
    """
    if history.empty or "age" not in history.columns:
        logger.info("fit_age_curve: no history — using the fallback curve")
        return dict(FALLBACK_AGE_CURVE)

    df = history.copy()
    df["_rate"] = _composite_rate(df)
    df["_minutes"] = pd.to_numeric(df["minutes"], errors="coerce").fillna(0.0)
    df["_age"] = pd.to_numeric(df["age"], errors="coerce")
    df = df[(df["_minutes"] >= min_minutes) & df["_rate"].notna() & df["_age"].notna()]

    if df.empty:
        return dict(FALLBACK_AGE_CURVE)

    # Join each season to the same player's next season.
    nxt = df[["person_id", "season", "_rate", "_age"]].copy()
    nxt["season"] = nxt["season"] - 1
    pairs = df.merge(
        nxt, on=["person_id", "season"], suffixes=("", "_next"), how="inner",
    )
    pairs = pairs[pairs["_rate"] > 0]
    if pairs.empty:
        return dict(FALLBACK_AGE_CURVE)

    pairs["_ratio"] = pairs["_rate_next"] / pairs["_rate"]
    # Guard against division blowups from tiny denominators.
    pairs = pairs[(pairs["_ratio"] > 0.2) & (pairs["_ratio"] < 5.0)]

    deltas: dict[int, float] = {}
    for age, grp in pairs.groupby(pairs["_age"].round().astype(int)):
        if len(grp) >= min_pairs_per_age:
            deltas[int(age)] = float(grp["_ratio"].median())

    if not deltas:
        logger.info("fit_age_curve: too few paired seasons — using the fallback")
        return dict(FALLBACK_AGE_CURVE)

    # Chain the year-over-year deltas into a level curve.
    ages = range(_MIN_AGE, _MAX_AGE + 1)
    curve: dict[int, float] = {}
    level = 1.0
    for age in ages:
        curve[age] = level
        level *= deltas.get(age, FALLBACK_AGE_CURVE.get(age + 1, 1.0) /
                            FALLBACK_AGE_CURVE.get(age, 1.0))

    peak = max(curve.values())
    if peak <= 0:
        return dict(FALLBACK_AGE_CURVE)
    return {a: v / peak for a, v in curve.items()}


def age_factor(age: Optional[float], curve: Mapping[int, float]) -> float:
    """Look up the multiplicative age adjustment, clamped to the curve's range."""
    if age is None or pd.isna(age):
        return 1.0
    a = int(round(float(age)))
    if a < _MIN_AGE:
        a = _MIN_AGE
    elif a > _MAX_AGE:
        a = _MAX_AGE
    return float(curve.get(a, 1.0))


# ---------------------------------------------------------------------------
# 4. Minutes, with team coherence
# ---------------------------------------------------------------------------

def project_minutes(
    rates: pd.DataFrame,
    *,
    assumptions: Optional[Mapping[int, PlayerAssumption]] = None,
    team_minutes_cap: float = TEAM_MINUTES_PER_GAME,
) -> pd.Series:
    """Projected MPG per player, capped so team totals stay physical.

    Starts from the player's recent MPG, applies any manual assumption, then
    enforces team coherence: if a team's projected minutes exceed the budget
    (5 on the floor × 48), every player on it is scaled down proportionally.
    Teams under the budget are left alone — a thin roster is a real thing,
    and inflating it would invent minutes nobody plays.
    """
    if rates.empty:
        return pd.Series(dtype="float64")

    mpg = pd.to_numeric(rates.get("last_mpg"), errors="coerce").fillna(0.0)
    mpg = mpg.clip(lower=0.0, upper=48.0)

    if assumptions:
        for idx, pid in rates["person_id"].items():
            a = assumptions.get(int(pid))
            if a is not None and a.projected_mpg is not None:
                mpg.at[idx] = float(a.projected_mpg)

    if "team" not in rates.columns:
        return mpg

    team_totals = mpg.groupby(rates["team"]).transform("sum")
    over = team_totals > team_minutes_cap
    scale = pd.Series(1.0, index=mpg.index)
    scale[over] = team_minutes_cap / team_totals[over]
    return mpg * scale


# ---------------------------------------------------------------------------
# 5. Games played
# ---------------------------------------------------------------------------

def project_games(
    rates: pd.DataFrame,
    curve: Mapping[int, float],
    *,
    assumptions: Optional[Mapping[int, PlayerAssumption]] = None,
) -> pd.Series:
    """Projected games played — availability history, nudged by age.

    Kept strictly separate from per-game ability (spec §3.4). Older players
    miss more games, so the age factor is applied to availability as well,
    but at a fraction of its strength: aging costs availability more slowly
    than it costs per-minute production.
    """
    if rates.empty:
        return pd.Series(dtype="float64")

    base = pd.to_numeric(rates.get("mean_gp"), errors="coerce")
    base = base.fillna(pd.to_numeric(rates.get("last_gp"), errors="coerce"))
    base = base.fillna(0.0).clip(lower=0.0, upper=GAMES_IN_SEASON)

    ages = rates.get("last_age")
    if ages is not None:
        # Age enters availability at half strength.
        factors = ages.map(lambda a: 1.0 - (1.0 - age_factor(a, curve)) * 0.5)
        base = base * factors

    if assumptions:
        for idx, pid in rates["person_id"].items():
            a = assumptions.get(int(pid))
            if a is not None and a.projected_games is not None:
                base.at[idx] = float(a.projected_games)

    return base.clip(lower=0.0, upper=GAMES_IN_SEASON)


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

def project_season(
    history: pd.DataFrame,
    target_season: int,
    *,
    weights: Sequence[float] = DEFAULT_SEASON_WEIGHTS,
    shrinkage_minutes: float = SHRINKAGE_MINUTES,
    age_curve: Optional[Mapping[int, float]] = None,
    assumptions: Optional[Iterable[PlayerAssumption]] = None,
    team_minutes_cap: float = TEAM_MINUTES_PER_GAME,
) -> ProjectionRun:
    """Project ``target_season`` from seasons strictly before it.

    Only rows with ``season < target_season`` are used — the guard is here
    rather than left to the caller because leaking the target season into
    its own prediction would silently invalidate every backtest.

    The returned frame matches ``backtest.evaluate``'s ``predictions``
    contract: ``person_id`` plus per-game ``pts, reb, ast, stl, blk, tpm,
    tov, fgm, fga, ftm, fta``, so it can be scored directly against actuals.
    """
    if history.empty:
        return ProjectionRun(
            target_season=target_season, projections=pd.DataFrame(),
            age_curve={}, season_weights=tuple(weights),
        )

    prior = history[pd.to_numeric(history["season"], errors="coerce") < target_season]
    n_players_total = history["person_id"].nunique()
    if prior.empty:
        return ProjectionRun(
            target_season=target_season, projections=pd.DataFrame(),
            age_curve={}, season_weights=tuple(weights),
            players_skipped_no_history=n_players_total,
        )

    curve = dict(age_curve) if age_curve is not None else fit_age_curve(prior)
    amap = {a.person_id: a for a in (assumptions or [])}

    rates = weighted_per_minute_rates(prior, weights=weights)
    if rates.empty:
        return ProjectionRun(
            target_season=target_season, projections=pd.DataFrame(),
            age_curve=curve, season_weights=tuple(weights),
            players_skipped_no_history=n_players_total,
        )
    rates = shrink_rates(rates, shrinkage_minutes=shrinkage_minutes)

    # Age applies to production per minute, and the assumption layer can
    # scale usage on top of it.
    age_mult = rates["last_age"].map(lambda a: age_factor(a, curve)) \
        if "last_age" in rates.columns else pd.Series(1.0, index=rates.index)
    usage_mult = pd.Series(1.0, index=rates.index)
    if amap:
        for idx, pid in rates["person_id"].items():
            a = amap.get(int(pid))
            if a is not None and a.usage_adjustment is not None:
                usage_mult.at[idx] = float(a.usage_adjustment)

    mpg = project_minutes(rates, assumptions=amap, team_minutes_cap=team_minutes_cap)
    games = project_games(rates, curve, assumptions=amap)

    out = pd.DataFrame({"person_id": rates["person_id"]})
    for stat in RATE_STATS:
        col = f"rate_{stat}"
        if col not in rates.columns:
            continue
        # Turnovers are a cost, not a skill — aging shouldn't "improve" them,
        # so the age/usage multipliers apply to production only.
        mult = age_mult * usage_mult if stat != "tov" else pd.Series(1.0, index=rates.index)
        out[stat] = (rates[col].fillna(0.0) * mult * mpg).astype(float)

    # Prefixed so they never collide with the actuals' own `gp`/`mpg` when
    # this frame is merged against them in the backtest harness.
    out["projected_mpg"] = mpg.astype(float)
    out["projected_gp"] = games.astype(float)
    out["age"] = rates.get("last_age")
    if "team" in rates.columns:
        out["team"] = rates["team"]

    # Percentages from projected makes/attempts — never averaged (spec §3.5).
    out["fg_pct"] = _safe_ratio(out.get("fgm"), out.get("fga"))
    out["ft_pct"] = _safe_ratio(out.get("ftm"), out.get("fta"))

    return ProjectionRun(
        target_season=target_season,
        projections=out.reset_index(drop=True),
        age_curve=curve,
        season_weights=tuple(weights),
        players_projected=len(out),
        players_skipped_no_history=max(0, n_players_total - len(out)),
    )


def _safe_ratio(num: Optional[pd.Series], den: Optional[pd.Series]) -> pd.Series:
    """makes / attempts, with 0 attempts yielding NaN rather than inf."""
    if num is None or den is None:
        return pd.Series(dtype="float64")
    d = den.replace(0, np.nan)
    return (num / d).astype(float)


# ---------------------------------------------------------------------------
# Weight fitting (the spec's "learned by backtest, not chosen by vibes")
# ---------------------------------------------------------------------------

def fit_season_weights(
    history: pd.DataFrame,
    *,
    target_seasons: Sequence[int],
    candidates: Optional[Sequence[Sequence[float]]] = None,
    min_gp: int = 20,
) -> tuple[tuple[float, ...], pd.DataFrame]:
    """Grid-search recency weights against held-out seasons.

    Scores each candidate by mean per-category MAE across ``target_seasons``
    and returns the best plus the full comparison table. This is what turns
    ``DEFAULT_SEASON_WEIGHTS`` from a documented guess into a fitted value —
    it needs real ``nba_player_seasons`` history to mean anything.
    """
    from backend.projections.backtest import evaluate

    if candidates is None:
        candidates = [
            (1.0,),
            (0.7, 0.3),
            (0.55, 0.30, 0.15),
            (0.5, 0.3, 0.2),
            (0.45, 0.35, 0.20),
            (0.4, 0.3, 0.2, 0.1),
        ]

    rows: list[dict[str, object]] = []
    for cand in candidates:
        maes: list[float] = []
        for season in target_seasons:
            run = project_season(history, season, weights=cand)
            if run.projections.empty:
                continue
            actuals = history[
                pd.to_numeric(history["season"], errors="coerce") == season
            ]
            if actuals.empty:
                continue
            result = evaluate(run.projections, actuals, min_gp=min_gp)
            if result.mae:
                maes.append(float(np.mean(list(result.mae.values()))))
        if maes:
            rows.append({"weights": tuple(cand), "mean_mae": float(np.mean(maes))})

    table = pd.DataFrame(rows).sort_values("mean_mae").reset_index(drop=True)
    best = tuple(table.iloc[0]["weights"]) if not table.empty else DEFAULT_SEASON_WEIGHTS
    return best, table
