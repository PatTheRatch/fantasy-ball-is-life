"""Tests for the review context bundler.

The bundler sits in the review path: if `changed_line_map` mis-parses a hunk
header, every subsequent review is silently degraded — the reviewer gets
previews that omit the lines that actually changed, and nothing fails. These
tests pin the parsing and budget behaviour so that can't happen quietly.

V1: n/a — tooling, no V1 origin.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUNDLER_PATH = REPO_ROOT / "scripts" / "build_review_bundle.py"


def _load_bundler():
    """Import the bundler as a module (it lives in scripts/, not a package)."""
    spec = importlib.util.spec_from_file_location("build_review_bundle", BUNDLER_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_review_bundle"] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bundler():
    return _load_bundler()


# --- is_test_path -----------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        "tests/test_standings.py",
        "test_scoring.py",
        "backend/tests/test_api.py",
        "frontend/src/features/standings/LeaguePage.test.tsx",
        "frontend/src/lib/format.spec.ts",
        "frontend/src/__tests__/util.ts",
        "src/test/helpers.py",
    ],
)
def test_recognises_test_paths(bundler, path):
    assert bundler.is_test_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        # The substring-match false positives that ate the budget: none of
        # these are tests, though each contains "test" as a substring.
        "backend/latest_scores.py",
        "backend/greatest_hits.py",
        "backend/contest.py",
        "backend/projections/attestation.py",
        "frontend/src/features/standings/LeaguePage.tsx",
    ],
)
def test_rejects_substring_false_positives(bundler, path):
    assert bundler.is_test_path(path) is False


# --- is_skippable -----------------------------------------------------------

@pytest.mark.parametrize(
    "path", ["package-lock.json", "poetry.lock", "uv.lock", "logo.png", "font.woff2"]
)
def test_skips_lockfiles_and_binaries(bundler, path):
    assert bundler.is_skippable(path) is True


@pytest.mark.parametrize("path", ["backend/api/main.py", "frontend/src/App.tsx", "README.md"])
def test_keeps_source_files(bundler, path):
    assert bundler.is_skippable(path) is False


# --- changed_line_map -------------------------------------------------------

def test_changed_line_map_parses_hunk_headers(bundler):
    """New-side line numbers must be tracked accurately across hunks.

    A `@@ -a,b +c,d @@` header with b/d omitted means '1 line', not '0' — the
    shorthand is easy to mis-parse and would shift every later hunk.
    """
    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -10,3 +10,4 @@ def f():\n"
        " context\n"          # new line 10
        "-old\n"              # consumes no new-side number
        "+new\n"              # new line 11
        "+added\n"            # new line 12
        "@@ -50 +51 @@\n"     # no counts → single line each side
        "-gone\n"
        "+fresh\n"            # new line 51
    )
    result = bundler.changed_line_map(diff, "b/")

    assert "x.py" in result
    # Added lines are tracked; deleted lines are not (they have no new-side number).
    assert 11 in result["x.py"], "first added line should map to new-side 11"
    assert 12 in result["x.py"], "second added line should map to new-side 12"
    assert 51 in result["x.py"], "post-hunk added line should map to new-side 51"
    # 50 does not exist in the new file at that point; the hunk starts at 51.
    assert 50 not in result["x.py"]


def test_changed_line_map_records_context_lines(bundler):
    """Context lines advance the counter and are part of the changed region."""
    diff = (
        "diff --git a/y.py b/y.py\n"
        "--- a/y.py\n"
        "+++ b/y.py\n"
        "@@ -1,3 +1,3 @@\n"
        " ctx_one\n"    # 1
        "-removed\n"
        "+replaced\n"   # 2
        " ctx_two\n"    # 3
    )
    result = bundler.changed_line_map(diff, "b/")
    assert result["y.py"] == {1, 2, 3}


def test_changed_line_map_multiple_files(bundler):
    diff = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n"
        "@@ -1 +1 @@\n-x\n+y\n"
        "diff --git a/b.py b/b.py\n--- a/b.py\n+++ b/b.py\n"
        "@@ -5 +5 @@\n-p\n+q\n"
    )
    result = bundler.changed_line_map(diff, "b/")
    assert result["a.py"] == {1}
    assert result["b.py"] == {5}


def test_changed_line_map_ignores_file_header_lines(bundler):
    """`--- a/x` and `+++ b/x` must not be counted as content lines."""
    diff = (
        "diff --git a/z.py b/z.py\n"
        "--- a/z.py\n"
        "+++ b/z.py\n"
        "@@ -1 +1 @@\n-a\n+b\n"
    )
    result = bundler.changed_line_map(diff, "b/")
    # Only the real added line, not the +++ header.
    assert result["z.py"] == {1}


# --- preview ----------------------------------------------------------------

def test_preview_marks_changed_lines_and_coalesces_ranges(bundler):
    lines = [f"line {i}" for i in range(1, 41)]
    body, ranges = bundler.preview(lines, {10, 11, 12}, radius=2)

    # 8-14 (10-2 .. 12+2) coalesces into a single range.
    assert ranges == [(8, 14)]
    assert ">   10|" in body, "changed lines are marked with '>'"
    assert "    9|" in body, "context lines are marked with ' '"


def test_preview_splits_distant_ranges(bundler):
    lines = [f"line {i}" for i in range(1, 101)]
    _body, ranges = bundler.preview(lines, {10, 80}, radius=3)
    assert ranges == [(7, 13), (77, 83)]


def test_preview_clamps_at_file_boundaries(bundler):
    lines = [f"line {i}" for i in range(1, 6)]
    _body, ranges = bundler.preview(lines, {1, 5}, radius=4)
    assert ranges == [(1, 5)], "radius must not run off the start or end of the file"


def test_preview_empty_when_nothing_changed(bundler):
    lines = ["a", "b"]
    body, ranges = bundler.preview(lines, set(), radius=2)
    assert body == ""
    assert ranges == []


def test_preview_handles_change_beyond_eof(bundler):
    """A stale line map can reference lines past the end; must not raise."""
    lines = ["a", "b", "c"]
    body, ranges = bundler.preview(lines, {99}, radius=2)
    assert isinstance(body, str)
    assert all(1 <= s <= e <= 3 for s, e in ranges)
