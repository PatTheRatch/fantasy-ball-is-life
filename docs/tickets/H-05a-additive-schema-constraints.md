# H-05a · Additive schema constraints

**Status:** NEXT (assigned) · **Depends on:** nothing · **PR into:** `v2`
**Branch:** `fix/h-05a-schema-constraints`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md) §Slice 1 hardening
**Source:** [`research/REDTEAM_TRIAGE.md`](../v2/research/REDTEAM_TRIAGE.md) §H-05
**Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

> **H-05 is split into three.** It was seven constraint families at three very
> different risk levels, which is not one bite.
> **H-05a (this)** — four purely additive constraints. Low risk, one migration.
> **H-05b** — cross-league composite keys on `matchups` and
> `fantasy_team_seasons`. Structural: adds parent unique keys and rewrites
> child FKs.
> **H-05c** — the polymorphic `identity_links.fcp_entity_id`. Not a constraint
> bite at all; it needs a design decision first (see the backlog entry).

---

## What this bite adds

Four constraints behind guarantees the design already states in prose. All
additive — no column changes, no FK rewrites, no data migration.

### 1 · Name-only provider identities must be unique

`uq_provider_identities_provider_entity` is
`(provider_id, entity_kind, provider_entity_id)`. Postgres treats NULLs as
distinct, and the table explicitly permits a NULL `provider_entity_id` with a
`raw_name` (`ck_provider_identities_id_or_name`). So name-only sources — BBM,
Hashtag — have **no** uniqueness at all, and two concurrent resolutions fork one
external identity into two durable ones.

Add a partial unique index:

```sql
create unique index uq_provider_identities_name_only
  on provider_identities (provider_id, entity_kind, raw_name)
  where provider_entity_id is null;
```

This is meaningful because `raw_name` already stores the **normalised** form —
`resolution.py` sets `raw_name=needle` deliberately, commenting that the
normalised form is the stable key for name-only sources.

### 2 · One open review item per identity

`identity_review_open_idx` is on `(status, created_at) WHERE status='open'` and
is **not unique**, so `resolve_and_link`'s check-then-insert is idempotent only
without concurrency — despite its docstring promising re-ingest "doesn't
inflate the open queue."

**Add** a second partial unique index; do not modify the existing one, which
serves queue *listing* and is still wanted:

```sql
create unique index uq_identity_review_open_per_identity
  on identity_review_queue (provider_identity_id)
  where status = 'open';
```

### 3 · Confidence is a probability

`identity_links.confidence numeric(4,3) NOT NULL` accepts `9.999`. Add
`ck_identity_links_confidence_range`: `confidence >= 0 AND confidence <= 1`.

### 4 · Finality and its timestamp agree

`matchup_periods.status` and `finalized_at` are independent, so a period can be
`final` with no record of when. Add:

```sql
check ((status = 'final') = (finalized_at is not null))
```

Stated as an equivalence, not an implication — a `finalized_at` on a
`scheduled` period is equally wrong and equally worth catching.

## The part that is not just a migration

**Constraints 1 and 2 change a failure mode, they do not remove it.** Today a
concurrent double-insert silently creates two rows. With the index it raises
`IntegrityError`. That is strictly better — corruption becomes a crash — but a
crash is not the desired end state, and shipping the index alone converts a
data bug into an availability bug.

So `IdentityResolutionService` must handle the conflict: attempt the insert
inside `session.begin_nested()` (a SAVEPOINT), and on `IntegrityError` roll back
to the savepoint and re-read the row the other transaction won. Without the
savepoint the whole session is poisoned and the surrounding run dies anyway.

That is the get-or-create pattern the check-then-insert was reaching for; the
index is what makes it correct.

## Files

- `migrations/versions/0009_schema_constraints.py` — all four, plus a
  `downgrade()` that drops them. **Migrations must apply *and* roll back in CI**
  (S1-04's standing rule).
- `backend/models/crosswalk.py`, `backend/models/fantasy.py` — mirror the
  constraints in `__table_args__`. The models and migrations must agree;
  `tests/platform/test_models_metadata.py` exists to catch drift.
- `backend/services/resolution.py` — the savepoint/retry described above.

## The tests you will have to fix, and why that is the point

Four sites seed `status="final"` on a `MatchupPeriod` with no `finalized_at`
(`tests/services/test_matchups_sync_postgres.py:127`,
`tests/api/test_periods_route.py:190,222,230`, and any helper they share). The
new constraint will fail them.

**Fix the seeds, do not weaken the constraint.** Those failures are the
constraint proving it bites, and they are the cheapest possible demonstration
that finality now carries its timestamp.

## Tests

Every constraint needs a test that the database *rejects* the bad row — not
that the application avoids writing it. These are Postgres tests; SQLite will
not enforce partial indexes the same way.

1. Two name-only identities with the same `(provider_id, entity_kind, raw_name)`
   → second insert rejected. A third with a non-null `provider_entity_id` and
   the same name → **accepted** (the index is partial; this is the guard against
   writing it too broadly).
2. Two open queue rows for one identity → rejected. A second row for the same
   identity with `status='resolved'` → accepted.
3. `confidence = 1.5` and `confidence = -0.1` → rejected; `0` and `1` →
   accepted (boundaries inclusive).
4. `status='final'` with null `finalized_at` → rejected. `status='scheduled'`
   with a non-null `finalized_at` → **also** rejected (the equivalence, not just
   the implication).
5. Concurrent resolution of the same unresolved identity: both transactions
   complete, one row exists, neither call raises. This is the savepoint test and
   the reason this bite is not migration-only.
6. Migration round-trip (upgrade → downgrade → upgrade) stays green.

## Acceptance criteria

- [ ] All four constraints exist and are enforced by the database.
- [ ] Concurrent identity resolution converges on one row without raising.
- [ ] Models and migrations agree; metadata drift test passes.
- [ ] `pytest && ruff check backend tests && mypy` clean; migration applies and
      rolls back.
- [ ] No API change — `openapi.json` must not move.

## Data model / API impact

One additive migration. No wire change.

## Rollback

`downgrade()` drops all four. Nothing depends on them existing.

## Out of scope

- **H-05b** — cross-league composite keys. Confirmed on both `matchups`
  (four independent FKs) and `fantasy_team_seasons` (a League-A franchise can
  bind to a League-B season). Structural, and it rewrites FKs — separate bite.
- **H-05c** — polymorphic `fcp_entity_id`. Needs a design decision, not a
  constraint.
- `H-06`, `H-07`, `H-09`, `H-10`, `S1-11d`.

## Notes for review

Claude will check: that indexes 1 and 2 are *partial* (a non-partial unique
index on `raw_name` would reject legitimate provider-id-bearing duplicates, and
test 1's third case catches that), that constraint 4 is an equivalence rather
than an implication, that the savepoint is a real `begin_nested` rather than a
bare try/except that poisons the session, that the seed fixes did not weaken
what they seed, and that `downgrade()` actually drops everything `upgrade()`
adds.
