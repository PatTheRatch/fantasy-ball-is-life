#!/usr/bin/env python3
"""Build a review context bundle for an evidence-based Claude code review.

Why this exists
---------------
A bare `git diff | claude -p "review this"` with no tool access is a *blind*
review: Claude sees the changed hunks but not the surrounding code, the callers,
or the project's own conventions. It catches surface defects (`==` vs `startswith`)
and misses anything that requires context — a helper that already validates the
input, a caller that relies on the old signature, a convention documented in
CONTRIBUTING.md.

This script assembles what the reviewer needs, budgets it, and emits a single
self-contained bundle to stdout. The reviewer needs no tools and no file reads.

Design notes
------------
* Tiered inclusion. Small files go in whole; large files get an annotated
  changed-region preview. Tests always get full bodies — they are the artifact
  that proves the claims.
* Budgeted, not truncating. Anthropic bills cache-miss input at full rate and
  fires a 400 above the context window, so an unbounded bundle is a real cost
  and failure mode. The budget drops whole tiers, lowest value first, and records
  every omission in an inventory the reviewer can see.
* Omissions are reported, never silent. A reviewer that doesn't know what it
  wasn't shown will either guess or claim false authority.

Exit codes: 0 success, 1 error.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Rough bytes-per-token for source code. Deliberately conservative (source is
# denser than prose) so the budget errs toward smaller bundles.
BYTES_PER_TOKEN = 3.6

# Files worth reading for conventions even when unchanged.
CONVENTION_FILES = ("CONTRIBUTING.md", "CLAUDE.md", ".claude/CLAUDE.md")

# Never bundle these. Lockfiles are enormous and worthless to a reviewer.
SKIP_SUFFIXES = (".lock", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf",
                 ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".zip")
SKIP_NAMES = ("package-lock.json", "poetry.lock", "uv.lock", "yarn.lock")


def sh(args: list[str]) -> str:
    """Run a command, returning stdout. Raises on failure."""
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({result.returncode}): {' '.join(args)}\n{result.stderr.strip()}"
        )
    return result.stdout


def git_try(args: list[str]) -> str:
    """Run a git command, returning stdout or '' on failure (best-effort calls)."""
    try:
        return sh(["git", *args])
    except RuntimeError:
        return ""


def is_test_path(path: str) -> bool:
    """True for test files, matched by convention rather than substring.

    A naive `"test" in name` also matches `latest_scores.py`, `greatest.py`,
    `contest.py` — bundling large unrelated files in full and eating the budget
    that previews need.
    """
    name = Path(path).name.lower()
    if name.startswith("test_") or name.endswith(("_test.py", ".test.ts", ".test.tsx",
                                                  ".spec.ts", ".spec.tsx")):
        return True
    parts = path.split("/")
    return "tests" in parts[:-1] or "test" in parts[:-1] or "__tests__" in parts


def is_skippable(path: str) -> bool:
    """True for lockfiles and binary assets — never worth bundling."""
    if any(path.endswith(s) for s in SKIP_SUFFIXES):
        return True
    return Path(path).name in SKIP_NAMES


def read_lines(repo: Path, path: str, rev: str | None = None) -> list[str] | None:
    """Read a file's lines.

    With `rev`, the content is read from that git revision (`git show rev:path`),
    which is what you want when reviewing a branch that isn't checked out. Without
    it, the working tree is read.

    Returns None if the file is missing at that revision, unreadable, or binary —
    the caller must distinguish those cases to avoid reporting a false 'binary'.
    """
    if rev:
        try:
            text = sh(["git", "show", f"{rev}:{path}"])
        except RuntimeError as exc:
            message = str(exc)
            missing = ("does not exist", "exists on disk", "unknown revision")
            if any(token in message for token in missing):
                return None
            raise
        if "\x00" in text[:4096]:
            return None
        return text.splitlines()

    target = repo / path
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if "\x00" in text[:4096]:
        return None
    return text.splitlines()


def classify_absence(repo: Path, path: str, rev: str | None) -> str:
    """Explain *why* a file couldn't be read. Never guess 'binary'."""
    if is_skippable(path):
        return "binary/lockfile — deliberately skipped"
    if rev:
        if read_lines(repo, path, rev) is not None:
            return "readable"
        return f"not present at {rev} (deleted, renamed, or path mismatch)"
    if not (repo / path).exists():
        return "not present in the working tree (check out the branch being reviewed)"
    return "binary or non-UTF-8 content"


