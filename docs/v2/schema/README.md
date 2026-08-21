# FCP V2 Domain Schema

**Work-plan item 2** from [`FCP_V2_Product_Architecture_Charter.md`](../../FCP_V2_Product_Architecture_Charter.md) §11: turn the conceptual domains into entities, keys, relationships, ownership/scoping rules and historical semantics.

**Status:** design. No migrations written. Nothing here is code yet.

> **Read this file before touching any domain file.** It owns the conventions every domain must follow. A domain file that invents its own ID strategy, timestamp policy or lineage columns is wrong even if it is internally consistent.

---

## How this is organised (and why)

Seven domain files plus this index. The split follows the charter's §5 domain map, which is also the ownership boundary — so two agents working in different files are working on genuinely different things and will not fight over the same tables.

| File | Domain | Depends on | Parallel-safe? |
|---|---|---|---|
| [`01-identity.md`](01-identity.md) | Users, managers, team ownership over time | — | **Foundation** |
| [`02-fantasy.md`](02-fantasy.md) | Leagues, seasons, teams, matchup periods, matchups, rosters, transactions | 01, 03 | **Foundation** |
| [`03-nba.md`](03-nba.md) | NBA seasons, teams, players, games, performances | — | **Foundation** |
| [`04-provider-ingestion.md`](04-provider-ingestion.md) | Connections, raw payloads, ingestion runs, identity crosswalk | 01, 02, 03 | after foundation |
| [`05-projections.md`](05-projections.md) | Sources, sets, rows, adjustments, freezes, preferences | 01, 03 | after foundation |
| [`06-intelligence.md`](06-intelligence.md) | Versioned derived metrics, draft sessions, private manager data, sharing | 01, 02, 05 | after foundation |
| [`07-story.md`](07-story.md) | Timeline, records, rivalries, power rankings, recap facts and editions | 01, 02, 06 | after foundation |

**Dependency rule for parallel work:** 01, 02 and 03 must be settled first — everything else references them. Once they are stable, 04–07 can be worked simultaneously by different agents, because no table in one is referenced by a table in another except through the foundation.

**One exception, called out explicitly:** `06-intelligence.md` defines `metric_definitions`, and `07-story.md` references it for power rankings. That is the only cross-link between non-foundation domains. It is defined in 06; 07 only points at it.

### Conventions for agents working here

- **Do not restate a foundation table in your own file.** Reference it by name. Duplicated definitions drift.
- **If you need a column on a foundation table, say so in your file under "Requests against foundation domains"** rather than editing 01–03 directly. Whoever owns the foundation applies it, once.
- **Every table you define must state its freshness class and its scope** (see below). A table without both is incomplete.
- **Naming is not negotiable.** See the conventions section. Consistency across seven files written by different agents is the whole point of this index.

---

## Conventions

### Identifiers

| Rule | Value |
|---|---|
| Primary key | `id uuid primary key` — UUIDv7, application-generated (time-ordered, so index locality is preserved without exposing row counts) |
| Foreign key naming | `<referenced_table_singular>_id` — e.g. `league_season_id` |
| Natural keys | Expressed as `UNIQUE` constraints, never as the primary key |
| External IDs | **Never** a primary key and never a join key outside `04-provider-ingestion`. Provider identifiers live in the crosswalk. |

Charter Decision 19 is the binding rule here: FCP owns identity; external IDs are mappings.

### Timestamps

- `timestamptz` always. Never `timestamp`. Never a naive datetime anywhere in the stack.
- `created_at timestamptz not null default now()` on every table.
- `updated_at` only on mutable tables. Immutable fact tables must not have one — its presence is a signal the table is mutable, and that signal must stay honest.
- Domain time is distinct from system time. `occurred_at` (when it happened in the world), `observed_at` (when we saw it), `as_of` (what instant a snapshot describes), `computed_at` (when we derived it). Do not collapse these into `created_at`.

### Naming

- `snake_case`; plural table names; singular column names.
- Booleans read as assertions: `is_active`, `has_playoffs`.
- Enum-ish columns end in a noun, not `_type` where a better word exists: `status`, `role`, `direction`, `kind`.
- Junction tables are `<a>_<b>` in alphabetical order unless one clearly owns the other.

### Enums vs lookup tables

| Use | When |
|---|---|
| Postgres native `enum` | Closed set that changes only with a code change — `provider_key`, `member_role`, `match_method` |
| Lookup table | Set that grows with data or configuration — **scoring categories**, transaction types, slot codes |

**Scoring categories must be a lookup table**, per charter Decision 11: the product launches on 9-cat H2H but the schema must not hardcode exactly nine categories forever.

### Scope — every table declares one

Every table is exactly one of these, and states it in its definition. **No table mixes shared and private rows.**

| Scope | Carries | Meaning |
|---|---|---|
| `global` | — | Platform-wide reference data (NBA players, games, categories) |
| `league` | `league_id` | Persists across seasons for one league |
| `league_season` | `league_season_id` | Belongs to one league's one season |
| `manager` | `manager_id` | **Private.** Visible only to that manager and their co-managers |
| `user` | `user_id` | **Private.** Account-level, not league-scoped |

This is charter Decision 12 and non-negotiable #1 ("no silent cross-league or cross-manager state leakage") expressed structurally. The repository layer keys off this column; a table with an ambiguous scope cannot be safely queried.

### Freshness — every table declares one

Charter §6 and non-negotiable "no hardcoded season calendars" both depend on freshness being explicit in the model rather than implied by which code path wrote the row.

