#!/usr/bin/env bash
# review.sh — context-aware, evidence-based Claude review that posts to the PR.
#
# Usage:
#   scripts/review.sh                       # review working tree vs origin/v2
#   scripts/review.sh --base origin/main    # different base
#   scripts/review.sh --pr 42               # review PR #42, post the verdict to GitHub
#   scripts/review.sh --no-post             # don't post, just print
#   scripts/review.sh --round 2             # second round; adds a re-review preamble
#
# Why this replaces the old diff-pipe:
#   1. Context. The old script piped the bare diff and told Claude not to read
#      files, so it reviewed blind — surface defects only. This builds a bundle
#      (changed regions in context, whole small files, test bodies, conventions)
#      via scripts/build_review_bundle.py.
#   2. Model. First-pass review runs on opus (per the aisha-claude-loop skill).
#      The old script hardcoded sonnet while being called "the review" — which
#      silently shipped the weaker reviewer while the stronger one sat idle on a
#      flat subscription. Cheap implementer, expensive reviewer: that's the split.
#   3. Durability. The verdict lands on the PR as a formal review, not in /tmp.
#      A review nobody can see from GitHub isn't a gate.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BASE="origin/v2"
PR=""
POST=1
ROUND=1
MODEL="opus"
BUDGET=60000
PR_BODY_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base)   BASE="$2"; shift 2 ;;
    --pr)     PR="$2"; shift 2 ;;
    --no-post) POST=0; shift ;;
    --round)  ROUND="$2"; shift 2 ;;
    --model)  MODEL="$2"; shift 2 ;;
    --budget) BUDGET="$2"; shift 2 ;;
    --body-file) PR_BODY_FILE="$2"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

# The runner's $HOME points at the Hermes profile home, so Claude can't find its
# OAuth creds; and a stale ANTHROPIC_API_KEY in the env overrides OAuth and 401s.
# Both parts of this prefix are load-bearing — see the aisha-claude-loop skill.
CLAUDE=(env -u ANTHROPIC_API_KEY claude)
export HOME=/home/aisha

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="/tmp/claude-review-${STAMP}.txt"
BUNDLE="/tmp/review-bundle-${STAMP}.txt"

# --- Resolve the comparison range -------------------------------------------
if [[ -n "$PR" ]]; then
  BRANCH="$(HOME=/home/aisha gh pr view "$PR" --json headRefName --jq '.headRefName')"
  BASE="$(HOME=/home/aisha gh pr view "$PR" --json baseRefName --jq '.baseRefName')"
  echo "=== PR #$PR — $BRANCH → $BASE ===" | tee "$OUT"
else
  BRANCH="$(git branch --show-current)"
  echo "=== Reviewing ${BRANCH:-detached HEAD} against $BASE ===" | tee "$OUT"
fi

# The bundle must diff against a ref we actually have.
if ! git rev-parse --verify --quiet "$BASE" >/dev/null; then
  echo "error: base ref '$BASE' not found. Try: git fetch origin" |& tee -a "$OUT"; exit 1
fi
git fetch origin "$BASE" --quiet 2>/dev/null || true

# --- Build the context bundle -----------------------------------------------
echo "" | tee -a "$OUT"
echo "--- building context bundle (budget ${BUDGET} tokens) ---" | tee -a "$OUT"

BUNDLE_ARGS=(--base "$BASE" --head HEAD --budget "$BUDGET")
if [[ -n "$PR_BODY_FILE" && -f "$PR_BODY_FILE" ]]; then
  BUNDLE_ARGS+=(--pr-body "$PR_BODY_FILE")
elif [[ -n "$PR" ]]; then
  HOME=/home/aisha gh pr view "$PR" --json body --jq '.body' > "/tmp/pr-body-$PR.txt" 2>/dev/null || true
  [[ -s "/tmp/pr-body-$PR.txt" ]] && BUNDLE_ARGS+=(--pr-body "/tmp/pr-body-$PR.txt")
fi

python3 scripts/build_review_bundle.py "${BUNDLE_ARGS[@]}" > "$BUNDLE"

# Report the bundle's own inventory so the omission list is visible locally too.
grep -A40 "Bundle inventory" "$BUNDLE" | head -25 | tee -a "$OUT" || true