def changed_line_map(diff: str, prefix: str) -> dict[str, set[int]]:
    """Map path -> set of changed new-side line numbers, from a raw diff.

    `prefix` selects the side: 'b/' for new-side (added/context) lines.
    """
    out: dict[str, set[int]] = {}
    current: str | None = None
    new_ln = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            header = raw[4:].strip()
            current = header[len(prefix):] if header.startswith(prefix) else None
            if current is not None:
                out.setdefault(current, set())
        elif raw.startswith("@@") and current is not None:
            # @@ -a,b +c,d @@
            try:
                after_plus = raw.split("+", 1)[1]
                new_ln = int(after_plus.split(",", 1)[0].split(" ", 1)[0])
            except (IndexError, ValueError):
                new_ln = 0
        elif current is not None and raw[:1] in {"+", " "} and not raw.startswith("+++"):
            out[current].add(new_ln)
            new_ln += 1
    return out


def preview(lines: list[str], changed: set[int], radius: int) -> tuple[str, list[tuple[int, int]]]:
    """Annotated preview of the changed regions of a file.

    Returns the rendered preview and the list of (start, end) ranges it covers,
    so the caller can report what was left out.
    """
    if not changed:
        return "", []
    wanted: set[int] = set()
    for ln in changed:
        for offset in range(-radius, radius + 1):
            candidate = ln + offset
            if 1 <= candidate <= len(lines):
                wanted.add(candidate)

    # A stale line map (e.g. from a rebase or a mismatch between the diffed ref
    # and the file revision) can reference lines that don't exist. Return empty
    # rather than raising — the caller reports the omission instead of dying.
    if not wanted:
        return "", []

    ranges: list[tuple[int, int]] = []
    ordered = sorted(wanted)
    start = prev = ordered[0]
    for ln in ordered[1:]:
        if ln == prev + 1:
            prev = ln
            continue
        ranges.append((start, prev))
        start = prev = ln
    ranges.append((start, prev))

    chunks = []
    for start, end in ranges:
        chunks.append(f"      [... lines {start}-{end} ...]")
        for ln in range(start, end + 1):
            marker = ">" if ln in changed else " "
            chunks.append(f"   {marker}{ln:>5}| {lines[ln - 1]}")
    return "\n".join(chunks), ranges


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/v2", help="base ref (default: origin/v2)")
    parser.add_argument("--head", default="HEAD", help="head ref (default: HEAD)")
    parser.add_argument("--repo", default=".", help="repo root (default: cwd)")
    parser.add_argument("--budget", type=int, default=60_000,
                        help="bundle token budget (default: 60000)")
    parser.add_argument("--full-file-lines", type=int, default=400,
                        help="include whole files up to this many lines (default: 400)")
    parser.add_argument("--preview-radius", type=int, default=12,
                        help="context lines around each change (default: 12)")
    parser.add_argument("--pr-body", default=None,
                        help="path to a file containing the PR description")
    parser.add_argument("--source-rev", default=None,
                        help="read file contents from this git rev instead of the "
                             "working tree (use when the branch under review is not "
                             "checked out, e.g. reviewing a remote branch)")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"error: {repo} is not a git repository", file=sys.stderr)
        return 1

    # Default the source revision to the head ref when it isn't the working tree,
    # so reviewing a remote branch doesn't silently read the wrong files.
    source_rev = args.source_rev
    if source_rev is None and args.head not in ("HEAD", ""):
        source_rev = args.head

    raw_diff = git_try(["diff", "--no-color", f"{args.base}...{args.head}"])
    if not raw_diff.strip():
        print(f"error: empty diff between {args.base} and {args.head}", file=sys.stderr)
        return 1

    files = [f for f in git_try(["diff", "--name-only", f"{args.base}...{args.head}"]).split()
             if f.strip()]
    stats = git_try(["diff", "--stat", f"{args.base}...{args.head}"])
    changed = changed_line_map(raw_diff, "b/")

    # (title, priority, body) — HIGHER priority number = dropped first.
    sections: list[tuple[str, int, str]] = []
    omitted: list[str] = []

    # --- Tier 1 (priority 0): the convention files. Cheap, high signal. ---
    for name in CONVENTION_FILES:
        text = read_lines(repo, name, source_rev)
        if text:
            sections.append((f"Convention: {name}", 0, "\n".join(text)))

    # --- Tier 2 (priority 1): whole small files + all test files. ---
    # Test files always go in whole: they are the evidence for the PR's claims,
    # and a partial test file is misleading.
    for path in files:
        if is_skippable(path):
            omitted.append(f"{path} ({classify_absence(repo, path, source_rev)})")
            continue
        lines = read_lines(repo, path, source_rev)
        if lines is None:
            omitted.append(f"{path} ({classify_absence(repo, path, source_rev)})")
            continue
        if is_test_path(path) or len(lines) <= args.full_file_lines:
            body = "\n".join(f"  {n:>5}| {line}" for n, line in enumerate(lines, 1))
            sections.append((f"Full file: {path} ({len(lines)} lines)", 1, body))

    # --- Tier 3 (priority 2): annotated previews for large non-test files. ---
    for path in files:
        if is_skippable(path) or any(s[0].startswith(f"Full file: {path} ") for s in sections):
            continue
        lines = read_lines(repo, path, source_rev)
        if lines is None:
            continue
        body, ranges = preview(lines, changed.get(path, set()), args.preview_radius)
        if not body:
            continue
        shown = sum(e - s + 1 for s, e in ranges)
        note = ""
        if shown < len(lines):
            note = f"\n  [{len(lines) - shown} unchanged lines not shown — ask for more if needed]"
        sections.append((f"Preview: {path} ({len(lines)} lines total)", 2, body + note))

    # --- The diff itself. Never dropped. ---
    diff_section = (f"Diff: {args.base}...{args.head}", -1, raw_diff)

    # --- Assemble under budget, dropping lowest-value tiers first. ---
    budget_bytes = int(args.budget * BYTES_PER_TOKEN)
    fixed = len(diff_section[2].encode())
    kept: list[tuple[str, int, str]] = []
    used = fixed
    for title, priority, body in sorted(sections, key=lambda s: s[1]):
        size = len(body.encode())
        if used + size > budget_bytes:
            omitted.append(f"{title} (over budget)")
            continue
        kept.append((title, priority, body))
        used += size

    # --- Render ---
    out = sys.stdout
    print("# REVIEW CONTEXT BUNDLE", file=out)
    print(f"\nBase: `{args.base}`  Head: `{args.head}`", file=out)
    print(f"Files changed: {len(files)}  Bundle: ~{int(used / BYTES_PER_TOKEN):,} tokens "
          f"(budget {args.budget:,})", file=out)

    print("\n## Change stat\n\n```", file=out)
    print(stats.strip(), file=out)
    print("```", file=out)

    if args.pr_body:
        try:
            body = Path(args.pr_body).read_text(encoding="utf-8")
            print("\n## Author's claims (PR description)\n", file=out)
            print("Verify these against the diff. An unverified claim is a finding.\n", file=out)
            print(body.strip(), file=out)
        except OSError as exc:
            print(f"\n[could not read PR body {args.pr_body}: {exc}]", file=out)

    if omitted:
        print("\n## Bundle inventory — NOT included\n", file=out)
        print("These were deliberately left out. Say so in `## Gaps` "
              "if you needed one.\n", file=out)
        for item in omitted:
            print(f"- {item}", file=out)

    for title, _priority, body in kept:
        print(f"\n## {title}\n", file=out)
        print("```", file=out)
        print(body, file=out)
        print("```", file=out)

    print(f"\n## {diff_section[0]}\n", file=out)
    print("```diff", file=out)
    print(diff_section[2].rstrip(), file=out)
    print("```", file=out)

    return 0


if __name__ == "__main__":
    sys.exit(main())
