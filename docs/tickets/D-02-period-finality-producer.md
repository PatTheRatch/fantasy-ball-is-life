# D-02 · Period finality producer

**Status:** NEXT (assigned) · **Depends on:** D-01 (merged, `f89fda1`), H-03, H-05a · **PR into:** `v2`
**Branch:** `feat/d-02-finalize-period`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md) §Demo path · *formerly H-07*
**Source:** [`research/REDTEAM_TRIAGE.md`](../v2/research/REDTEAM_TRIAGE.md) §2
**Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

---

## Why this is the bite that makes the demo work

**Nothing in the codebase writes `matchup_periods.status = 'final'.'** D-01
creates every period as `scheduled`, correctly, because finality is this bite's
job.

Everything downstream reads finality: `StandingsReadService` folds only final
periods, the periods selector offers only final periods, and the whole sync-cost
model rests on "a final period is never refetched." So today, a fully
bootstrapped league with correct data renders **"not synced"** on every screen.
Finality is the linchpin of the design and it is an input nobody produces.

This bite produces it, and it is the last thing between D-03's CLI and Patrick
seeing real standings.

## The rule, defined once, here

A period becomes final when **its end date has passed by a grace margin, and a
last authoritative fetch has been persisted.** Both halves matter: the date makes
it *eligible*, the fetch makes it *true*.

`PROVIDER_INGESTION_DESIGN.md` §Sync scheduling already specifies the trigger —
`finalize_period` | on `end_date` + grace | skips when already `final`. This is
that row, implemented.

**Three things about the rule:**

**The grace margin is not optional and not a magic number.** ESPN posts stat
corrections after games settle; finalizing at midnight on `end_date` freezes a
number that is still moving. Make it a named, documented default — **48 hours**
— passed as a parameter, not a literal buried in a conditional.

**Dates resolve through the league's timezone.** `league_seasons.timezone`
exists precisely for this, and its model comment says every date boundary
resolves through it. "Has `end_date` passed" computed in UTC or server-local is
wrong for any league not in that zone, and wrong by up to a day — which on the
boundary is a whole week's standings. This is the single easiest thing to get
subtly wrong in this bite.

**The read path still never infers finality.** S1-11c was told not to add a
date-based fallback, and that stands. The distinction is the point of this
ticket: the rule lives *here*, in one service, once. Nowhere else may derive
finality from dates.

## Files

### `backend/services/matchups.py` — the transition owner

Add `finalize_period(period, *, connection, adapter)`:

```
fetch scoreboard  →  record raw payload  →  normalize + supersede/persist
                  →  set status='final' AND finalized_at=now()
```

H-05a's constraint `(status='final') = (finalized_at IS NOT NULL)` makes those
last two inseparable — set them in the same statement, and let the constraint be
the thing that guarantees it rather than a convention.

Add `finalize_eligible_periods(*, connection, adapter, grace_hours=48)` as the
league-level driver: load periods, skip anything already `final`, skip anything
not yet eligible, finalize the rest in ordinal order.

### The rename

`sync_league_final_periods` fetches every *already-final* period — a backfill
whose name and docstring claim to be the sync, and the contradiction the
red-team caught. Rename it **`resync_final_periods`**, and make its docstring
say what it is: a repair path for re-reading periods after a normalizer change,
which **must not** change `status`.

**Keep it, do not delete it.** Its Postgres tests are the only proof supersession
works, and trading that coverage for tidiness is a bad deal. Extract the
per-period fetch-normalize-persist into one private method both paths call, so
there is a single implementation of the thing that writes matchups.

## Transaction boundary — commit per period, not per run

**Each period finalizes in its own transaction, committed before the next
starts.**

A season backfill is ~20 sequential ESPN calls and any one of them can flake. If
the whole run is one transaction, a failure at period 15 rolls back the first 14
and the next attempt starts from zero. Committing per period means a failure
leaves periods 1–14 final, period 15 `scheduled`, the run `failed`, and a re-run
resumes exactly where it stopped.

This is compatible with `run_scope`, which commits the run as `running` on entry
specifically so writes inside the body are durable and the `failed` stamp
survives the rollback. Within a single period, the matchup writes and the status
flip must land **together** — a period that is `final` with half its matchups is
the one state that would be genuinely unrecoverable, because finality means it
is never refetched.

## Eligibility rules

| Period | Finalize? |
|---|---|
| already `final` | **skip** — never refetched, that is what finality means |
| `end_date` + grace not yet passed (league tz) | skip, not yet eligible |
| no `provider_period_id` | skip — cannot be fetched (D-01 skips these too) |
| `type='break'` | **finalize** with zero matchups |
| any other type, eligible | finalize |

A break period (All-Star) is genuinely over and has no matchups. Finalize it, and
**do not treat zero matchups as `partial`** — an empty break is complete data,
not missing data. Leaving breaks perpetually `scheduled` puts a permanent hole
in the ordinal sequence that `through_period` reads across.

Missing *categories* within a matchup remain `partial` (H-01's unknowns). That is
a different thing from a period with no matchups, and the run status should
distinguish them.

## Tests

- An eligible period finalizes: matchups persisted, `status='final'`,
  `finalized_at` non-null.
- **A period inside the grace window does not finalize** — the test that pins
  grace as real rather than decorative.
- **Timezone boundary:** a period whose `end_date` has passed in UTC but not in
  the league's timezone does not finalize. This is the trap test; write it
  deliberately.
- An already-final period is not refetched — assert the adapter was **not
  called**, not merely that nothing changed.
- A `break` period finalizes with zero matchups and the run is **not** `partial`.
- A matchup with missing categories finalizes the period and marks the run
  `partial`.
- **Resumability (Postgres):** adapter raises on the 3rd of 5 periods → periods
  1–2 are final and committed, 3–5 are still `scheduled`, run is `failed`, and
  a re-run completes the rest.
- `resync_final_periods` does not change `status` on anything.
- End-to-end: bootstrap (D-01) → finalize → `StandingsReadService.standings()`
  returns a populated table. **This is the test that proves the demo works**, and
  it is worth writing even though it spans two services.

## Acceptance criteria

- [ ] Eligible periods reach `final` with `finalized_at`; ineligible ones do not.
- [ ] Grace and timezone both provably affect eligibility.
- [ ] A final period is never refetched.
- [ ] A mid-run failure is resumable — earlier periods stay final.
- [ ] `resync_final_periods` renamed, repair-only, status untouched.
- [ ] `pytest && ruff check backend tests && mypy` clean; no migration; no API
      change (`openapi.json` must not move).

## Data model / API impact

None. Writes existing columns; no schema change, no wire change.

## Rollback

Service-only. Reverting restores the pre-D-02 state, in which no period is ever
final — worth remembering, because that is a demo-breaking rollback, not a
cosmetic one.

## Out of scope

- **The CLI that calls this** — D-03, along with the manager claim.
- A scheduler. There is still no job runner, and this bite does not add one;
  D-03 invokes it directly.
- `H-05b`, `H-05c`, `H-06`, `H-08`, `H-09`, `H-10`, `S1-11d`.

## Notes for review

Claude will check: that the timezone test exists and would fail under a naive
UTC comparison, that grace is a named parameter rather than a literal, that
already-final periods are proven unfetched by asserting on the adapter, that the
per-period commit is real (the resumability test must show committed work
surviving), that a break's zero matchups do not read as `partial`, and that only
one code path writes `status='final'`.
