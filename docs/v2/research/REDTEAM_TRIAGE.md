# Red-team triage — data layer, 22 August 2026

**Source:** ChatGPT with repo access, red-teaming the ingestion/schema design
against the shipped Slice 1 implementation. 26 findings.

**This document is the verdict, not the report.** Every finding below was
checked against the code at `e59614f`. Verdicts are mine; where I could not
verify, I say so rather than passing the claim through.

**Headline:** the report is strong. Most findings are real. But its severity
ranking is wrong at the top — two of its three "criticals" are unbuilt work or
latent-not-live, while the finding it rated "major" (#21) is the most serious
thing in the report, because it violates a stated non-negotiable and is
currently corrupting standings.

---

## Act on these first

### 1. Missing stats become real ties (report #21) — CONFIRMED, most serious

`domain/categories.py:71-88`. `compare()` returns `TIE, TIE` when either side is
`None`/NaN, and the docstring rationalises it. `services/matchups.py` persists
that as `result='tie'`, and `standings_read` counts every stored `'tie'` into
`category_ties`.

The code correctly avoids V1's null→zero bug and then commits a subtler version
of the same error: **null→tie**. A stored tie from a missing stat is
byte-identical to a genuine 100-100 tie. That is precisely the non-negotiable in
charter §10: *"The absence of a result must never be indistinguishable from a
result, and a computation that ran on partial inputs must say which inputs were
missing."*

The fix is smaller than it looks: `matchup_category_results.result` is **already
nullable** (`0008_matchups.py`). The schema anticipated unknown; only the domain
collapses it. Return an explicit unknown from `compare()`, persist `NULL`, and
make the standings fold exclude unknown categories and mark the matchup partial.

### 2. Exact-name auto-link ignores a contradicting birthdate (report #13, #26) — CONFIRMED

`services/resolution.py:124-135`. When a birthdate is present but no candidate
matches name+DOB, the ladder **falls through** to exact-name and auto-links at
0.850 on a unique name — even when that candidate's birthdate actively
contradicts the provider's.

Provider "Marcus Williams, b. 1999-01-01" auto-links to the only "marcus
williams" in the pool, born 1995-12-03. That is confidently wrong where the
design demands unknown (charter D18), and `tests/services/test_resolution.py`
covers matching-DOB and absent-DOB but never the conflicting case — which is
exactly why it shipped.

Fix: if both sides have a birthdate and they disagree, that candidate is a
conflict, not a match. Queue it.

### 3. Failed runs stay `running` forever (report #8) — CONFIRMED

`services/matchups.py:162-209`. `start_run()` opens the run; `finish_run(...,
"succeeded")` is only reached on the happy path. There is no `try/except/finally`.
An adapter timeout, an unresolved team (`raise MatchupSyncError`), or a
constraint failure leaves the run `running` permanently.

`finish_run` supports `failed` and `partial`, but nothing structurally forces a
caller to use them — so D28's "job outcomes are queryable data" is false for
every failure path. Fix: a run-lifecycle context manager that guarantees a
terminal status on exit.

### 4. Matchups are stamped `final` with no completeness check (report #22) — CONFIRMED

`services/matchups.py:297,323` hardcodes `status="final"` on every matchup
regardless of how many of the season's scoring categories the payload actually
contained. Combined with #1, a payload missing six of nine categories yields a
"final" matchup, plausible standings, and a `succeeded` run.

---

## Confirmed, structural — fix before Slice 2 builds on them

| # | Finding | Verified at |
|---|---|---|
| 9 | **D26's tenancy guarantee is false for league repos.** `LeagueScopedRepository` exists in `repos/base.py:37` and is used only by `UserRepository`. `MatchupRepository` and `LeagueSeasonRepository` take a bare `Session`. The standings route is protected by `require_league_member`, so there is no live hole — but the *structural* guarantee the charter claims is absent, and the next worker or route gets no protection. | `repos/matchups.py:30,96`; `repos/base.py` |
| 10 | **Route policy is a label, not enforcement.** `declare_policy` only does `setattr`; the matrix test asserts the attribute exists and nothing more. A route can declare `LEAGUE_SCOPED`, skip `require_league_member`, construct an unscoped repo, and pass CI. | `api/policy.py:33-36`; `tests/api/test_route_policy_matrix.py:39-54` |
| 11 | **Cross-league matchup rows are constructible.** Four independent FKs; nothing ties `matchup_period_id` and the two team-season ids to the claimed `league_season_id`. All FKs pass on a row mixing three leagues. | `0008_matchups.py:57-79` |
| 2 | **No finality transition.** `matchup_periods.status` and `finalized_at` are independent; the only check is `end_date >= start_date`. Worse than reported: **nothing in the codebase sets `status='final'` at all** — the only `status="final"` writes are on `Matchup`, not `MatchupPeriod`. Finality is currently an input nobody produces. | `0003_fantasy_core.py:256,267`; `grep` across `backend/` |
| 15 | **Name-only provider identities are not DB-unique.** `uq_provider_identities_provider_entity` is `(provider_id, entity_kind, provider_entity_id)`; Postgres treats NULLs as distinct, and the table explicitly permits `provider_entity_id IS NULL` with a name. Concurrent resolution forks one external identity into two durable ones. | `0007_identity_crosswalk.py:84-91` |
| 16 | **Review-queue idempotency is check-then-insert.** `identity_review_open_idx` is on `(status, created_at)` `WHERE status='open'` and is **not unique**. (The report described the index columns wrongly but reached the right conclusion.) | `0007_identity_crosswalk.py:181-186` |
| 17 | **No confidence bounds; `fcp_entity_id` is polymorphic with no FK.** `confidence numeric(4,3) NOT NULL` accepts 9.999. `identity_links_entity_idx` is a plain index, not a constraint. | `0007_identity_crosswalk.py:104,137` |
| 4 | **Payload dedupe is never wired in.** `find_by_hash` and `latest_for` have **zero callers** anywhere in `backend/` or `tests/`. `record_payload` always inserts. The repo docstring calls `find_by_hash` "the query that lets an unchanged payload skip normalization" — it does not, because nothing calls it. | `repos/ingestion.py:50-71`; `services/ingestion.py:96-110` |
| 5 | **The dedupe key lacks league scope.** `(provider_id, endpoint, content_hash)`, where endpoint is `f"scoreboard/{provider_period_id}"` — an ESPN period id, not unique across leagues. Latent while #4 is unwired; a bug the moment it is wired. | `services/matchups.py:186`; `repos/ingestion.py:61-71` |

---

## Re-severed — the report got these wrong

### #1 "Finality implemented backwards" — real shape, wrong severity (critical → major)

The code is exactly as described: `final_periods()` selects `status == 'final'`
and `sync_league_final_periods()` fetches every one. The docstring at
`repos/matchups.py:70` is self-contradictory — it calls final periods "the only
periods a sync ever touches" while citing "final periods are never refetched."

But the report's failure scenario ("refetches periods 1-10 every 15 minutes")
**cannot happen: there is no scheduler.** No celery, apscheduler, cron or worker
exists anywhere in `backend/`, and `sync_league_final_periods` has no callers
outside tests. This is a backfill service whose name and docstring claim to be
the sync. Real confusion to resolve before a scheduler lands — not a live defect.

### #3 "Replay does not exist" — accurate, but not a divergence (critical → drop, keep one piece)

Correct that no replay service exists and `RawPayloadRepository` cannot load a
run's payload set. But replay was never scoped as a bite. S1-08 was scoped as
the substrate — *"persist before interpret, so replay works"* — and it delivered
that. Unbuilt work is not a design-implementation divergence.

**One piece survives and is worth keeping:** `NORMALIZER_VERSION` is a module
constant, so `start_run()` cannot record a different version for a replay run.
Replay needs it as an argument or registry key. Fix that when replay is built.

### #7 "Concurrent syncs race" — real in shape, latent (major → minor until scheduled)

The `find_live` → mutate → insert sequence has no `FOR UPDATE` or advisory lock,
so the analysis holds. But with no scheduler and no concurrent caller, nothing
can trigger it today. Fix it in the same bite that adds the scheduler — and note
the partial unique index means the failure mode is a crash, not corruption.

### #20 "result_source can claim computed" — real, and understated

Verified worse than reported: **nothing reads `computed_result`, `result_source`
or `provider_result` at all.** `grep` across `services/standings_read.py` and
`api/` returns nothing. Standings folds per-category results only, so the
provider tiebreak is computed, stored, and never consumed. Not a live bug; dead
data with a trap in it for the first consumer that reads `computed_result`.

---

## Not verified

I did not confirm these and am not passing them through as findings: #6
(supersession transaction boundary), #12 (`fantasy_team_seasons` cross-league
binding — plausible given #11, unchecked), #14 (link correction path), #18 (raw
payload immutability), #19 (in-place mutation permissions), #23 (lineage columns
nullable), #24 (`provider_connections` scope combinations).

#12 in particular is likely real by the same pattern as #11 and should be
checked when #11 is fixed.

---

## What this changes

Nothing in the charter or the schema design is wrong. Every confirmed finding is
an **implementation gap against a design that already says the right thing** —
which is the good outcome for a red-team, and is why the docs stay as they are.

Two exceptions worth noting as design-level:

- The **null→tie** collapse (#1 above) is a domain-logic decision that was made
  deliberately, with a rationalising docstring. It needs an explicit unknown in
  the domain vocabulary, not just a code fix.
- **Finality has no producer.** The design treats `status='final'` as the
  linchpin of sync cost and standings correctness, and nothing writes it. That
  is a missing bite, not a bug.
