# D-04 · Local runbook — make it actually runnable

**Status:** NEXT (assigned) · **Depends on:** D-03 (`f75797a`) · **PR into:** `v2`
**Branch:** `docs/d-04-local-runbook`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md) §Demo path
**Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

---

## Why this exists

The demo path is code-complete. **Nobody has ever run this application outside
CI**, and there is no document anywhere that gets a person from a checkout to a
running app. Patrick should not be the one discovering what breaks.

A survey of the repo turned up four concrete gaps, and they are the shape of
what else is probably there:

1. **The Supabase auth wiring for V2 has never been done.**
   `platform/settings.py` requires `SUPABASE_JWT_ISSUER`,
   `SUPABASE_JWT_AUDIENCE` and `SUPABASE_JWKS_URL`. Those three names appear
   **nowhere else in the repo** — not in `.env.example`, not in CI, not in any
   doc. V1's `docs/DEPLOY.md` documents a Supabase project under entirely
   different variable names (`SUPABASE_URL`, `SUPABASE_ANON_KEY`). Nothing
   connects the two.
2. **`.env.example` is incomplete.** It covers D-03's four variables and none of
   the three above, so a person following it gets a backend that cannot start.
3. **`CONTRIBUTING.md`'s run command is stale.** It says
   `uvicorn backend.api.main:app`. There is no `backend/api/main.py` — the app
   lives in `backend/api/app.py`, and it exposes `create_app()` with no
   module-level `app`, so the correct invocation needs `--factory`. Anyone
   following the contributing guide fails at the first command.
4. **There is no local Postgres story.** `docker-compose.yml` is V1's. Tests use
   a CI service container. Nothing tells a developer how to get a database.

## The deliverable

`docs/v2/RUNBOOK.md` — clone to running app, **written by doing it**, not by
reading code.

Do it on a clean checkout in a fresh directory. Every command verbatim, in
order, with its expected output. Where a step fails, either fix the cause in
this PR (if it is a repo defect, like #2 and #3 above) or document the manual
step precisely (if it is genuinely external, like creating a Supabase project).

The test of this document is that someone who has never seen the repo can
follow it without asking a question. If you find yourself writing "you may need
to…", that is a gap to close, not a sentence to ship.

## Cover, in order

**Prerequisites** — Python version, Node version, Postgres. Pin what the repo
actually needs, not what happens to be installed.

**Database** — how to get a local Postgres and create the database. If a
`docker compose` service is the cleanest answer, add one for V2 rather than
documenting a manual `createdb` dance; if V1's compose file is in the way, say
so and leave it alone.

**Migrations** — the exact `alembic upgrade head` invocation and what
configuration it reads. Confirm a fresh database reaches head cleanly.

**Backend** — the **correct** uvicorn command, and fix `CONTRIBUTING.md` while
you are there. Verify `GET /health` responds.

**Auth — the unknown, and the part to be most careful with.**
Establish what a V2 developer needs for `SUPABASE_JWT_ISSUER`,
`SUPABASE_JWT_AUDIENCE`, `SUPABASE_JWKS_URL`, and how to obtain a JWT that
`platform/auth.py` will accept. Document how to get a token for a dev user, and
how signing in once creates the `users` row that D-03's `--claim-email`
requires.

**Do not weaken auth to make this easier.** No mock verifier, no bypass flag, no
"skip JWKS in dev" branch. S1-11a's shim carries a real token *precisely* so the
backend still verifies end to end, and that property is worth more than a
convenient runbook. If a real token cannot be obtained without a decision only
Patrick can make, **stop and say so** — that is a finding, not a failure.

**Frontend** — `npm install`, `.env.local` from `frontend/.env.example`,
`npm run dev`, and what `/` should show once a token is set.

**The sync** — D-03's invocation, including the two-step discovery (run without
`--claim-team` to list teams, then re-run with one). Mark clearly that the ESPN
credentials are Patrick's and this is the one step you cannot execute
end-to-end yourself.

**Troubleshooting** — every failure you actually hit, with its cause and fix.
This section is the most valuable part of the document and it can only be
written by someone who hit them.

## Scope boundary

You can verify everything except the real ESPN call — you have no league and no
cookies, and **you must not ask for them**. Verify that path with a fake or
recorded adapter, exactly as D-03's tests do, and mark the live step as
Patrick-supplied.

## Fixes that belong in this PR

Repo defects the runbook exposes, where the fix is small and obvious:

- `.env.example` gains the three `SUPABASE_*` variables (names and comments,
  **no values**).
- `CONTRIBUTING.md`'s stale run command.
- A V2 `docker compose` Postgres service, if that is the cleanest database
  answer.

Anything larger — a missing endpoint, a real auth gap, a config redesign — is a
**finding to report, not to fix here**. Say so in the PR and it gets its own
bite. A runbook PR that quietly grows a feature is how a documentation task
becomes unreviewable.

## Acceptance criteria

- [ ] `docs/v2/RUNBOOK.md` takes a clean checkout to a running app.
- [ ] Every command was actually executed, not inferred from source.
- [ ] The auth path is either documented end to end, or blocked with a precise
      statement of what decision is needed and why.
- [ ] No auth weakening anywhere in the diff.
- [ ] The three repo defects above are fixed.
- [ ] Failures encountered are captured in Troubleshooting.
- [ ] `pytest && ruff check backend tests scripts && mypy` still clean; no
      migration unless the compose service needs one (it should not).

## Data model / API impact

None. Docs, `.env.example`, and possibly a compose service.

## Rollback

Documentation and configuration; trivially revertible.

## Out of scope

`H-05b`/`c`, `H-06`, `H-08`, `H-09`, `H-10`, `S1-11d`, deployment of any kind
(this is local only — `deploy.yml` remains scoped to `main`), and the open
question #6 probe.

## Notes for review

Claude will check: that the runbook reads as executed rather than inferred
(expected output is the tell), that no auth verification was weakened or
bypassed, that the ESPN step is clearly marked as the one requiring Patrick's
credentials, that findings too large for this PR were reported rather than
absorbed, and that `CONTRIBUTING.md` and `.env.example` now match reality.
