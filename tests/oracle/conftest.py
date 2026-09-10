"""Oracle-suite configuration.

The V1 checkout location comes from an **environment variable**, not a pytest
option, and that is deliberate.

An earlier version used ``--v1-root``. Because the capture tests are collected by
the same pytest run as the default suite, passing a path *into* the V1 tree made
pytest treat it as a rootdir candidate and collect V1's own
``tests/conftest.py`` — which imports ``backend.league.credentials`` at module
scope and fails outright when the V1 tree is not the active rootdir.

An env var keeps the V1 tree off pytest's path entirely. The capture tests add it
to ``sys.path`` themselves when they need to import V1.

    D09_V1_ROOT=/path/to/v1-worktree pytest -m capture tests/oracle/
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def v1_root() -> Path:
    """Path to a V1 checkout (a ``main`` worktree is fine).

    Skipped rather than failed when absent, so running ``-m capture`` on a machine
    without a V1 tree reports a clear skip instead of a confusing import error.
    """
    configured = os.environ.get("D09_V1_ROOT")
    if not configured:
        pytest.skip("D09_V1_ROOT not set (export it to a V1 `main` worktree)")
    root = Path(configured)
    if not (root / "backend" / "draft" / "optimizer.py").exists():
        pytest.skip(f"no V1 checkout at {root}")
    return root
