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
