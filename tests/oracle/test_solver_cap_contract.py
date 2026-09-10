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
============================  ==========================================  ==========
solver (status, value)        V1 behaviour                                branch
============================  ==========================================  ==========
(`user_limit`, None)          ValueError naming the 8s limit; says the    2
                              result "doesn't necessarily mean it's
                              infeasible"
(`infeasible`, None)          ValueError, message includes                3
                              `status=infeasible`
(`unbounded`/other, None)     same shape as infeasible, includes the      3
                              actual status
(`user_limit`, real           accepted; count verified against            1
incumbent of wrong length)    `roster_size - len(current_roster)`
(`user_limit`, all-zero       the count check fires → ValueError          1
degenerate)                   naming both counts
============================  ==========================================  ==========

Branches 2 and 3 are captured as executable assertions below. Branch 1 is
**documented, not asserted** — see the trap note.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Deselected from the default run: these import V1 and therefore cvxpy/pandas.
pytestmark = pytest.mark.capture


# V1 is imported lazily so that collection of this module by the default pytest
# run does not explode when cvxpy is absent. The marker in pyproject.toml is the
# primary guard; this is belt-and-braces.
V1_ROOT = Path(__file__).with_name("v1_root")


# --- The trap, recorded because it cost real time ---------------------------
#
# Branch 1 (a `user_limit` incumbent whose length is wrong) CANNOT be reached by
# faking `prob.status` alone. `player_vars.value` is written by the real solver
# during `prob.solve`; if the call is stubbed out, the variable is never
# populated, so `player_vars.value is None` and V1 takes branch 2 instead.
#
# Reaching branch 1 honestly requires a real incumbent of the wrong length, i.e.
# an actual capped solve — which is the wall-clock-nondeterministic thing we are
# trying to avoid. So it is recorded as documented behaviour with its exact
# message and the code path that produces it, and NOT asserted. D-12 should
# implement the count check; it should not build a test that pretends to prove
# V1 does it under a stub, because that test would pass for the wrong reason.
#
# Source: optimizer.py ~556-579, in the `user_limit` handling block.


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
    """Force a solver status and return V1's error message.

    Patches the *method* on the real `cp.Problem` class, so the objective and
    constraints are built for real and only the solve result is injected.
    """
    real_problem = optimizer_module.cp.Problem
    original_solve = real_problem.solve

    def forced_solve(self, **kwargs):  # noqa: ANN001 - mirrors cvxpy's signature
        self._status = status
        return None

    try:
        with patch.object(real_problem, "solve", forced_solve):
            opt.optimize_roster("PTS")
    except ValueError as exc:
        return str(exc)
    finally:
        real_problem.solve = original_solve
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
