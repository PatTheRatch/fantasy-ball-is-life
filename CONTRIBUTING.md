# Contributing

How work gets from an idea to `main` on this project. Roles are defined in
[`docs/AISHA_OPERATING_MANUAL.md`](docs/AISHA_OPERATING_MANUAL.md); this doc is
the mechanics.

## The rule

**No direct commits to `main`.** Every change lands through a pull request that
Aisha (lead systems engineer) has approved. `main` stays deployable at all times.

## The flow

Aisha (lead implementer) and Claude (reviewer/scoper) work in a tight loop.
Patrick is notified when a feature series completes — he does not participate
in per-PR cycles.

1. **Claude scopes.** Aisha asks Claude to scope the next PR from the spec.
   Claude returns: files to create/modify, approach, key decisions. Concise —
   just enough for Aisha to implement correctly on the first try.
2. **Aisha builds.** Aisha implements per Claude's scope. Branch off `main`:
   - `feat/<short-name>` — new feature
   - `fix/<short-name>` — bug fix
   - `chore/<short-name>` — tooling, deps, cleanup
   - `docs/<short-name>` — docs only
3. **Claude reviews.** Aisha pushes and asks Claude to review the diff against
   the spec. Claude checks for bugs, edge cases, spec compliance, and test
   coverage.
4. **Aisha fixes.** Aisha applies Claude's review feedback, pushes, and
   re-reviews until approved.
5. **Aisha merges.** Once Claude approves and suite is green, squash-merge
   and delete the branch.
6. **Repeat.** Back to step 1 for the next PR in the series.

## Commit messages

- Imperative subject line ("Add projection adapter"), ~50 chars.
- Body explains **why**, not just what.
- Claude Code commits include the trailer:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

## Before requesting review

- Backend: run the tests and make sure the app still boots
  (`uvicorn backend.api.main:app`).
- Frontend: `npm run lint` and `npm run build` pass.
- No secrets in the diff. `.env` is gitignored; never commit credentials or
  ESPN cookies.

## Exceptions

Patrick, as repo owner, may push directly in a genuine emergency (e.g. a hotfix
to a broken `main`). It's the exception, not the habit — everything else goes
through review.

## Cross-agent handoffs

Aisha and Claude work in a cost-efficient split:
- **Claude (opus) does the expensive thinking:** scope (what to build, approach,
  decisions) and review (bugs, edge cases, spec compliance).
- **Aisha does the cheap implementation:** reading files, writing code, running
  tests, pushing branches.

The per-PR cycle: Aisha asks Claude for scope → Aisha builds → Aisha asks
Claude for review → Aisha fixes → next PR.

- **Read the spec first.** Every feature has an approved spec in `docs/specs/`.
  The spec is the single source of truth. Do not implement from memory or from
  conversation history — read the file.
- **Pull `main` before starting.** The latest state is on `origin/main`.
  Check `git log --oneline -5` to see what landed since the spec was written.
- **Small PRs, clear commits.** Each PR does one thing. Commit messages describe
  what changed and why. The next agent should understand your commit from the
  message alone.
- **Write the test that would have caught your bug.** If you find a gap in test
  coverage during implementation, add the test before fixing the code.
- **Don't guess on ambiguity.** If the spec doesn't cover a decision you need to
  make, add a comment to the spec with the open question and flag it in your PR
  description. Aisha or Patrick will resolve it.
- **`docs/specs/` is the handoff surface.** When a review closes an open question
  or a decision changes, update the spec. The spec is what the next agent reads.
