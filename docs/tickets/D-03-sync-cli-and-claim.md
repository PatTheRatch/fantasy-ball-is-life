# D-03 · Sync CLI + claim

**Status:** NEXT (assigned) · **Depends on:** D-01 (`f89fda1`), D-02 (`087ea08`) · **PR into:** `v2`
**Branch:** `feat/d-03-sync-cli`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md) §Demo path
**Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

---

## What this is

The operator entry point that ties D-01 and D-02 together and puts Patrick's
real league on screen. After this: `npm run dev`, a dev token, and a URL.

D-02 folded matchup persistence into `finalize_period`, so the sequence is
shorter than the backlog originally described — **bootstrap → finalize →
claim**, not bootstrap → finalize → separate sync.

This is the first bite with a real `main()`. `scripts/` is not covered by the
architecture tests (they constrain `backend.domain` and the routers), and an
operator script importing services and repositories directly is correct — it is
a composition root, not a layer.

## Credentials — get this right first

`espn_s2` and `SWID` are live session credentials for Patrick's ESPN account.
They are not config.

**Read them from the environment only. Never from `argv`.** Arguments are
visible in `ps`, land in shell history, and get captured by any process
supervisor or CI log. `backend/platform/settings.py` already has the
`_require(name)` pattern; follow it.

```
FCP_ESPN_SWID       required
FCP_ESPN_ESPN_S2    required
FCP_ESPN_LEAGUE_ID  required   (an id, not a secret, but it belongs with them)
DATABASE_URL        required   (settings.database_url() already reads it)
```

`.env` is already gitignored (`.gitignore:2`). Add the names — **and no
values** — to a `.env.example`.

**Never print, log, or interpolate a credential into an error message.** A
failed ESPN call must report the status and the endpoint, not the cookie. If a
credential is missing, say which env var is unset — never echo what was found.

## The claim, and the trap inside it

`manager_user_links` is the row that turns a bootstrapped league into one
Patrick can actually read — without it, `require_league_member` 403s him off his
own league. D-01 deliberately left it undone because linking a person to a
manager is an auditable act, not an ingestion side effect (charter D13).

**The CLI must find an existing user. It must never create one.**

`users.auth_subject` is `NOT NULL UNIQUE` and holds the identity provider's
subject claim. A CLI-created user would need an invented `auth_subject`, which
would never match Patrick's real JWT `sub` — so his first real sign-in would
silently create a *second* user, and the claim would be attached to the wrong
one. The league would still 403, and the cause would be invisible.

So: `--claim-email <address>` looks up `users` by email. If there is no match,
**fail with a message that says what to do**: sign in once through the
frontend so `get_current_user`'s get-or-create makes the row, then re-run.

Team selection: `--claim-team <provider_team_id>`. If it is omitted or does not
match, print the league's teams — provider id, name, owner manager — and exit
non-zero. That makes the CLI self-describing instead of requiring a database
query to use it.

The link itself: get-or-create `manager_user_links(manager_id, user_id,
is_primary=true)` against the team-season's `owner`-role manager. Note the
partial unique index allows only one primary per manager, and
`(manager_id, user_id)` is unique — so re-running must be a no-op, not a
crash.

## What the CLI does

```
scripts/sync_league.py --season 2026 [--claim-email X] [--claim-team Y]
                       [--grace-hours 48] [--skip-finalize]

  1. bootstrap        LeagueBootstrapService.bootstrap(conn, season_year)
  2. finalize         MatchupSyncService.finalize_eligible_periods(...)
  3. claim            (only when --claim-email is given)
  4. print a summary
```

Each step is idempotent by construction — D-01 bootstraps zero-write on re-run,
D-02 skips already-final periods, the claim is get-or-create. **Re-running the
whole command must be safe**, because it will be run repeatedly while the demo
is set up.

### The summary is the deliverable

Print, at minimum:

