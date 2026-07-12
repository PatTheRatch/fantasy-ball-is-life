# Contributing

How work gets from an idea to `main` on this project. Roles are defined in
[`docs/AISHA_OPERATING_MANUAL.md`](docs/AISHA_OPERATING_MANUAL.md); this doc is
the mechanics.

## The rule

**No direct commits to `main`.** Every change lands through a pull request that
Aisha (lead systems engineer) has approved. `main` stays deployable at all times.

## The flow

1. **Spec first.** A feature needs a spec that meets the six-part definition of
   done (user story, acceptance criteria, data model impact, API/UI impact, test
   plan, rollback/failure) before code is written. Specs live in `docs/specs/`.
   Major architecture, product, database, payment, auth, or security decisions
   need Aisha's or Patrick's sign-off on the spec first — see the operating manual.
2. **Branch.** Cut a branch from `main`:
   - `feat/<short-name>` — new feature
   - `fix/<short-name>` — bug fix
   - `chore/<short-name>` — tooling, deps, cleanup
   - `docs/<short-name>` — docs only
3. **Build small.** Keep the branch focused on one spec. Smallest paid-worthy
   version first — skip "cool" extras that don't support subscription value.
4. **Open a PR** into `main`. The description must:
   - link the spec it implements,
   - check off the six definition-of-done parts (or say why one is N/A),
   - note how it was tested.
5. **Review.** Aisha reviews. At least **one approving review** is required to
   merge. Implementation engineers (Claude Code) do not self-merge; they don't
   make major architectural/product/DB/payment/auth/security calls without Aisha
   or Patrick approving in the PR.
6. **Merge.** Squash-merge once approved and green. Delete the branch.

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

This project is built by multiple agents (Aisha, Claude, Codex, Cursor).
When you pick up where another agent left off:

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
