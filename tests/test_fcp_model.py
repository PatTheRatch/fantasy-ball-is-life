"""FCP Projections M-3b — model tests (spec §7 test plan).

Hermetic: every fixture is synthetic, so these run in CI with no database,
no nba_api, and no backfill. The spec asks for golden-player unit tests
(aging vets decline, small samples regress, percentages derived from
makes/attempts), a team-coherence property test, and determinism.
"""

from __future__ import annotations

import pytest

pd = pytest.importorskip("pandas")

from backend.projections.fcp_model import (
    DEFAULT_SEASON_WEIGHTS,
    FALLBACK_AGE_CURVE,
    GAMES_IN_SEASON,
    TEAM_MINUTES_PER_GAME,
    PlayerAssumption,
    age_factor,
    fit_age_curve,
    project_minutes,
    project_season,
    shrink_rates,
    weighted_per_minute_rates,
)


def season_row(
    person_id: int,
    season: int,
    *,
    age: float = 26,
    gp: int = 70,
    mpg: float = 32.0,
    pts: float = 20.0,
    reb: float = 5.0,
    ast: float = 4.0,
    stl: float = 1.0,
    blk: float = 0.5,
    tpm: float = 2.0,
    tov: float = 2.0,
    fgm: float = 7.0,
    fga: float = 15.0,
    ftm: float = 4.0,
    fta: float = 5.0,
    tpa: float = 5.5,
    team: str = "BOS",
    name: str | None = None,
) -> dict:
    """One nba_player_seasons row. Stats are per-game; minutes is the total."""
    return {
        "person_id": person_id,
        "normalized_name": name or f"player {person_id}",
        "display_name": name or f"Player {person_id}",
        "season": season,
        "age": age,
        "team": team,
        "gp": gp,
        "gs": gp,
        "minutes": mpg * gp,
        "mpg": mpg,
        "pts": pts, "reb": reb, "ast": ast, "stl": stl, "blk": blk,
        "tpm": tpm, "tov": tov,
        "fgm": fgm, "fga": fga, "ftm": ftm, "fta": fta, "tpa": tpa,
        "usg_pct": None, "team_pace": None, "team_ortg": None,
    }


def frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Per-minute rates
# ---------------------------------------------------------------------------

class TestPerMinuteRates:
    def test_rate_is_production_over_minutes(self):
        """A player at 20 pts on 40 mpg projects 0.5 pts/min."""
        hist = frame([season_row(1, 2024, mpg=40.0, gp=82, pts=20.0)])
        rates = weighted_per_minute_rates(hist, weights=(1.0,))
        assert rates.loc[0, "rate_pts"] == pytest.approx(0.5, rel=1e-6)

    def test_recent_seasons_weigh_more(self):
        """Recency weighting pulls the estimate toward the latest season."""
        hist = frame([
            season_row(1, 2024, mpg=30.0, gp=80, pts=30.0),  # 1.0 pts/min
            season_row(1, 2023, mpg=30.0, gp=80, pts=15.0),  # 0.5 pts/min
        ])
        rate = weighted_per_minute_rates(hist, weights=(0.7, 0.3)).loc[0, "rate_pts"]
        # Equal minutes, so weights alone decide: .7(1.0) + .3(0.5) = 0.85
        assert rate == pytest.approx(0.85, rel=1e-6)
        assert rate > 0.75, "the recent season must dominate"

    def test_bigger_seasons_weigh_more_at_equal_recency(self):
        """Minutes are reliability: a 2000-minute season beats a 100-minute one."""
        hist = frame([
            season_row(1, 2024, mpg=5.0, gp=20, pts=10.0),    # tiny sample, hot
            season_row(1, 2023, mpg=35.0, gp=80, pts=17.5),   # big sample
        ])
        rate = weighted_per_minute_rates(hist, weights=(0.5, 0.5)).loc[0, "rate_pts"]
        # Equal recency weights, so minutes decide: the big season's 0.5/min
        # should dominate the small season's 2.0/min.
        assert rate < 1.0, f"small hot sample dominated the estimate ({rate})"

    def test_only_the_n_most_recent_seasons_count(self):
        """A 4th season is outside a 3-weight window and must not leak in."""
        rows = [season_row(1, s, pts=20.0) for s in (2024, 2023, 2022)]
        rows.append(season_row(1, 2021, pts=99.0))  # ancient outlier
        rate = weighted_per_minute_rates(frame(rows)).loc[0, "rate_pts"]
        expected = weighted_per_minute_rates(frame(rows[:3])).loc[0, "rate_pts"]
        assert rate == pytest.approx(expected, rel=1e-9)

    def test_zero_minute_season_is_ignored(self):
        """A season with no minutes says nothing about rates and must not divide by zero."""
        hist = frame([
            season_row(1, 2024, mpg=0.0, gp=0, pts=0.0),
            season_row(1, 2023, mpg=30.0, gp=70, pts=15.0),
        ])
        rates = weighted_per_minute_rates(hist)
        assert len(rates) == 1
        assert rates.loc[0, "rate_pts"] == pytest.approx(0.5, rel=1e-6)


