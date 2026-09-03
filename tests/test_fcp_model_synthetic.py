"""FCP Projections M-3b — synthetic-season validation (spec §7).

The spec asks for the harness to be "tested against a synthetic season with
known answers". This goes one step further and uses that synthetic world as
a merge-gate rehearsal: the model must beat the naive last-season-repeated
baseline on data whose generative process we control.

This is NOT a substitute for the real backtest. It proves the model's
*structure* is sound — that averaging over weighted seasons, regressing
small samples, and applying an age curve genuinely recover talent from
noisy observations. Whether the real NBA behaves like this world is exactly
what ``python -m backend.projections.backtest`` answers once
``nba_player_seasons`` is populated.

The world: each player has a fixed true per-minute talent. Observed seasons
are that talent, aged, plus observation noise whose size falls with minutes
played — mirroring the real problem, where a 90-minute cameo is a far
noisier read on talent than a 2,400-minute season.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from backend.projections.backtest import evaluate
from backend.projections.fcp_model import (
    FALLBACK_AGE_CURVE,
    GAMES_IN_SEASON,
    TEAM_MINUTES_PER_GAME,
    project_season,
)

SEASONS = list(range(2010, 2026))   # 16 seasons, like the real table
TARGET = 2025
N_PLAYERS = 1900                    # ~1,915 unique players in production
N_TEAMS = 30
SEED = 20260903

# Per-minute talent means for the counting stats, roughly NBA-shaped.
# Makes are NOT drawn independently — they are derived from attempts times a
# shooting percentage below, so no synthetic player ever makes more shots
# than they take.
_TALENT_MEANS = {
    "pts": 0.45, "reb": 0.18, "ast": 0.11, "stl": 0.030,
    "blk": 0.020, "tov": 0.055,
    "fga": 0.380, "fta": 0.110, "tpa": 0.150,
}

#: Shooting percentages: (mean, sigma), clipped to a plausible range.
_PCT_TALENTS = {
    "fg": (0.470, 0.055, 0.32, 0.68),
    "ft": (0.770, 0.090, 0.40, 0.95),
    "tp": (0.355, 0.055, 0.15, 0.50),
}


def _build_world(seed: int = SEED) -> pd.DataFrame:
    """Generate seasons whose underlying talent we know exactly.

    Two properties matter as much as the talent model, because an earlier
    version of this fixture had neither and consequently passed while the
    model was under-projecting minutes ~3x on real data:

    1. **Careers end.** Players debut and retire, so the historical pool is
       several times larger than the active league (the real table is 1,915
       players over 16 seasons, ~570 active in any one). A fixture where
       everyone plays every season never exercises the roster filter.
    2. **Team minutes obey the identity.** A team plays 240 minutes per
       game, so ``Σ(mpg_i × gp_i) = 240 × 82`` for each team-season.
       Minutes are allocated to satisfy that rather than drawn
       independently, so the team-coherence budget is tested against
       realistic rosters instead of arbitrary ones.
    """
    rng = np.random.default_rng(seed)

    talent = {
        stat: np.clip(rng.lognormal(mean=np.log(m), sigma=0.35, size=N_PLAYERS), 1e-4, None)
        for stat, m in _TALENT_MEANS.items()
    }
    # Shooting skill is a rate, not a volume — a player's makes follow from
    # their attempts and how well they shoot.
    pct_talent = {
        kind: np.clip(rng.normal(mu, sigma, size=N_PLAYERS), lo, hi)
        for kind, (mu, sigma, lo, hi) in _PCT_TALENTS.items()
    }
    # Ages spread across a career so the age curve has something to do.
    debut_age = rng.integers(19, 30, size=N_PLAYERS)
    # Careers end: each player is in the league for a bounded stretch, so
    # the historical pool is far larger than any single season's league.
    debut_idx = rng.integers(-len(SEASONS), len(SEASONS), size=N_PLAYERS)
    career_len = np.clip(rng.normal(6, 3, size=N_PLAYERS), 1, len(SEASONS)).astype(int)
    # Role weight drives share of a team's minutes: a few starters, a long tail.
    role = np.clip(rng.lognormal(mean=np.log(1.0), sigma=0.6, size=N_PLAYERS), 0.15, 3.0)
    team_of = np.array([f"T{p % N_TEAMS:02d}" for p in range(N_PLAYERS)])

    rows: list[dict] = []
    for s_idx, season in enumerate(SEASONS):
        active = [
            p for p in range(N_PLAYERS)
            if debut_idx[p] <= s_idx < debut_idx[p] + career_len[p]
        ]
        if not active:
            continue

        gp_of = {p: int(np.clip(rng.normal(66, 14), 5, 82)) for p in active}

        # Allocate each team's 240 minutes/game across its active players so
        # that Σ(mpg × gp) = 240 × 82 holds, the way a real season does.
        mpg_of: dict[int, float] = {}
        for team in set(team_of[p] for p in active):
            squad = [p for p in active if team_of[p] == team]
            denom = sum(role[p] * gp_of[p] for p in squad)
            if denom <= 0:
                continue
            c = (TEAM_MINUTES_PER_GAME * GAMES_IN_SEASON) / denom
            for p in squad:
                mpg_of[p] = float(np.clip(c * role[p], 2.0, 40.0))

        for p in active:
            age = float(debut_age[p] + (s_idx - debut_idx[p]))
            age_mult = FALLBACK_AGE_CURVE.get(int(round(age)), 0.7)

            mpg = mpg_of.get(p, 0.0)
            gp = gp_of[p]
            minutes = mpg * gp
            if minutes <= 0:
                continue
            # Observation noise shrinks as minutes grow (~1/sqrt(minutes)).
            noise_scale = 6.0 / np.sqrt(max(minutes, 1.0))

            row = {
                "person_id": p,
                "normalized_name": f"player {p}",
                "display_name": f"Player {p}",
                "season": season,
                "age": age,
                "team": team_of[p],
                "gp": gp,
                "gs": gp,
                "minutes": minutes,
                "mpg": mpg,
                "usg_pct": None, "team_pace": None, "team_ortg": None,
            }
            for stat, tal in talent.items():
                true_rate = tal[p] * age_mult
                observed = true_rate * (1.0 + rng.normal(0, noise_scale))
                row[stat] = float(max(observed, 0.0) * mpg)  # per-game

            # Makes derive from attempts × shooting skill, so makes <= attempts
            # by construction. Percentages wobble a little year to year.
            for kind, att_col, made_col in (
                ("fg", "fga", "fgm"), ("ft", "fta", "ftm"), ("tp", "tpa", "tpm"),
            ):
                lo, hi = _PCT_TALENTS[kind][2], _PCT_TALENTS[kind][3]
                pct = float(np.clip(
                    pct_talent[kind][p] * (1.0 + rng.normal(0, noise_scale * 0.25)),
                    lo, hi,
                ))
                row[made_col] = row[att_col] * pct

            # Points follow from what actually went in: 2s, 3s and free throws.
            row["pts"] = (row["fgm"] - row["tpm"]) * 2 + row["tpm"] * 3 + row["ftm"]
            rows.append(row)

    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def world() -> pd.DataFrame:
    return _build_world()


def _naive_predictions(history: pd.DataFrame, target_season: int) -> pd.DataFrame:
    """The bar: repeat season N-1 unchanged (mirrors backtest.naive_baseline)."""
    prev = history[history["season"] == target_season - 1]
    cols = ["person_id", "pts", "reb", "ast", "stl", "blk", "tpm", "tov",
            "fgm", "fga", "ftm", "fta"]
    return prev[cols].copy()


def _mean_mae(result) -> float:
    vals = [v for v in result.mae.values() if v == v]  # drop NaN
    return float(np.mean(vals))


class TestBeatsNaiveOnSyntheticData:
    def test_model_beats_the_naive_baseline_on_mean_mae(self, world):
        """The merge gate, rehearsed: FCP must beat last-season-repeated."""
        history = world[world["season"] < TARGET]
        actuals = world[world["season"] == TARGET]

        fcp = evaluate(project_season(world, TARGET).projections, actuals, min_gp=20)
        naive = evaluate(_naive_predictions(world, TARGET), actuals, min_gp=20)

        fcp_mae, naive_mae = _mean_mae(fcp), _mean_mae(naive)
        assert fcp.players_evaluated > 100, "too few players to draw a conclusion"
        assert fcp_mae < naive_mae, (
            f"FCP ({fcp_mae:.4f}) did not beat naive ({naive_mae:.4f})"
        )

    def test_it_wins_on_most_individual_categories(self, world):
        """A win driven by one category would be a fluke, not a model."""
        actuals = world[world["season"] == TARGET]
        fcp = evaluate(project_season(world, TARGET).projections, actuals, min_gp=20)
        naive = evaluate(_naive_predictions(world, TARGET), actuals, min_gp=20)

        cats = [c for c in fcp.mae if c in naive.mae
                and fcp.mae[c] == fcp.mae[c] and naive.mae[c] == naive.mae[c]]
        wins = [c for c in cats if fcp.mae[c] < naive.mae[c]]
        assert len(wins) > len(cats) / 2, (
            f"only won {len(wins)}/{len(cats)} categories: "
            + ", ".join(f"{c} {fcp.mae[c]:.3f}v{naive.mae[c]:.3f}" for c in cats)
        )

    def test_the_advantage_is_not_seed_specific(self):
        """Re-roll the world several times: the model must win in
        expectation and on most draws.

        Deliberately NOT "wins on every seed". At ~280 evaluated players the
        per-draw margin is small enough that an occasional loss is sampling
        noise, and asserting an every-seed win would pin a claim that is
        false — the measured spread across seeds is roughly -0.4% to +12%.
        A single lucky seed proving a model is exactly the failure mode a
        backtest exists to catch, so the gate is the average plus a majority,
        not one run.
        """
        margins: list[float] = []
        for seed in (1, 2, 3, 4, 5):
            w = _build_world(seed=seed)
            actuals = w[w["season"] == TARGET]
            fcp = _mean_mae(evaluate(project_season(w, TARGET).projections, actuals, min_gp=20))
            naive = _mean_mae(evaluate(_naive_predictions(w, TARGET), actuals, min_gp=20))
            margins.append((naive - fcp) / naive)

        mean_margin = float(np.mean(margins))
        wins = sum(1 for m in margins if m > 0)
        assert mean_margin > 0.02, (
            f"mean improvement {mean_margin:.2%} across {len(margins)} worlds "
            f"is not a real edge: {[f'{m:+.2%}' for m in margins]}"
        )
        assert wins >= 4, (
            f"only won {wins}/{len(margins)} worlds: {[f'{m:+.2%}' for m in margins]}"
        )

    def test_projections_are_unbiased_in_aggregate(self, world):
        """The guard that would have caught all three shipped bugs at once.

        Every one of them was a silent systematic scaling error — the team
        budget over the historical pool (0.19x), the raw-MPG cap, and the
        age curve applied as a level rather than a change (0.96x). Per-player
        MAE cannot see a uniform scaling: it just degrades a little and the
        model looks merely mediocre instead of visibly broken.

        Comparing population means catches it immediately, and is the first
        thing to check whenever the real backtest loses.
        """
        actuals = world[world["season"] == TARGET]
        proj = project_season(world, TARGET).projections
        m = proj.merge(
            actuals[["person_id", "mpg", "gp", "pts", "reb", "ast"]],
            on="person_id", suffixes=("_p", "_a"),
        )
        m = m[m["gp"] >= 20]
        assert len(m) > 100

        mpg_ratio = m["projected_mpg"].mean() / m["mpg"].mean()
        assert 0.90 < mpg_ratio < 1.10, (
            f"minutes are systematically off: projected/actual = {mpg_ratio:.3f}"
        )

        for stat in ("pts", "reb", "ast"):
            ratio = m[f"{stat}_p"].mean() / m[f"{stat}_a"].mean()
            assert 0.90 < ratio < 1.10, (
                f"{stat} is systematically off: projected/actual = {ratio:.3f}"
            )
            # Isolate the per-minute term from the minutes term, so a failure
            # says which half is wrong (this is how bug 3 was found).
            rate_ratio = ratio / mpg_ratio
            assert 0.92 < rate_ratio < 1.08, (
                f"{stat} per-minute rate is off: {rate_ratio:.3f} "
                f"(stat ratio {ratio:.3f} / mpg ratio {mpg_ratio:.3f})"
            )

    def test_projections_are_physically_plausible(self, world):
        """Sanity: no negative production, no 60-minute players."""
        proj = project_season(world, TARGET).projections
        for stat in ("pts", "reb", "ast", "stl", "blk", "tpm", "tov"):
            assert (proj[stat] >= 0).all(), f"negative {stat}"
        assert (proj["projected_mpg"] <= 48.0).all()
        assert (proj["projected_gp"] <= 82.0).all()
        pct = proj["fg_pct"].dropna()
        assert ((pct >= 0) & (pct <= 1)).all(), "FG% outside [0,1]"
