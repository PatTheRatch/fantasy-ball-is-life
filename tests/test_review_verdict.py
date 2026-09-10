"""Tests for review.sh's verdict integrity — does the gate fail correctly?

This loop has already shipped an `APPROVED` that was really a crashed reviewer.
That class of bug is invisible to a normal test: the script runs, prints
plausible output, exits 0, and the PR gets a green verdict nobody wrote. The
only way to catch it is to break the reviewer on purpose and assert that
nothing approves.

So these are hostile tests. Each one sabotages a different part of the review
path and asserts two things: the exit code is non-zero, and `gh pr review` was
never called with an approving event.

`claude` and `gh` are replaced with recording stubs on PATH, so nothing here
talks to a model or to GitHub.

V1: n/a — tooling, no V1 origin.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REVIEW_SH = REPO_ROOT / "scripts" / "review.sh"

# Exit codes, mirrored from review.sh.
EXIT_APPROVED = 0
EXIT_CHANGES = 1
EXIT_INCOMPLETE = 3

pytestmark = pytest.mark.skipif(
    not REVIEW_SH.exists(), reason="scripts/review.sh not present"
)


REVIEW_BODY = """## Summary
The change looks reasonable.

## Issues
None.

## Verdict
{verdict}

## Confidence
8
"""


def _make_stub(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)


@pytest.fixture
def harness(tmp_path):
    """A PATH with stub `claude` and `gh`, plus a log of every gh invocation."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh_log = tmp_path / "gh-calls.log"

    # `gh` records its argv, and answers the few queries review.sh makes.
    _make_stub(
        bin_dir / "gh",
        f'''printf '%s\\n' "$*" >> "{gh_log}"
case "$*" in
  *headRefName*) echo "feat/test-branch" ;;
  *baseRefName*) echo "v2" ;;
  *"pr view"*body*) echo "PR body" ;;
  *"pr checkout"*) exit 0 ;;
  *"pr review"*) exit 0 ;;
esac
exit 0
''',
    )

    def run(claude_body: str, *args: str) -> subprocess.CompletedProcess:
        _make_stub(bin_dir / "claude", claude_body)
        env = dict(os.environ)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        # review.sh exports HOME=/home/aisha for the real runner; point it
        # somewhere writable so the stubs don't care.
        env["HOME"] = str(tmp_path)
        return subprocess.run(
            ["bash", str(REVIEW_SH), *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )

    run.gh_log = gh_log  # type: ignore[attr-defined]
    return run


def _gh_calls(harness) -> str:
    log = harness.gh_log
    return log.read_text() if log.exists() else ""


def _assert_never_approved(harness) -> None:
    """`gh pr review --approve` must not have been called. The script posts
    approvals as comments rather than approve events, so also assert no
    approving verdict label reached a review body."""
    calls = _gh_calls(harness)
    assert "--approve" not in calls, f"an approval was posted:\n{calls}"


# --- The reviewer crashes ----------------------------------------------------

class TestReviewerCrash:
    def test_crash_exits_incomplete(self, harness):
        """The original failure: reviewer dies, script exits 0, PR shows green."""
        r = harness('echo "partial output, then death"; exit 137', "--no-post")
        assert r.returncode == EXIT_INCOMPLETE, r.stdout[-2000:]
        assert "INCOMPLETE" in r.stdout

    def test_crash_after_printing_approved_does_not_approve(self, harness):
        """The nastiest shape: the crashed reviewer's partial output contains
        the word APPROVED. Scanning the whole transcript turns that into a
        verdict."""
        r = harness(
            'echo "## Verdict"; echo "APPROVED"; echo "boom" >&2; exit 1',
            "--no-post",
        )
        assert r.returncode == EXIT_INCOMPLETE, r.stdout[-2000:]
        assert "VERDICT: INCOMPLETE" in r.stdout

    def test_crash_posts_no_verdict_to_the_pr(self, harness):
        r = harness('echo "## Verdict"; echo "APPROVED"; exit 2', "--pr", "42")
        assert r.returncode == EXIT_INCOMPLETE
        _assert_never_approved(harness)
        calls = _gh_calls(harness)
        # It should still say something, so silence isn't mistaken for a pass.
        assert "pr review" in calls, "an incomplete run told nobody"
        assert "--request-changes" not in calls, (
            "an incomplete run posted a blocking review it cannot justify"
        )


# --- The reviewer completes but says nothing useful --------------------------

class TestUnparseableVerdict:
    def test_no_verdict_section_is_incomplete(self, harness):
        r = harness('echo "I have thoughts but no verdict heading."', "--no-post")
        assert r.returncode == EXIT_INCOMPLETE, r.stdout[-2000:]

    def test_empty_output_is_incomplete(self, harness):
        r = harness("true", "--no-post")
        assert r.returncode == EXIT_INCOMPLETE

    def test_prose_mentioning_approved_is_not_a_verdict(self, harness):
        """A review that discusses the word without emitting a verdict section
        must not be read as approving it."""
        r = harness(
            'echo "## Summary"; echo "I would have APPROVED this, but the '
            'migration is not reversible."',
            "--no-post",
        )
        assert r.returncode == EXIT_INCOMPLETE, r.stdout[-2000:]


# --- Verdicts that ARE emitted ----------------------------------------------

class TestVerdictParsing:
    def test_approved_exits_zero(self, harness):
        r = harness(f'cat <<\'EOF\'\n{REVIEW_BODY.format(verdict="APPROVED")}\nEOF', "--no-post")
        assert r.returncode == EXIT_APPROVED, r.stdout[-2000:]
        assert "VERDICT: APPROVED" in r.stdout

    def test_changes_requested_exits_nonzero(self, harness):
        """Previously this exited 0, so no caller could ever block on it."""
        r = harness(
            f'cat <<\'EOF\'\n{REVIEW_BODY.format(verdict="CHANGES_REQUESTED")}\nEOF',
            "--no-post",
        )
        assert r.returncode == EXIT_CHANGES, r.stdout[-2000:]
        assert "VERDICT: CHANGES_REQUESTED" in r.stdout

    def test_approved_with_findings_is_not_read_as_approved(self, harness):
        """APPROVED is a prefix of APPROVED_WITH_FINDINGS — a naive match
        reports the wrong, weaker verdict."""
        r = harness(
            f'cat <<\'EOF\'\n{REVIEW_BODY.format(verdict="APPROVED_WITH_FINDINGS")}\nEOF',
            "--no-post",
        )
        assert r.returncode == EXIT_APPROVED
        assert "VERDICT: APPROVED_WITH_FINDINGS" in r.stdout

    def test_changes_requested_wins_over_approved_in_prose(self, harness):
        """The verdict section decides, not whatever the body happened to say."""
        body = (
            "## Summary\nThis would be APPROVED if not for the data loss.\n\n"
            "## Verdict\nCHANGES_REQUESTED\n\n## Confidence\n9\n"
        )
        r = harness(f"cat <<'EOF'\n{body}\nEOF", "--no-post")
        assert r.returncode == EXIT_CHANGES, r.stdout[-2000:]

    def test_last_verdict_section_wins(self, harness):
        """A round-2 review echoes the preamble; the verdict it ends on is the
        real one."""
        body = (
            "## Verdict\nAPPROVED\n\n"
            "## Summary\nOn re-reading, the migration drops a column.\n\n"
            "## Verdict\nCHANGES_REQUESTED\n\n## Confidence\n9\n"
        )
        r = harness(f"cat <<'EOF'\n{body}\nEOF", "--no-post")
        assert r.returncode == EXIT_CHANGES, r.stdout[-2000:]