```
League      <name>  (season 2026)
Teams       12 created, 0 updated
Periods     22 total · 20 finalized · 2 not yet eligible
Matchups    140 persisted · 3 with unknown categories
Identities  0 queued for review
Runs        league_bootstrap succeeded · matchups partial
League URL  http://localhost:5173/leagues/<league_season_id>
```

**The URL line matters.** S1-11d is not built, so there is no way to reach a
league except by pasting its UUID — the CLI is how Patrick gets it. Print the
`league_season_id` prominently or the demo stalls on "which UUID?".

Surface run statuses honestly: if a run came back `partial`, say so and say
why (unresolved categories, unknown stats). A CLI that prints a clean summary
over a partial run is the silent-degradation failure in a new costume.

## Rate limiting

One settings call, one teams, one periods, and one scoreboard per eligible
period — roughly 23 requests for a full season. Well under anything observed as
risky, but keep it **sequential, with no concurrency**, per
[`research/ESPN_ROSTER_API.md`](../v2/research/ESPN_ROSTER_API.md) §4: there is
no published quota, and the right posture is to make the integration cheap by
construction.

## Tests

A CLI is still testable, and the parts worth testing are the ones that will
bite in the dark:

- Missing credential env var → clear error naming the variable, and **the error
  does not contain any credential value**.
- `--claim-email` with no matching user → non-zero exit and the "sign in once
  first" message; **no user row is created** (assert the count).
- Claim creates exactly one `manager_user_links` row; running twice creates no
  second row and does not raise.
- After claim, `LeagueMembershipRepository.is_member` returns true for that
  user and league season — the same assertion D-01 used, now end to end.
- `--claim-team` omitted → teams are listed and exit is non-zero.
- Argument parsing does not accept credentials (a `--espn-s2` flag must not
  exist — assert the parser rejects it, so nobody adds one later for
  convenience).

Use a fake adapter for these; **no test may make a real ESPN call.**

## Acceptance criteria

- [ ] `bootstrap → finalize → claim` runs end to end against a fake adapter.
- [ ] Credentials come only from the environment; none reachable via `argv`;
      none appear in output or errors.
- [ ] No user is ever created by the CLI.
- [ ] Re-running the whole command changes nothing.
- [ ] The summary prints the league URL and honest run statuses.
- [ ] `pytest && ruff check backend tests scripts && mypy` clean; no migration;
      `openapi.json` untouched.

## Data model / API impact

None. No schema change, no endpoint. `provider_connections` stays unused —
`EspnConnection` is still the plain value object its docstring describes, and
encrypted credential storage is a later bite, not this one.

## Rollback

New script plus a `.env.example`; nothing else depends on it.

## Correcting something I said earlier

I told Patrick this bite "doubles as the live check for open question #6."
**That was wrong, and the backlog entry inherits the error.**

Open question #6 asks whether historical lineups are recoverable — via
`rosterForCurrentScoringPeriod` in the historical scoreboard payload, or by
replaying `mTransactions2` `FUTURE_ROSTER` moves. This CLI touches settings,
teams, periods and scoreboards. **It exercises none of those paths**, so it
cannot answer the question.

What it does prove is that the whole pipeline works against a real league,
which is worth having on its own. Open question #6 still needs its own small
probe — an S1-03-shaped bite — and running this CLI successfully is a good
moment to schedule it, not a substitute for it.

Fix the backlog entry as part of this ticket's landing.

## Out of scope

- A scheduler or any recurring job. This is invoked by hand.
- `provider_connections` rows / encrypted credential storage.
- Any HTTP endpoint or onboarding UI.
- `S1-11d` (which would remove the need to paste a UUID), `H-05b/c`, `H-06`,
  `H-08`, `H-09`, `H-10`.

## Notes for review

Claude will check: that no credential can arrive via `argv` and none appears in
any output path, that the CLI cannot create a user and the test asserts the row
count, that every step is genuinely re-runnable, that the league URL is printed,
that partial runs are reported rather than smoothed over, and that no test can
reach the real ESPN API.
