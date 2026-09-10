"""D-09 capture harness — regenerate the golden outputs from V1.

**This is NOT part of the default test run.** It is deselected by pytest marker
(`-m capture`) and requires an opt-in dependency extra, because it imports V1's
code and therefore `cvxpy`, `pandas`, and `numpy` — none of which V2 depends on
in production.

Why it is committed anyway
--------------------------
V2 intends to replace V1 entirely. So why keep a script that imports it?

Because without this file the committed goldens are **unfalsifiable magic
numbers**: "someone ran something once and got 744.275; trust us." That is the
same failure as proving a claim in prose, just with numbers instead of words —
and it is exactly the gap D-09's own review named. Committing the harness is what
makes the goldens *evidence*: anyone can re-derive them, and a mismatch can be
triaged as version drift vs port bug rather than becoming a mystery.

The distinction that matters: the goldens are a **committed record**, consulted
in normal CI with no V1 involved. This harness is the **provenance** of that
record, run rarely and on purpose.

Usage
-----
    # from a V1 checkout (worktree of main), with the fixture copied in:
    python tests/oracle/capture_goldens.py --v1-root /path/to/v1 --out /tmp/goldens.json

    # in V2's repo, the goldens are compared by the default test suite:
    pytest tests/oracle/

V1 must be importable from ``--v1-root``. A `main` worktree works:

    git worktree add /tmp/v1 main

Environment notes (learned the hard way)
----------------------------------------
* Construction requires BOTH an injected ``LeagueContext`` AND a stub for
  ``get_cached_my_league`` — the latter does four live ESPN requests.
* ``process_draft_data`` reads ``self.league.draft`` unconditionally, so the
  league stub needs at least ``draft`` and ``teams`` attributes.
* The D-08 fixture must be present in the V1 tree's ``tests/fixtures`` for
  ``v1_adapter`` to import. Copy it in; do not symlink (V1's tree is disposable).

What it captures, and what it deliberately does not
---------------------------------------------------
Nine categories are attempted; **seven succeed**. ``FG%`` and ``FT%`` raise
``KeyError: 'FG% PW'`` — the solver has no percentage "PW" columns, only
``fgm/g PW`` / ``fga/g PW`` / ``ftm/g PW`` / ``fta/g PW``. Percentage categories
are *constrained* (``set_requirements``) but never *maximized* in V1: its own
tests, CLI, and API only ever pass volume stats. Recorded as a limitation, not
papered over — D-12 must reproduce the asymmetry.

The solver-cap contract is captured separately (see ``capture_solver_cap``),
because the timeout path is wall-clock nondeterministic and cannot produce a
stable numeric golden. Details in the D-09 findings doc.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path
from typing import Any

# The nine categories V1's config exposes. Seven are solvable; see module docs.
ALL_CATEGORIES: tuple[str, ...] = ("PTS", "REB", "AST", "STL", "BLK", "3PM", "TO", "FG%", "FT%")

# Pinned constants the goldens are only valid under. Captured into the JSON so a
# future mismatch can be triaged against "did someone change a default?".
CAPTURE_CONSTANTS: dict[str, Any] = {
    "roster_size": 13,
    "initial_budget": 200,
    "minimum_value_players": 3,
    "minimum_game_threshold": 20,
    "value_col": "$",
    "solver_time_limit_seconds": 8,
}

# Rounding policy. Floats are rounded at capture and compared with a tolerance,
# because cross-version numpy/HiGHS can wobble the trailing digits. Exact float
# equality in a golden would flake on the first solver bump.
OBJECTIVE_DECIMALS = 3


def version_manifest() -> dict[str, str]:
    """Record the stack the goldens were produced under.

    Without this, a golden mismatch in D-12 is an uninterpretable mystery. With
    it, "cvxpy moved 1.9.2 -> 1.10" is immediately distinguishable from "the
    port is wrong".
    """
    manifest = {"python": platform.python_version(), "platform": platform.platform()}
    for name in ("cvxpy", "numpy", "pandas", "scipy", "highspy"):
        try:
            module = __import__(name)
            manifest[name] = str(getattr(module, "__version__", "unknown"))
        except ImportError:
            manifest[name] = "absent"
    return manifest


def _install_league_stub() -> None:
    """Inject the fake league V1 needs but cannot fetch in a hermetic run.

    Two things are required and neither is optional:

    1. A ``LeagueContext`` on the ContextVar — the same technique V1's own
       ``tests/conftest.py`` uses.
    2. A stub for ``get_cached_my_league``, which otherwise performs four live
       ESPN requests. ``process_draft_data`` reads ``self.league.draft``
       unconditionally, so the stub needs ``draft`` and ``teams``.

    A ``draft = []`` / ``teams = []`` league is enough for the golden path: it
    represents a draft not yet started, which is what these goldens describe.
    """
    from unittest.mock import patch

    import backend.draft.optimizer as optimizer
    from backend.league.credentials import _LEAGUE_CTX, LeagueContext

    _LEAGUE_CTX.set(
        LeagueContext(
            league_id="d09-capture",
            slug="d09-capture",
            name="D-09 Capture League",
            espn_league_id=123456,
            espn_season=2026,
            swid="d09",
            espn_s2="d09",
            timezone="America/New_York",
        )
    )

    class _StubLeague:
        draft: list[Any] = []
        teams: list[Any] = []

    patcher = patch.object(optimizer, "get_cached_my_league", return_value=_StubLeague())
    patcher.start()


def capture_categories(v1_root: Path) -> dict[str, Any]:
    """Run V1's optimizer against the D-08 fixture for every category."""
    sys.path.insert(0, str(v1_root))

    import backend.draft.optimizer as optimizer
    import pandas as pd

    from tests.fixtures.projections import v1_adapter

    _install_league_stub()

    results: dict[str, Any] = {}
    for category in ALL_CATEGORIES:
        # Rebuild the frame and optimizer per category so no solver state carries
        # across. Cheap (one construction) and removes a whole class of
        # cross-contamination bug from the capture.
        frame = pd.DataFrame(v1_adapter.to_v1_columns(v1_adapter.load_canonical()))
        opt = optimizer.OptimizeLineup(
            projections_df=frame,
            minimum_game_threshold=CAPTURE_CONSTANTS["minimum_game_threshold"],
            value_col=CAPTURE_CONSTANTS["value_col"],
        )
        try:
            roster = opt.optimize_roster(category)
        except Exception as exc:  # noqa: BLE001 - the failure IS the finding
            results[category] = {
                "solvable": False,
                "error_type": type(exc).__name__,
                "error": str(exc)[:300],
            }
            continue

        results[category] = {
            "solvable": True,
            "roster_size": int(len(roster)),
            # Sorted: cvxpy/HiGHS output order is not contractual, and asserting
            # it would make the golden brittle for no gain. Membership is the
            # observable behaviour.
            "roster": sorted(str(name) for name in roster["Name"].tolist()),
            # The objective is the sum of the category's per-week weighted column
            # over the roster — V1 maximizes `player_data_df[f'{cat} PW'] @ vars`
            # and then reports the same quantity. NOT `Value` (that is bid value,
            # summing to the budget) and NOT raw `{cat}` (that is the unweighted
            # per-game total; PTS sums to 212.65 where the objective is 744.275).
            "objective": round(float(roster[f"{category} PW"].sum()), OBJECTIVE_DECIMALS)
            if f"{category} PW" in roster.columns
            else None,
            "cost": round(float(roster["Bid"].sum()), 2) if "Bid" in roster.columns else None,
        }
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v1-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    if not (args.v1_root / "backend" / "draft" / "optimizer.py").exists():
        print(f"not a V1 checkout: {args.v1_root}", file=sys.stderr)
        return 2

    payload = {
        "_note": (
            "Generated by tests/oracle/capture_goldens.py against V1 (main). "
            "Do not hand-edit. Re-run the harness to regenerate."
        ),
        "constants": CAPTURE_CONSTANTS,
        "versions": version_manifest(),
        "categories": capture_categories(args.v1_root),
    }
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    solvable = [c for c, v in payload["categories"].items() if v["solvable"]]
    unsolvable = [c for c, v in payload["categories"].items() if not v["solvable"]]
    print(f"wrote {args.out}")
    print(f"  solvable:   {len(solvable)} {solvable}")
    print(f"  unsolvable: {len(unsolvable)} {unsolvable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
