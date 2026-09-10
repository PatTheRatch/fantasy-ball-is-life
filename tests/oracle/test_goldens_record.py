"""D-09 · V1 characterization goldens — the oracle D-12 must reproduce.

**This suite does NOT import V1.** It reads a committed record of V1's observed
behaviour and asserts the record is coherent with itself and with the fixture it
describes. That is deliberate, and it is the whole point of the design.

Why a recorded oracle rather than a live one
--------------------------------------------
Charter §6.2 says: *"Run the current optimizer against the fixture, record
outputs, assert V2 reproduces them."* Read literally, that is a golden-master /
characterization test: V1 is the oracle you **consult once**, not a service on
retainer. The unit of migration is the idea (§9), not the file.

So this suite is fast, hermetic, and needs no `cvxpy`, no `pandas`, and no V1
import — none of which V2 depends on. V1 stays a point-in-time authority.

The provenance of the numbers is `tests/oracle/capture_goldens.py`, which **is**
committed, behind an opt-in dependency extra and deselected from the default run.
That file is what makes these numbers evidence rather than unfalsifiable magic:
anyone can re-derive them. Committing only the JSON would recreate the failure
D-09's own review named — a claim proven in prose, with numbers instead of words.

What is asserted here, and what is not
--------------------------------------
Asserted (properties of the record):
  * every category V1 could solve is recorded, and the two it could not are
    recorded as failing *with their error type* — a limitation, not an omission
  * the constants the goldens are only valid under are pinned as data, so a
    reviewer can check nobody silently changed a default
  * every recorded roster is a legal fantasy roster at the fixture's pool size
  * the objective is recorded from the category's `PW` column, and the size of
    the recorded objectives is consistent across runs

NOT asserted: that V2 matches. V2 does not exist yet. D-12 asserts that, against
this record, with the tolerance policy below.

Known limit of this suite, named rather than implied away
---------------------------------------------------------
This suite pins **structure and coverage** of the record, not the *magnitude* of
most objectives. A hand-edit of AST's objective from 180.25 to 175.0 passes every
test here — it stays finite, numeric and positive, and the cost is untouched.
Only PTS and REB have a magnitude floor (``> budget``), and that is a weak floor
rather than an equality.

Why not pin them exactly: recomputing ``sum(frame[f'{cat} PW'])`` over each
roster would mean reimplementing V1's per-week weighting here, i.e. duplicating
the very logic the oracle exists to check independently. That is a worse trade
than the residual risk, and it would also drag pandas into the default suite.

So the magnitudes are trustworthy because they were *captured* (by
``capture_goldens.py``, which is committed and re-runnable) rather than because
this suite verifies them. If you need to confirm an objective, re-run the
harness; do not treat a green run here as confirmation of the numbers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

GOLDENS_PATH = Path(__file__).with_name("d09_goldens.json")

# The constants the goldens are valid under. Pinned HERE as well as in the JSON so
# that editing the JSON to match a drifted V1 default still trips a test.
EXPECTED_CONSTANTS: dict[str, Any] = {
    "roster_size": 13,
    "initial_budget": 200,
    "minimum_value_players": 3,
    "minimum_game_threshold": 20,
    "value_col": "$",
    "solver_time_limit_seconds": 8,
}

# Categories V1 can actually maximize. FG%/FT% are NOT here — see below.
SOLVABLE_CATEGORIES = {"PTS", "REB", "AST", "STL", "BLK", "3PM", "TO"}

# Percentage categories raise KeyError on the missing `{cat} PW` column.
#
# This is a real V1 limitation, discovered by running the solver, not a gap in
# the capture. V1's `set_requirements` can *constrain* percentages, but
# `optimize_roster` can only *maximize* categories that have a per-week weighted
# column, and the frame carries `fgm/g PW` / `fga/g PW` / `ftm/g PW` /
# `fta/g PW` instead of `FG% PW` / `FT% PW`. V1's own tests, CLI, and API never
# pass a percentage to `optimize_roster` — the limitation was simply never hit.
#
# Recorded so D-12 reproduces the asymmetry rather than inventing percentage
# support V1 never had, and so the omission is visible instead of silent.
# UNDECIDED: bug vs by-design. This records the SHAPE of V1's behaviour, which is
# all a characterization pass should do. Whether "percentages cannot be maximized"
# is correct behaviour that V2 must faithfully reproduce, or a V1 gap that V2
# should leave behind, is a charter/D-12 decision — NOT something this record
# settles. An earlier draft of these docstrings said "D-12 must reproduce the
# asymmetry", which over-committed: it pre-decided a port obligation from a
# characterization artifact. D-12's scope should answer bug-vs-by-design first.
UNSOLVABLE_CATEGORIES = {"FG%": "KeyError", "FT%": "KeyError"}

# Tolerance policy for D-12. Floats are rounded at capture (3dp objective, 2dp
# cost) because cross-version numpy/HiGHS can wobble trailing digits; an exact
# float golden would flake on the first solver bump. D-12 should assert
# math.isclose(rel=1e-6) on the objective and exact equality on roster
# membership.
OBJECTIVE_TOLERANCE_REL = 1e-6


@pytest.fixture(scope="module")
def goldens() -> dict[str, Any]:
    return json.loads(GOLDENS_PATH.read_text())


@pytest.fixture(scope="module")
def categories(goldens: dict[str, Any]) -> dict[str, Any]:
    return goldens["categories"]


def test_goldens_file_is_committed() -> None:
    """The record must be in git. This is the same assertion D-08 needed and
    failed: a fixture that lives only on the machine that generated it is not a
    committed fixture, and CI has no other copy."""
    assert GOLDENS_PATH.exists(), f"{GOLDENS_PATH} is not committed"


def test_capture_constants_are_pinned(goldens: dict[str, Any]) -> None:
    """Every constant the goldens depend on is recorded as data.

    A reviewer must be able to check that V2 did not silently drift a default —
    `roster_size` 13 vs 12 changes every roster, and nothing else in the record
    would reveal it.
    """
    assert goldens["constants"] == EXPECTED_CONSTANTS


def test_capture_records_its_version_manifest(goldens: dict[str, Any]) -> None:
    """A golden mismatch in D-12 must be triageable as version drift vs port bug.

    Without the solver/numpy versions recorded, every future mismatch is an
    uninterpretable mystery and the goldens get deleted out of frustration.
    """
    versions = goldens["versions"]
    assert versions.get("cvxpy"), "cvxpy version not recorded"
    assert versions.get("python"), "python version not recorded"


def test_every_solvable_category_is_recorded(categories: dict[str, Any]) -> None:
    """A missing category silently under-specifies the port.

    Different categories bind different constraints (TO is minimized, so its
    objective is negative), so a subset would let D-12 pass on the easy ones
    while being wrong on the rest.
    """
    assert set(categories) == SOLVABLE_CATEGORIES | set(UNSOLVABLE_CATEGORIES)


def test_every_recorded_roster_is_legal(categories: dict[str, Any]) -> None:
    """Each solved roster must be a full, duplicate-free roster.

    V1 returns 13 rows for a 13-man league. A truncated or duplicated roster
    would be a capture bug that D-12 would then faithfully reproduce — the worst
    outcome, since it would look like agreement.
    """
    for category in sorted(SOLVABLE_CATEGORIES):
        entry = categories[category]
        assert entry["solvable"] is True, f"{category} unexpectedly unsolvable"
        roster = entry["roster"]
        assert len(roster) == EXPECTED_CONSTANTS["roster_size"], (
            f"{category}: roster has {len(roster)} players, "
            f"expected {EXPECTED_CONSTANTS['roster_size']}"
        )
        assert len(set(roster)) == len(roster), f"{category}: duplicate player in roster"


def test_objective_is_recorded_and_finite(categories: dict[str, Any]) -> None:
    """Objectives come from the category's `PW` column and must be present.

    This caught a real bug in the harness: capturing `Value` instead of
    `{category} PW` yields `200.0` for every category (it is the bid-value
    column, summing to the budget) and looks entirely plausible. `TO` is
    negative because turnovers are minimized — a sign check that the right
    column is being read.
    """
    for category in sorted(SOLVABLE_CATEGORIES):
        objective = categories[category]["objective"]
        assert objective is not None, f"{category}: objective missing"
        assert isinstance(objective, (int, float)), f"{category}: objective not numeric"
    # Turnovers are minimized, so their objective is negative. If a future edit
    # flips this, the capture is reading the wrong column.
    assert categories["TO"]["objective"] < 0, "TO objective should be negative"


def test_objectives_are_not_the_budget(categories: dict[str, Any]) -> None:
    """A regression guard for the exact bug the harness had.

    Capturing the wrong column produced `objective == 200.0` for every category —
    the budget, not the stat total. Several categories legitimately *do* cost the
    full $200, so cost cannot detect this; the objective must be checked directly.

    Only categories whose objective is *verified* above the budget are listed.
    An earlier version of this test included 3PM, whose objective is legitimately
    102.48 — three-point makes are a small number, so it does not clear 200 and
    the assertion was simply wrong. Listing a category here is a claim about its
    magnitude; do not add one without checking the recorded value first.
    """
    for category in ("PTS", "REB"):
        objective = categories[category]["objective"]
        assert objective > EXPECTED_CONSTANTS["initial_budget"], (
            f"{category}: objective {objective} is not above the budget — the harness "
            "is probably reading the `Value` column instead of `{category} PW`"
        )


def test_cost_never_exceeds_budget(categories: dict[str, Any]) -> None:
    """The solver's headline guarantee. A recorded cost over budget would mean
    the capture recorded something other than a legal V1 solve."""
    for category in sorted(SOLVABLE_CATEGORIES):
        cost = categories[category]["cost"]
        assert cost is not None, f"{category}: cost missing"
        assert cost <= EXPECTED_CONSTANTS["initial_budget"] + 1e-6, (
            f"{category}: cost {cost} exceeds the ${EXPECTED_CONSTANTS['initial_budget']} budget"
        )


@pytest.mark.parametrize("category", sorted(UNSOLVABLE_CATEGORIES))
def test_percentage_categories_are_recorded_as_unsolvable(
    categories: dict[str, Any], category: str
) -> None:
    """FG% and FT% must be recorded as *failing*, with their error type.

    This is the honest-recording test. A capture that skipped percentages, or
    that reported them as solvable, would hide a real V1 limitation and invite
    D-12 to "fix" behaviour V2 should be reproducing faithfully.
    """
    entry = categories[category]
    assert entry["solvable"] is False, f"{category} unexpectedly solvable"
    assert entry["error_type"] == UNSOLVABLE_CATEGORIES[category]
    assert "PW" in entry["error"], "the missing-column error should name the column"


def test_rosters_are_made_of_fixture_players(
    categories: dict[str, Any],
) -> None:
    """Every selected player must exist in the D-08 fixture.

    Ties the record to the artifact it describes. If the fixture is regenerated
    with a different seed, the goldens become describable-by-nothing and must be
    recaptured — this catches that instead of leaving two incompatible artifacts
    committed side by side.
    """
    from tests.fixtures.projections import v1_adapter

    known = {v1_adapter.v1_name(row.key) for row in v1_adapter.load_canonical()}
    for category in sorted(SOLVABLE_CATEGORIES):
        unknown = set(categories[category]["roster"]) - known
        assert not unknown, (
            f"{category}: roster names {sorted(unknown)[:3]} are not in the fixture — "
            "the fixture was likely regenerated and the goldens need recapturing"
        )


def test_oracle_modules_are_dependency_light() -> None:
    """The oracle suite must import cleanly without V1's heavy dependencies.

    **This is a regression guard for a real CI failure.** A module-scope
    ``import numpy`` in the capture module broke the *default* test run with::

        ModuleNotFoundError: No module named 'numpy'
        !!! Interrupted: 1 error during collection !!!

    because pytest **imports a module to collect it**, and the ``capture`` marker
    deselects at *test* level, not module level. An import that exists only to
    support deselected tests still has to be lazy — or the deselecting environment
    (CI, which installs none of these) cannot even collect the file.

    The failure surfaced as a bare ``ModuleNotFoundError`` from a test file nobody
    intended to run. This test converts that from an implicit CI accident into an
    explicit assertion with a clear message and a named fix.

    Checked by reading the source rather than importing, so this test cannot
    itself be the thing that fails to import.
    """
    banned = {"numpy", "pandas", "cvxpy", "scipy", "highspy", "openpyxl", "pulp"}
    offenders: list[str] = []

    for path in sorted(Path(__file__).parent.glob("*.py")):
        if path.name == "capture_goldens.py":
            continue  # the harness is meant to import V1; it is never collected
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            # Only top-level imports count. Indented ones are lazy by definition.
            if line != stripped or not stripped.startswith(("import ", "from ")):
                continue
            root = stripped.split()[1].split(".")[0]
            if root in banned:
                offenders.append(f"{path.name}:{lineno}: {stripped}")

    assert not offenders, (
        "module-scope import of a dependency CI does not install — pytest imports "
        "this file to collect it even when every test is deselected, so the whole "
        "run fails with a collection error. Move the import inside the function:\n  "
        + "\n  ".join(offenders)
    )