# ---------------------------------------------------------------------------
# Small-sample regression
# ---------------------------------------------------------------------------

class TestShrinkage:
    def test_small_sample_regresses_toward_the_league(self):
        """The golden case: 90 minutes of scoring binge is not a 1.0/min player."""
        hist = frame(
            [season_row(1, 2024, mpg=4.5, gp=20, pts=4.5)]          # 1.0 pts/min
            + [season_row(i, 2024, mpg=32.0, gp=80, pts=16.0) for i in range(2, 12)]
        )
        raw = weighted_per_minute_rates(hist, weights=(1.0,))
        shrunk = shrink_rates(raw)

        cameo_raw = raw.set_index("person_id").loc[1, "rate_pts"]
        cameo_shrunk = shrunk.set_index("person_id").loc[1, "rate_pts"]
        assert cameo_raw == pytest.approx(1.0, rel=1e-6)
        assert cameo_shrunk < 0.75, "a 90-minute sample kept too much of its own signal"

    def test_large_sample_keeps_its_own_signal(self):
        """A 2,500-minute season is mostly itself after shrinkage."""
        hist = frame(
            [season_row(1, 2024, mpg=35.0, gp=75, pts=28.0)]        # 0.8 pts/min
            + [season_row(i, 2024, mpg=30.0, gp=75, pts=12.0) for i in range(2, 12)]
        )
        shrunk = shrink_rates(weighted_per_minute_rates(hist, weights=(1.0,)))
        star = shrunk.set_index("person_id").loc[1, "rate_pts"]
        assert star > 0.65, f"a full season was over-regressed ({star})"


# ---------------------------------------------------------------------------
# Age curve
# ---------------------------------------------------------------------------

class TestAgeCurve:
    def test_fallback_curve_declines_after_peak(self):
        assert FALLBACK_AGE_CURVE[35] < FALLBACK_AGE_CURVE[30] < FALLBACK_AGE_CURVE[26]

    def test_age_factor_clamps_outside_the_curve(self):
        assert age_factor(15, FALLBACK_AGE_CURVE) == FALLBACK_AGE_CURVE[19]
        assert age_factor(50, FALLBACK_AGE_CURVE) == FALLBACK_AGE_CURVE[40]

    def test_age_factor_handles_missing_age(self):
        assert age_factor(None, FALLBACK_AGE_CURVE) == 1.0
        assert age_factor(float("nan"), FALLBACK_AGE_CURVE) == 1.0

    def test_thin_history_falls_back_rather_than_fitting_noise(self):
        """Two players is not a league — don't pretend to fit a curve."""
        hist = frame([season_row(1, 2024), season_row(2, 2024)])
        assert fit_age_curve(hist) == FALLBACK_AGE_CURVE

    def test_fitted_curve_is_normalized_to_peak(self):
        rows = []
        for pid in range(1, 60):
            for season, age, pts in ((2022, 25, 20.0), (2023, 26, 19.0), (2024, 27, 18.0)):
                rows.append(season_row(pid, season, age=age, pts=pts, mpg=32.0, gp=75))
        curve = fit_age_curve(frame(rows), min_pairs_per_age=5)
        assert max(curve.values()) == pytest.approx(1.0, rel=1e-9)

    def test_aging_vet_declines(self):
        """Golden player: same rates, older age → lower projection."""
        young = frame([season_row(1, 2024, age=25, pts=20.0)])
        old = frame([season_row(1, 2024, age=36, pts=20.0)])
        curve = FALLBACK_AGE_CURVE

        y = project_season(young, 2025, age_curve=curve).projections
        o = project_season(old, 2025, age_curve=curve).projections
        assert o.loc[0, "pts"] < y.loc[0, "pts"]