| Class | Meaning | Refetch policy |
|---|---|---|
| `reference` | Slowly-changing truth (NBA teams, categories) | Occasional |
| `synced` | Mirrors current provider state | Every sync cycle |
| `event` | Append-only record of something that happened | Never rewritten |
| `snapshot` | What the world looked like at an instant | Never rewritten |
| `final` | Historical fact, closed | **Never refetched** |
| `derived` | Computed from other tables | Recomputed on demand or on input change |

### Events vs snapshots

Charter Decision 20 makes both permanent and first-class. The distinction is enforced by naming:

- `*_events` — append-only, has `occurred_at`, describes a change. Never updated.
- `*_snapshots` — has `as_of`, describes complete state at an instant. Never updated.

A table that would need both is two tables.

### Lineage — required on every canonical fact

Charter Decision 17 and non-negotiable "no normalization that cannot explain where a canonical fact came from." Every table whose rows are derived from a provider payload carries:

```sql
ingestion_run_id    uuid  not null references ingestion_runs(id)
observed_at         timestamptz not null      -- when the source reported it
normalizer_version  text not null             -- which parser produced this row
superseded_by_id    uuid null references <same table>(id)
superseded_at       timestamptz null
```

### Supersession, not mutation

Charter §6, "History is immutable by default." Corrections **supersede** rather than overwrite:

- Never `UPDATE` a canonical fact and never `DELETE` one.
- Write the corrected row, then set `superseded_by_id` / `superseded_at` on the old one.
- Reads filter `where superseded_at is null` unless deliberately reading history.
- The fact that an earlier interpretation existed is itself preserved.

### Versioned derived metrics

Charter Decision 21. Any table holding a computed result references the definition that produced it:

```sql
metric_definition_id  uuid not null references metric_definitions(id)
```

`metric_definitions` is keyed `(key, version)`. A methodology change creates a new version; historical results stay attributable to the version that produced them and remain reproducible. Defined in [`06-intelligence.md`](06-intelligence.md).

### No silent degradation

Charter Decision 28 and §10. **Every derived table carries an outcome, not just a value:**

```sql
status  computation_status not null   -- 'ok' | 'partial' | 'insufficient_data' | 'failed'
reason  text null                     -- required when status <> 'ok'
inputs  jsonb null                    -- what was actually available
```

A missing row and a row that says "could not compute, here is why" are different things, and the second is almost always what we want. A computation that ran on partial inputs records which inputs were missing.

### Migrations

- Alembic. One concern per migration. Forward-compatible across one release.
- Additive by default: add column → backfill → switch reads → drop old, across separate deploys.
- Every migration must be applied *and rolled back* in CI.
- No data migration from V1 (charter Decision 25 — V2 starts empty).

---

## Cross-domain reference contract

The only foreign keys permitted **into** foundation domains from elsewhere:

```
→ users(id)                   user-scoped private data, audit columns
→ managers(id)                manager-scoped private data, ownership
→ leagues(id)                 league-persistent data
→ league_seasons(id)          season-scoped data
→ fantasy_team_seasons(id)    per-season team references
→ matchup_periods(id)         anything week-shaped
→ players(id)                 anything player-shaped — ALWAYS this, never a name
→ nba_seasons(id)             season anchoring
→ nba_games(id)               game-level references
```

**`players(id)` is the one to internalise.** Charter non-negotiable: *no player identity strategy based primarily on fuzzy names.* If a table in any domain joins on a name string, it is wrong. Name resolution happens once, at ingest, in `04-provider-ingestion`, and produces a `player_id`.

---

## Open items for the schema phase

Tracked here so they do not get lost in individual domain files.

1. **Matchup-period date mapping.** Charter Decision 15 says periods are imported from providers, not hand-maintained. ESPN does not cleanly expose period→date ranges; current FCP derives them from daily scoring periods. Verify against a live ESPN league early — this is the kind of detail that invalidates a schema late. Owner: `04-provider-ingestion`.
2. **Ratio-category representation.** FG% and FT% must be stored as makes and attempts, never as a bare percentage, so aggregation is correct. `categories` needs to express which underlying stats a ratio category is built from. Owner: `02-fantasy`.
3. **Raw payload storage location.** Charter Decision 23 allows object storage. Recommendation: start with `jsonb` in Postgres so ingestion is transactional with the run that produced it; move to object storage behind the same `raw_payloads` row when volume justifies it, keeping `storage_ref` nullable from day one. Owner: `04-provider-ingestion`.
4. **Lineup granularity.** Charter Decision 10 wants lineup state "when obtainable." Daily started/benched is obtainable from ESPN at some cost. Decide whether V2 captures it from the first sync — it cannot be backfilled later. Owner: `02-fantasy`.
5. **Unresolved-identity workflow.** Decision 18 queues ambiguous matches rather than guessing. Someone has to work that queue. Decide whether slice 1 ships the queue table only or the review UI too. Owner: `04-provider-ingestion`.

---

## Slice 1 scope

Charter §11.6 and Decision 26. The first vertical slice proves the architecture end to end:

> user → manager → league → league_season → ESPN sync → canonical teams/players/matchup periods → one shared league page

Tables required for slice 1, and no others:

```
01  users · managers · manager_user_links
    fantasy_team_seasons · fantasy_team_season_managers
02  leagues · league_seasons · categories · league_season_categories
    fantasy_teams · matchup_periods · matchups · matchup_category_results
03  nba_seasons · nba_teams · players
04  providers · provider_connections · ingestion_runs · raw_payloads
    provider_identities · identity_links · identity_review_queue
```

Everything in 05, 06 and 07 is deliberately out of slice 1. Authorization and scoping are **in** slice 1 (Decision 26), not deferred.

---

*Design phase. Current as of charter `8aa3ac0`.*
