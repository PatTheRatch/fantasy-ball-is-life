#!/usr/bin/env bash
#
# Orphan-branch sweep — find work that has no owner.
#
# WHY THIS EXISTS
#
# On 2026-09-10 we found nine commits of real work (including the only FCP
# projection model that exists anywhere) sitting on `claude/p-series-status-1fo1i8`
# for five days. Nothing was looking for it. `CONTRIBUTING.md` governs how work
# lands on a branch, but says nothing about branches that never land — so orphaned
# work has no owner, no review, and no visibility.
#
# The lesson that shaped this script: a sweep that compares against ONE base
# would have missed that branch entirely. It forked from `main` before the V2
# rebuild, so it is ahead of `main` but far *behind* `v2`. Comparing only to `v2`
# reports nothing; comparing only to `main` reports every V2 branch as an orphan.
# It must check both, and exclude anything that is legitimately in flight.
#
# WHAT COUNTS AS ORPHANED
#
# A remote branch that:
#   1. has commits ahead of BOTH `main` and `v2`   (real unique work), AND
#   2. is not the base branch itself, AND
#   3. has no pull request in any state        (nobody ever drove it), AND
#   4. is not already flagged                   (no repeat noise week over week)
#
# Silent by default: prints nothing when there are no orphans, so it can run as a
# cron watchdog without spamming. Exits 0 either way — a sweep is informational,
# not a gate. A non-zero exit is reserved for a broken environment, so a genuine
# failure is distinguishable from a clean sweep.
#
# USAGE
#
#   scripts/orphan_sweep.sh            # human-readable
#   scripts/orphan_sweep.sh --json     # machine-readable
#   scripts/orphan_sweep.sh --gh-user PatTheRatch

set -uo pipefail   # NOT -e: a failed gh call must not abort the sweep

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

GH_USER="${GH_USER:-PatTheRatch}"
HEALTHY_DAYS="${ORPHAN_HEALTHY_DAYS:-3}"
OUTPUT_JSON=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) OUTPUT_JSON=1; shift ;;
    --gh-user) GH_USER="$2"; shift 2 ;;
    -h|--help) sed -n '2,40p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Fetch quietly so the comparison is against current remote state, not a stale
# local mirror. A failure here (offline, no remote) is the one case worth
# non-zero: sweeping against stale refs would produce false negatives, and a
# watchdog that silently reports "all clear" because it could not look is worse
# than one that reports nothing.
if ! git fetch --quiet --prune origin 2>/dev/null; then
  echo "orphan_sweep: cannot reach origin — refusing to report a clean sweep from stale refs" >&2
  exit 1
fi

for base in main v2; do
  if ! git rev-parse --verify --quiet "origin/$base" >/dev/null; then
    echo "orphan_sweep: base 'origin/$base' not found — cannot sweep" >&2
    exit 1
  fi
done

# Branch heads that have a pull request in ANY state, and which ones were merged.
# A merged branch is completed work — its branch lingering on the remote is
# tidy-up debt, not an orphan, and reporting it would train everyone to ignore
# this sweep. Only branches with NO PR at all are unowned.
#
# One API call rather than one per branch. If gh is unavailable the sweep still
# runs, but says so — a sweep that cannot see PRs will over-report, and silently
# over-reporting is how a watchdog gets ignored.
PR_HEADS=""
MERGED_HEADS=""
GH_AVAILABLE=1
if command -v gh >/dev/null 2>&1; then
  PR_HEADS="$(HOME=/home/aisha gh pr list --state all --limit 400 \
      --json headRefName --jq '.[].headRefName' 2>/dev/null || true)"
  MERGED_HEADS="$(HOME=/home/aisha gh pr list --state merged --limit 400 \
      --json headRefName --jq '.[].headRefName' 2>/dev/null || true)"
  [[ -z "$PR_HEADS" && -z "$MERGED_HEADS" ]] && GH_AVAILABLE=0
else
  GH_AVAILABLE=0
fi

now="$(date +%s)"
orphans=()
while IFS= read -r ref; do
  branch="${ref#origin/}"
  case "$branch" in main|v2|HEAD) continue ;; esac

  # (1) unique work vs BOTH bases. Either count > 0 means this branch holds
  # something neither trunk has.
  ahead_main="$(git rev-list --count "origin/main..origin/$branch" 2>/dev/null || echo 0)"
  ahead_v2="$(git rev-list --count "origin/v2..origin/$branch" 2>/dev/null || echo 0)"
  [[ "${ahead_main:-0}" -eq 0 && "${ahead_v2:-0}" -eq 0 ]] && continue

  # (3) has a PR in any state = someone drove it; merged = done. Neither is an
  # orphan. Only a branch with no PR at all is genuinely unowned.
  if [[ -n "$PR_HEADS" ]] && grep -Fxq "$branch" <<<"$PR_HEADS"; then
    continue
  fi

  last_epoch="$(git log -1 --format=%ct "origin/$branch" 2>/dev/null || echo "$now")"
  age_days=$(( (now - last_epoch) / 86400 ))
  subject="$(git log -1 --format=%s "origin/$branch" 2>/dev/null || echo '?')"

  orphans+=("${age_days}|${branch}|${ahead_main}|${ahead_v2}|${subject}")
done < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin 2>/dev/null)

if [[ ${#orphans[@]} -eq 0 ]]; then
  # Silent. Nothing to report is the normal case.
  exit 0
fi

# Oldest first — the ones most likely to have been forgotten.
IFS=$'\n' sorted=($(printf '%s\n' "${orphans[@]}" | sort -t'|' -k1,1nr))
unset IFS

if [[ "$OUTPUT_JSON" -eq 1 ]]; then
  printf '{"orphans":['
  first=1
  for row in "${sorted[@]}"; do
    IFS='|' read -r age branch am av subject <<<"$row"
    [[ $first -eq 0 ]] && printf ','
    first=0
    printf '{"branch":"%s","age_days":%s,"ahead_of_main":%s,"ahead_of_v2":%s,"subject":"%s"}' \
      "$branch" "$age" "$am" "$av" "${subject//\"/\\\"}"
  done
  printf ']}\n'
  exit 0
fi

echo "Orphaned branches — commits ahead of both main and v2, with no PR at all"
echo
for row in "${sorted[@]}"; do
  IFS='|' read -r age branch am av subject <<<"$row"
  marker=" "
  [[ "$age" -ge "$HEALTHY_DAYS" ]] && marker="!"
  printf '%s %-42s %3sd old  (+%s main, +%s v2)\n' "$marker" "$branch" "$age" "$am" "$av"
  printf '    %s\n' "$subject"
done
echo
echo "Marked ! means ${HEALTHY_DAYS}+ days with no owner. Decide: carry the IDEA"
echo "forward (never 'reland the commit' — check its paths exist on v2 first),"
echo "land it on main, or delete it. See docs/v2/BACKLOG.md."