# ---------------------------------------------------------------------------
# Team coherence — the property test the spec calls for
# ---------------------------------------------------------------------------

class TestTeamCoherence:
    def test_no_team_exceeds_the_minutes_budget(self):
        """'Not a rotation, a clown car': eight 40-MPG teammates get scaled."""
        rows = [season_row(i, 2024, mpg=40.0, team="LAL") for i in range(1, 9)]
        rates = weighted_per_minute_rates(frame(rows))
        mpg = project_minutes(rates)
        assert mpg.sum() <= TEAM_MINUTES_PER_GAME + 1e-6
        # Scaled proportionally, so equals stay equal.
        assert mpg.nunique() == 1

    def test_thin_roster_is_not_inflated(self):
        """Under budget is left alone — don't invent minutes nobody plays."""
        rows = [season_row(i, 2024, mpg=20.0, team="SAS") for i in range(1, 4)]
        mpg = project_minutes(weighted_per_minute_rates(frame(rows)))
        assert mpg.sum() == pytest.approx(60.0, rel=1e-6)

    def test_each_team_is_budgeted_independently(self):
        rows = [season_row(i, 2024, mpg=40.0, team="LAL") for i in range(1, 9)]
        rows += [season_row(i, 2024, mpg=15.0, team="SAS") for i in range(9, 12)]
        rates = weighted_per_minute_rates(frame(rows))
        mpg = project_minutes(rates)
        by_team = mpg.groupby(rates["team"]).sum()
        assert by_team["LAL"] <= TEAM_MINUTES_PER_GAME + 1e-6
        assert by_team["SAS"] == pytest.approx(45.0, rel=1e-6)

    def test_projection_respects_the_cap_end_to_end(self):
        rows = [season_row(i, 2024, mpg=40.0, team="LAL") for i in range(1, 9)]
        run = project_season(frame(rows), 2025)
        assert run.projections["projected_mpg"].sum() <= TEAM_MINUTES_PER_GAME + 1e-6


# ---------------------------------------------------------------------------
# Games played, kept separate from per-game ability
# ---------------------------------------------------------------------------

class TestGamesPlayed:
    def test_injury_history_does_not_lower_per_game_rates(self):
        """The spec is explicit: availability must not contaminate ability."""
        healthy = frame([season_row(1, 2024, gp=82, mpg=30.0, pts=15.0)])
        injured = frame([season_row(1, 2024, gp=30, mpg=30.0, pts=15.0)])

        h = project_season(healthy, 2025).projections
        i = project_season(injured, 2025).projections

        assert h.loc[0, "pts"] == pytest.approx(i.loc[0, "pts"], rel=1e-6)
        assert i.loc[0, "projected_gp"] < h.loc[0, "projected_gp"]

    def test_games_never_exceed_the_season(self):
        rows = [season_row(i, 2024, gp=82) for i in range(1, 6)]
        run = project_season(frame(rows), 2025)
        assert (run.projections["projected_gp"] <= GAMES_IN_SEASON).all()

    def test_assumption_overrides_projected_games(self):
        hist = frame([season_row(1, 2024, gp=82)])
        run = project_season(
            hist, 2025, assumptions=[PlayerAssumption(person_id=1, projected_games=41)]
        )
        assert run.projections.loc[0, "projected_gp"] == pytest.approx(41.0)


# ---------------------------------------------------------------------------
# Percentages derived from makes/attempts
# ---------------------------------------------------------------------------

