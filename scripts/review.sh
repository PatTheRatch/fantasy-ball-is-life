#!/usr/bin/env bash
# Usage: ./review.sh [base-branch]
# Pipes the diff against base-branch (default: main) to Claude with the structured review template.
# Outputs to stdout and saves to /tmp/claude-review-<timestamp>.txt

set -euo pipefail

BRANCH="${1:-main}"
TEMPLATE="$(dirname "$0")/docs/claude-prompts/review-template.md"
OUT="/tmp/claude-review-$(date +%Y%m%d-%H%M%S).txt"

echo "=== Reviewing diff against '$BRANCH' ===" | tee "$OUT"
echo "" | tee -a "$OUT"

git diff "$BRANCH"...HEAD | claude -p "$(cat "$TEMPLATE")

Review this diff. Do NOT read any files. Return only the structured review." \
  --model sonnet \
  --max-turns 5 \
  --permission-mode acceptEdits \
  --allowedTools "" \
  --output-format text 2>&1 | tee -a "$OUT"

echo "" | tee -a "$OUT"
echo "=== Review saved to $OUT ===" | tee -a "$OUT"