PROMPT="$(cat docs/claude-prompts/review-template.md)"

if [[ "$ROUND" -gt 1 ]]; then
  PROMPT="--- RE-REVIEW: ROUND ${ROUND} ---
This is a re-review. Your previous round raised findings; the author has pushed fixes.
For each previously-raised finding, state whether it is RESOLVED, PARTIALLY RESOLVED, or
NOT ADDRESSED, and check that the fix did not introduce a new defect. Then apply the full
review below to the current state of the change.

${PROMPT}"
fi

# --- Run the review ----------------------------------------------------------
echo "" | tee -a "$OUT"
echo "--- review: model=$MODEL round=$ROUND ---" | tee -a "$OUT"
echo "" | tee -a "$OUT"

set +e
"${CLAUDE[@]}" -p "$PROMPT" \
  --model "$MODEL" \
  --max-turns 6 \
  --allowedTools "" \
  --output-format text < "$BUNDLE" 2>&1 | tee -a "$OUT"
REVIEW_EXIT="${PIPESTATUS[0]}"
set -e

if [[ "$REVIEW_EXIT" -ne 0 ]]; then
  echo "" | tee -a "$OUT"
  echo "!!! claude exited $REVIEW_EXIT — treat this review as INCOMPLETE, not as approval" | tee -a "$OUT"
fi

echo "" | tee -a "$OUT"
echo "=== review saved to $OUT (bundle: $BUNDLE) ===" | tee -a "$OUT"

# --- Determine the verdict ---------------------------------------------------
# `VERDICT` is only meaningful when a verdict token was actually emitted; with
# `set -u` an unset expansion aborts the script, so initialise it explicitly.
VERDICT=""
if [[ -f "$OUT" ]]; then
  VERDICT="$(grep -oE 'APPROVED_WITH_FINDINGS|CHANGES_REQUESTED|APPROVED' "$OUT" | tail -1 || true)"
fi

# --- Post to the PR ----------------------------------------------------------
if [[ "$POST" -eq 1 && -n "$PR" ]]; then
  case "$VERDICT" in
    APPROVED)                EVENT="comment";  LABEL="APPROVED" ;;
    APPROVED_WITH_FINDINGS)  EVENT="comment";  LABEL="APPROVED_WITH_FINDINGS" ;;
    CHANGES_REQUESTED)       EVENT="request-changes"; LABEL="CHANGES_REQUESTED" ;;
    *)                       EVENT="comment";  LABEL="UNPARSED — review did not emit a verdict" ;;
  esac

  {
    echo "## 🤖 Claude review — round $ROUND"
    echo ""
    echo "**Verdict: ${LABEL}** &nbsp;·&nbsp; model: \`${MODEL}\` &nbsp;·&nbsp; \`$(git rev-parse --short HEAD)\`"
    echo ""
    echo "---"
    echo ""
    # Extract the review body between the Summary heading and the trailing
    # "=== review saved" banner, dropping the trailing Confidence block.
    sed -n '/^## Summary/,$p' "$OUT" \
      | sed '/^=== review saved/,$d' \
      | sed '/^## Confidence/,$d'
    echo ""
    echo "---"
    echo ""
    echo "<sub>Reviewed with a context bundle (~$(grep -c '' "$BUNDLE") lines: changed regions in context, whole small files, test bodies, project conventions) — not just the raw diff. Per the loop's rule, any HIGH/MED finding blocks the merge; LOW findings are expected to be folded in before merging, not deferred.</sub>"
  } > "/tmp/pr-review-$PR.md"

  echo "" | tee -a "$OUT"
  if HOME=/home/aisha gh pr review "$PR" --"$EVENT" --body-file "/tmp/pr-review-$PR.md" 2>&1 | tee -a "$OUT"; then
    echo "=== verdict posted to PR #$PR as $EVENT ===" | tee -a "$OUT"
  else
    echo "!!! could not post review to PR #$PR (PAT scope?). Review text is in $OUT" | tee -a "$OUT"
  fi
fi

[[ -n "$VERDICT" ]] && echo "VERDICT: $VERDICT"
exit 0