class TestPercentages:
    def test_fg_pct_derived_from_projected_makes_and_attempts(self):
        hist = frame([season_row(1, 2024, fgm=8.0, fga=16.0, mpg=32.0, gp=80)])
        proj = project_season(hist, 2025).projections
        expected = proj.loc[0, "fgm"] / proj.loc[0, "fga"]
        assert proj.loc[0, "fg_pct"] == pytest.approx(expected, rel=1e-9)

    def test_volume_shooter_outweighs_a_cameo_in_the_league_prior(self):
        """48.7% on 1,100 FGA is not the same fact as 48.7% on 90."""
        hist = frame([
            season_row(1, 2024, mpg=35.0, gp=80, fgm=10.0, fga=20.0),
            season_row(2, 2024, mpg=3.0, gp=15, fgm=1.0, fga=2.0),
        ])
        proj = project_season(hist, 2025).projections.set_index("person_id")
        # The cameo is regressed hard toward the league, which is dominated
        # by the volume shooter's minutes.
        assert proj.loc[2, "fga"] < proj.loc[1, "fga"]

    def test_zero_attempts_yields_nan_not_infinity(self):
        hist = frame([season_row(1, 2024, ftm=0.0, fta=0.0)])
        proj = project_season(hist, 2025).projections
        assert pd.isna(proj.loc[0, "ft_pct"])


# ---------------------------------------------------------------------------
# Contract with the backtest harness, and leakage
# ---------------------------------------------------------------------------

class TestBacktestContract:
    def test_target_season_is_never_used_to_predict_itself(self):
        """Leaking the target into its own prediction would silently
        invalidate every backtest, so the model filters, not the caller."""
        hist = frame([
            season_row(1, 2024, pts=10.0),
            season_row(1, 2025, pts=99.0),   # the season being predicted
        ])
        proj = project_season(hist, 2025).projections
        # 10 pts on 32 mpg over 70 games, projected back onto ~32 mpg.
        assert proj.loc[0, "pts"] < 20.0, "the target season leaked into the prediction"

    def test_output_matches_evaluate_s_expected_columns(self):
        from backend.projections.backtest import _CAT_MAP

        rows = [season_row(i, 2024) for i in range(1, 6)]
        proj = project_season(frame(rows), 2025).projections
        for col in ["person_id", "fgm", "fga", "ftm", "fta"] + list(_CAT_MAP.values()):
            assert col in proj.columns, f"missing column required by evaluate(): {col}"

    def test_scores_against_the_harness_without_error(self):
        from backend.projections.backtest import evaluate

        hist = frame([season_row(i, 2024, pts=10.0 + i) for i in range(1, 15)])
        actuals = frame([season_row(i, 2025, pts=11.0 + i) for i in range(1, 15)])

        run = project_season(hist, 2025)
        result = evaluate(run.projections, actuals, min_gp=20)
        assert result.players_evaluated > 0
        assert "pts" in result.mae

    def test_players_with_no_history_are_absent_not_zeroed(self):
        """Rookies are M-5's job — a zero row would poison the MAE."""
        hist = frame([season_row(1, 2024)])
        proj = project_season(hist, 2025).projections
        assert 2 not in set(proj["person_id"])


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:
    def test_identical_inputs_give_identical_output(self):
        rows = [season_row(i, s) for i in range(1, 12) for s in (2023, 2024)]
        a = project_season(frame(rows), 2025).projections
        b = project_season(frame(rows), 2025).projections
        pd.testing.assert_frame_equal(a, b)

    def test_row_order_does_not_change_the_result(self):
        rows = [season_row(i, s) for i in range(1, 12) for s in (2023, 2024)]
        a = project_season(frame(rows), 2025).projections
        b = project_season(frame(rows[::-1]), 2025).projections
        pd.testing.assert_frame_equal(
            a.sort_values("person_id").reset_index(drop=True),
            b.sort_values("person_id").reset_index(drop=True),
        )


# ---------------------------------------------------------------------------
# Empty / degenerate inputs
# ---------------------------------------------------------------------------

class TestDegenerateInputs:
    def test_empty_history_returns_an_empty_run(self):
        run = project_season(pd.DataFrame(), 2025)
        assert run.projections.empty

    def test_history_entirely_after_the_target_returns_empty(self):
        hist = frame([season_row(1, 2026)])
        run = project_season(hist, 2025)
        assert run.projections.empty
        assert run.players_skipped_no_history == 1

    def test_default_weights_are_the_documented_ones(self):
        assert DEFAULT_SEASON_WEIGHTS == (0.55, 0.30, 0.15)
