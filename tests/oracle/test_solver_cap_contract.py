"""D-09 · The solver-cap contract, as recorded from V1.

**Not part of the default test run** — same rationale as ``capture_goldens.py``:
importing V1 pulls in `cvxpy`/`pandas`/`numpy`, none of which V2 depends on.

Why this file exists separately from the numeric goldens
-------------------------------------------------------
The timeout path **cannot** be captured as a numeric golden, and that is not a
limitation of the tooling — it is a property of the thing being captured.

Which incumbent HiGHS holds when it trips an 8-second wall clock depends on CPU
speed, solver version, and BLAS build. A golden saying "at timeout, this roster
comes back" would differ between a dev laptop, CI, and Patrick's machine. Two
tempting workarounds both fail:

* **Build a genuinely hard problem** so the cap is reached. Doubly
  nondeterministic: *whether* it caps AND *what* it returns both vary by machine.
* **Monkeypatch the cap to ~1ms.** Changes the constant under test, so the golden
  describes a system nobody runs — and the returned incumbent is *still*
  wall-clock-nondeterministic. Unfaithful and unstable.

So the cap is characterized as **branch behaviour**, not as numbers. Which branch
V1 takes, for a given `(status, value)` from the solver, is pure decision logic —
deterministic, machine-independent, and exactly what a correct-vs-wrong V2 port
differs on.

The seam
--------
``prob`` is a local inside ``optimize_roster``, so there is no attribute to patch
on the instance. But ``cp.Problem`` is resolved through the module's ``cp``
namespace, so patching the *method* on the real problem class intercepts cleanly
— no cvxpy internals are mocked. Verified working.

The three recorded outcomes
---------------------------
Numbering follows SOURCE ORDER in `optimize_roster`, so it can be checked
against the code without a mapping table. (An earlier version numbered these the
other way round, which contradicted both the source and the PR narrative — the
kind of mismatch that confuses whoever ports this next.)

==============================  ========================================  ======
solver (status, value)          V1 behaviour                              branch
==============================  ========================================  ======
(`user_limit`, None)            ValueError naming the 8s limit; says it   B1
                                "doesn't necessarily mean it's
                                infeasible"
(any non-accepted status, None) ValueError including `status=<status>`    B2
                                — covers `infeasible`, `unbounded`, ...
(`user_limit`, incumbent whose  the count check fires → ValueError       B3
length != needed)               naming both counts
(`user_limit`, correctly-sized  ACCEPTED, roster returned                B4
incumbent)
==============================  ========================================  ======

All four are now executable assertions below. B3 was originally documented but
not asserted, on a false belief that it was unreachable — see the note above for
why that was wrong.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

# Deselected from the default run: these import V1 and therefore cvxpy/pandas.
pytestmark = pytest.mark.capture


# V1 is imported lazily so that collection of this module by the default pytest
# run does not explode when cvxpy is absent. The marker in pyproject.toml is the
# primary guard; this is belt-and-braces.


# --- Reaching the count-check branch, and a wrong first conclusion -------------
#
# An earlier version of this file claimed the count-check branch (a `user_limit`
# incumbent whose length is wrong) could NOT be tested without a real capped
# solve, and therefore documented it instead of asserting it. **That was wrong**,
# and the review caught it. The reasoning was: `player_vars.value` is written by
# the real solver, so faking the status leaves it None and V1 takes the
# "no incumbent" branch instead.
#
# That is only true if you fake the status ALONE. The `self` inside a patched
# `Problem.solve` is the **real** problem object, which holds its variables via
# `self.variables()`. Assigning `.value` on those injects a genuine incumbent, so
# the "value is None" branch is skipped, `user_limit` is in the accepted set (so
# the generic error is skipped), and the count check runs — deterministically,
# with no wall-clock involvement, because no real solve happens.
#
# The generalizable lesson, since it cost a review round: "I tried one way and it
# didn't work" is not "it cannot be done". The first attempt failed because it was
# a bad seam, not because no seam existed.
#
# Source: optimizer.py ~556-579, in the `user_limit` handling block.


def _force_solve_with_incumbent(
    optimizer_module, incumbents: list[float] | None, status: str = "user_limit"
):
    """Patch ``cp.Problem.solve`` to inject a controlled solver result.

    ``incumbents=None`` reproduces "solver returned no values" (the variable's
    ``.value`` is never assigned). A list assigns it index-by-index, so a caller
    can construct a correct-length selection, a short one, or the all-zero
    degenerate case the source comment warns about.
    """
    real_problem = optimizer_module.cp.Problem
    original_solve = real_problem.solve

    def forced_solve(self, **kwargs):  # noqa: ANN001 - mirrors cvxpy's signature
        if incumbents is not None:
            for variable in self.variables():
                vector = np.zeros(variable.shape)
                vector[: len(incumbents)] = incumbents
                variable.value = vector
        self._status = status
        return None

    return patch.object(real_problem, "solve", forced_solve), original_solve


def _import_v1(v1_root: Path):
    """Import V1's ``backend`` package, displacing V2's if already loaded.

    V1 and V2 both ship a top-level ``backend`` package. Under pytest, V2's repo
    root is already on ``sys.path`` and ``backend`` may already be bound to V2's
    tree, which has no ``backend/draft`` at all — so a plain ``sys.path.insert``
    is not enough and the import fails with a confusing ModuleNotFoundError.

    Evicting the cached ``backend*`` modules and prepending the V1 root is what
    makes the import deterministic. Safe here because these tests are
    deselected from the default run: no V2 code is live in the same process.
    """
    for name in [m for m in sys.modules if m == "backend" or m.startswith("backend.")]:
        del sys.modules[name]
    if str(v1_root) in sys.path:
        sys.path.remove(str(v1_root))
    sys.path.insert(0, str(v1_root))

    import backend

    if Path(backend.__file__).resolve().parent.parent != v1_root.resolve():
        raise AssertionError(
            f"imported backend from {backend.__file__}, expected the V1 tree at {v1_root}"
        )


def _build_v1_optimizer(v1_root: Path):
    """Construct a V1 OptimizeLineup against the fixture, offline.

    V1 is imported directly rather than run as a pytest rootdir: pytest would
    collect V1's own ``tests/conftest.py``, which imports
    ``backend.league.credentials`` at module scope and fails when the V1 tree is
    not the active rootdir.

    Two stubs are required and neither is optional: a LeagueContext on the
    ContextVar, and `get_cached_my_league` (four live ESPN requests otherwise).
    """
    _import_v1(v1_root)

    import backend.draft.optimizer as optimizer
    import pandas as pd
    from backend.league.credentials import _LEAGUE_CTX, LeagueContext

    from tests.fixtures.projections import v1_adapter

    # V1's `tests` package is not necessarily importable as `tests.*`; load the
    # adapter from the local V2 copy, which is the same file the fixture uses.
    if not hasattr(v1_adapter, "to_v1_columns"):  # pragma: no cover - defensive
        raise AssertionError("v1_adapter missing to_v1_columns; wrong module imported")

    _LEAGUE_CTX.set(
        LeagueContext(
            league_id="d09-cap",
            slug="d09-cap",
            name="D-09 Cap League",
            espn_league_id=123456,
            espn_season=2026,
            swid="d09",
            espn_s2="d09",
            timezone="America/New_York",
        )
    )

    class _StubLeague:
        draft: list = []
        teams: list = []

    with patch.object(optimizer, "get_cached_my_league", return_value=_StubLeague()):
        frame = pd.DataFrame(v1_adapter.to_v1_columns(v1_adapter.load_canonical()))
        opt = optimizer.OptimizeLineup(
            projections_df=frame, minimum_game_threshold=20, value_col="$"
        )
    return opt, optimizer


def _solve_with_status(optimizer_module, opt, status: str) -> str:
    """Force a solver status (no incumbent) and return V1's error message.

    Patches the *method* on the real `cp.Problem` class, so the objective and
    constraints are built for real and only the solve result is injected. The
    variable is never assigned, which is what a real capped solve looks like when
    it found nothing.
    """
    patcher, original_solve = _force_solve_with_incumbent(optimizer_module, None, status)
    try:
        with patcher:
            opt.optimize_roster("PTS")
    except ValueError as exc:
        return str(exc)
    finally:
        optimizer_module.cp.Problem.solve = original_solve
    raise AssertionError(f"expected a ValueError for status={status!r}, got none")


def test_user_limit_without_incumbent_names_the_time_limit(v1_root: Path) -> None:
    """Branch 2: `user_limit` + no incumbent is its own distinct error.

    The message must say the result does not imply infeasibility — that
    distinction is the entire reason §6.3 flagged this path. A V2 port that
    collapsed it into the generic infeasible error would lose actionable
    information for the user.
    """
    opt, optimizer = _build_v1_optimizer(v1_root)
    message = _solve_with_status(optimizer, opt, "user_limit")

    assert "time limit" in message
    assert "doesn't necessarily mean it's infeasible" in message
    # And it must NOT be the generic infeasible wording.
    assert "No feasible roster found" not in message


def test_infeasible_reports_the_status_verbatim(v1_root: Path) -> None:
    """Branch 3: infeasible names `status=infeasible` in the message.

    Captured because the two errors are easy to mistake for each other: both are
    ValueError, both mention the pool size and budget. The tell is that branch 3
    interpolates the raw status, which is what lets a user distinguish "your
    constraints conflict" from "the solver ran out of time".
    """
    opt, optimizer = _build_v1_optimizer(v1_root)
    message = _solve_with_status(optimizer, opt, "infeasible")

    assert "No feasible roster found" in message
    assert "status=infeasible" in message
    assert "time limit" not in message


def test_unknown_status_is_not_silently_accepted(v1_root: Path) -> None:
    """Branch 3 generalises: any non-accepted status raises rather than
    returning a partial roster.

    `optimal`, `optimal_inaccurate` and `user_limit` are the accepted set. An
    unrecognised status must not fall through to a "best effort" roster — that
    would hand a user a lineup the solver never validated.
    """
    opt, optimizer = _build_v1_optimizer(v1_root)
    message = _solve_with_status(optimizer, opt, "unbounded")

    assert "No feasible roster found" in message
    assert "status=unbounded" in message


def test_user_limit_with_degenerate_incumbent_triggers_count_check(v1_root: Path) -> None:
    """The count check: a `user_limit` incumbent of the wrong length is REJECTED.

    This is the most dangerous branch and it was originally left untested on a
    false belief that it was unreachable. It is reachable: injecting a value on
    the real problem's variables produces a genuine incumbent, so V1 skips the
    "no incumbent" branch and runs the count check.

    Why it matters more than the other two: this is the branch that stops a
    degenerate all-zero selection from being handed to a user as a lineup. V1's
    own comment names the case —

        "HiGHS can return a degenerate all-zero selection when it hits the time
         limit before finding a single complete roster. Verify the count before
         trusting it; a size mismatch here means 'ran out of time', not a usable
         (if suboptimal) roster."

    A D-12 port that trusted a `user_limit` incumbent without verifying length
    would silently return a 0- or 5-player roster — and nothing else in this
    oracle suite would catch it.
    """
    opt, optimizer = _build_v1_optimizer(v1_root)
    patcher, original_solve = _force_solve_with_incumbent(optimizer, [])  # all zeros
    try:
        with patcher:
            opt.optimize_roster("PTS")
    except ValueError as exc:
        message = str(exc)
    else:
        pytest.fail("V1 accepted a degenerate all-zero incumbent")
    finally:
        optimizer.cp.Problem.solve = original_solve

    # Names both counts, so the user can see how short the incumbent was.
    assert "without completing a valid" in message
    assert "got 0" in message
    assert "status=user_limit" in message
    assert "13-player" in message, "the required roster size should be named"


def test_user_limit_with_short_incumbent_names_both_counts(v1_root: Path) -> None:
    """A non-degenerate but short incumbent (5 of 13) is rejected the same way.

    Distinct from the all-zero case: this proves the check compares *counts*
    rather than special-casing the all-zero pattern. An implementation that only
    detected "everything is zero" would pass the previous test and fail this one.
    """
    opt, optimizer = _build_v1_optimizer(v1_root)
    patcher, original_solve = _force_solve_with_incumbent(optimizer, [1.0] * 5)
    try:
        with patcher:
            opt.optimize_roster("PTS")
    except ValueError as exc:
        message = str(exc)
    else:
        pytest.fail("V1 accepted a 5-of-13 incumbent")
    finally:
        optimizer.cp.Problem.solve = original_solve

    assert "got 5" in message
    assert "13-player" in message


def test_user_limit_with_correct_length_incumbent_is_accepted(v1_root: Path) -> None:
    """The positive case: a correctly-sized `user_limit` incumbent IS returned.

    Without this, the suite would only prove V1 rejects things. The contract is
    that `user_limit` is accepted like `optimal_inaccurate` — the solver ran out
    of time but produced a usable roster — and that has to be demonstrated too,
    or D-12 could implement rejection-of-everything and pass.

    The returned cost here is NOT bound by the budget check the happy path gets,
    which is exactly why the count check matters: a `user_limit` roster is
    trusted on length alone.

    (Observed: 13 players, cost 207.0. The over-budget cost is a property of this
    synthetic incumbent, not of V1 — it reflects that a stubbed incumbent is not
    constrained by the LP.)
    """
    opt, optimizer = _build_v1_optimizer(v1_root)
    patcher, original_solve = _force_solve_with_incumbent(optimizer, [1.0] * 13)
    try:
        with patcher:
            roster = opt.optimize_roster("PTS")
    finally:
        optimizer.cp.Problem.solve = original_solve

    assert len(roster) == 13, "a correctly-sized incumbent should be returned"
