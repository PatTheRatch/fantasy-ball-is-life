# 04 · Provider & Ingestion

**Domain:** provider connections, raw evidence, ingestion lineage, and the identity crosswalk.
**Depends on:** 01, 02, 03.
**Charter:** Decisions 5 (multi-provider future), 16 (raw retention), 17 (lineage), 18 (prefer unknown over confidently wrong), 19 (permanent crosswalk), 28 (observability).

> Read [`README.md`](README.md) first. Conventions there are binding.

---

## What this domain is for

Everything external enters FCP here and nowhere else. Charter non-negotiable: *no provider-specific client object as the canonical fantasy domain model.*

The pipeline is deliberately four stages, each durable:

```
fetch  →  raw_payloads      (evidence, never interpreted)
          ingestion_runs    (what ran, when, with which parser)
normalize →  canonical tables in 02 / 03   (with lineage back to the run)
resolve   →  identity_links (which provider record is which FCP entity)
```

**Replay beats patching** (charter §6). A normalization bug is fixed by shipping a new normalizer version and re-running it over stored `raw_payloads` — no refetch, no data loss, and the old interpretation is superseded rather than erased. Current FCP has no equivalent: a mapping bug means refetching from ESPN and hoping the upstream data has not changed.

---

## Tables

### `providers`

**Scope:** `global` · **Freshness:** `reference`

```sql
create type provider_key as enum
  ('espn', 'yahoo', 'sleeper', 'nba', 'kaggle', 'bbm', 'hashtag', 'manual');

create table providers (
  id            uuid primary key,
  key           provider_key not null unique,
  name          text not null,
  kind          text not null,        -- fantasy_platform | stats | projections
  created_at    timestamptz not null default now()
);
```

Yahoo and Sleeper are enum members from day one even though no adapter exists (charter Decision 5). Their presence costs nothing and makes the multi-provider intent visible in the schema rather than aspirational.

### `provider_connections`

**Scope:** `league` for platform connections, `global` for stats sources · **Freshness:** `reference`

```sql
create table provider_connections (
  id                  uuid primary key,
  provider_id         uuid not null references providers(id),
  league_id           uuid null references leagues(id),
  owner_user_id       uuid null references users(id),
  credentials_encrypted bytea null,      -- envelope-encrypted, app-side
  credentials_key_id  text null,         -- which KEK; enables rotation
  status              text not null default 'unverified',  -- unverified|ok|invalid|expired
  last_verified_at    timestamptz null,
  last_error          text null,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);
```

Notes:

- **Credentials are encrypted application-side**, not by a database RPC. Current FCP POSTs the encryption key to Postgres as an RPC parameter on every league resolution — the migration comment claims the key never touches the database, which is self-contradictory, and it costs two extra round trips per request. Here the key never leaves the application.
- `credentials_key_id` exists so rotation is possible without a migration.
- `status` and `last_error` are stored, not logged (charter Decision 28). "This league's ESPN cookies expired" is a fact the product should be able to surface to its owner, not something discovered by reading a stack trace.
- Separate from `league_seasons` so one connection can serve several seasons and so credential ownership is distinct from league identity.

### `ingestion_runs`

**Scope:** `global` · **Freshness:** `event`

```sql
create type run_status as enum ('running', 'succeeded', 'partial', 'failed');

create table ingestion_runs (
  id                  uuid primary key,
  provider_id         uuid not null references providers(id),
  connection_id       uuid null references provider_connections(id),
  league_season_id    uuid null references league_seasons(id),
  kind                text not null,        -- league_settings|matchups|rosters|transactions|nba_stats
  normalizer_version  text not null,
  started_at          timestamptz not null default now(),
  finished_at         timestamptz null,
  status              run_status not null default 'running',
  error               text null,
  stats               jsonb not null default '{}',   -- rows read/written/superseded/queued
  replayed_from_run_id uuid null references ingestion_runs(id),
  created_at          timestamptz not null default now()
);

create index ingestion_runs_league_kind_idx
  on ingestion_runs (league_season_id, kind, started_at desc);
```

Every canonical fact in 02 and 03 carries `ingestion_run_id`, so the provenance of any row is one join away. `status = 'partial'` is a first-class outcome (charter Decision 28): a run that got matchups but not transactions says so, rather than succeeding quietly with half the data.

`replayed_from_run_id` records that this run reinterpreted a previous run's stored payloads rather than fetching fresh.

### `raw_payloads`

**Scope:** `global` · **Freshness:** `event` (immutable evidence)

```sql
create table raw_payloads (
  id                uuid primary key,
  ingestion_run_id  uuid not null references ingestion_runs(id),
  provider_id       uuid not null references providers(id),
  endpoint          text not null,
  request_params    jsonb not null default '{}',
  fetched_at        timestamptz not null,
  http_status       int null,
  content_hash      text not null,         -- sha256, for dedupe and change detection
  payload           jsonb null,            -- inline storage (default)
  storage_ref       text null,             -- object-storage key (large payloads)
  byte_size         int null,
  created_at        timestamptz not null default now(),
  check (payload is not null or storage_ref is not null)
);

create index raw_payloads_run_idx on raw_payloads (ingestion_run_id);
create index raw_payloads_hash_idx on raw_payloads (provider_id, endpoint, content_hash);
```

Charter Decision 16. Three things this buys beyond replay:

- **Free, real test fixtures.** Sanitised payloads become golden-file inputs for mapper tests. Current FCP has one hand-captured fixture (`mtransactions2_sample.json`) produced by a bespoke script.
- **Change detection.** `content_hash` means an unchanged payload skips normalization entirely.
- **Debugging from evidence rather than logs.** "Why did week 7 come out wrong" is answerable a month later.

**Storage decision (README open item 3):** start with `payload jsonb` inline so writes are transactional with the run that produced them. `storage_ref` is nullable from day one so large payloads can move to object storage (charter Decision 23) without a schema change. Do not build the object-storage path until volume justifies it.

### `provider_identities`

**Scope:** `global` · **Freshness:** `synced`

Every distinct external entity FCP has ever seen, before any judgement about what it maps to.

```sql
create type provider_entity_kind as enum ('player', 'team', 'league', 'manager', 'game');

create table provider_identities (
  id                  uuid primary key,
  provider_id         uuid not null references providers(id),
  entity_kind         provider_entity_kind not null,
  provider_entity_id  text null,        -- null for sources with no stable id (BBM exports)
  raw_name            text null,
  raw_attributes      jsonb not null default '{}',   -- team, position, dob — matching evidence
  first_seen_at       timestamptz not null default now(),
  last_seen_at        timestamptz not null default now(),
  unique (provider_id, entity_kind, provider_entity_id),
  check (provider_entity_id is not null or raw_name is not null)
);
```

Note `provider_entity_id` is nullable: a Basketball Monster spreadsheet has names and nothing else. That is exactly the case that must not be silently resolved.

### `identity_links`

**Scope:** `global` · **Freshness:** `reference`

Charter Decision 19 — the permanent crosswalk.

```sql
create type match_method as enum
  ('provider_id', 'nba_anchor', 'exact_name_dob', 'exact_name', 'fuzzy_name', 'manual');

create table identity_links (
  id                    uuid primary key,
  provider_identity_id  uuid not null references provider_identities(id),
  fcp_entity_kind       provider_entity_kind not null,
  fcp_entity_id         uuid not null,          -- players.id, fantasy_team_seasons.id, ...
  match_method          match_method not null,
  confidence            numeric(4,3) not null,  -- 0.000–1.000
  evidence              jsonb not null default '{}',
  verified_by_user_id   uuid null references users(id),
  verified_at           timestamptz null,
  superseded_by_id      uuid null references identity_links(id),
  superseded_at         timestamptz null,
  created_at            timestamptz not null default now()
);

create unique index identity_links_active_idx
  on identity_links (provider_identity_id) where superseded_at is null;

create index identity_links_entity_idx on identity_links (fcp_entity_kind, fcp_entity_id);
```

Notes:

- `fcp_entity_id` is polymorphic by `fcp_entity_kind`, so one crosswalk serves players, teams and managers. The alternative — a link table per entity kind — triples the surface for no gain, since resolution logic is identical.
- **A wrong link is superseded, never deleted.** The fact that we once believed a mapping is itself history, and correcting a player identity retroactively changes derived analytics that should remain explicable.
- `evidence` records *why* — matched dob, matched team, edit distance — so a human reviewing a low-confidence link can judge it without re-deriving.

### `identity_review_queue`

**Scope:** `global` · **Freshness:** `derived`

Charter Decision 18: *"Ambiguous matches are flagged rather than silently fuzzy-matched. Prefer unknown over confidently wrong."*

```sql
create type review_status as enum ('open', 'resolved', 'rejected', 'ignored');

create table identity_review_queue (
  id                    uuid primary key,
  provider_identity_id  uuid not null references provider_identities(id),
  ingestion_run_id      uuid not null references ingestion_runs(id),
  reason                text not null,      -- no_candidate|ambiguous|low_confidence|conflict
  candidates            jsonb not null default '[]',  -- [{fcp_entity_id, score, evidence}]
  status                review_status not null default 'open',
  resolved_link_id      uuid null references identity_links(id),
  resolved_by_user_id   uuid null references users(id),
  resolved_at           timestamptz null,
  created_at            timestamptz not null default now()
);

create index identity_review_open_idx on identity_review_queue (status, created_at)
  where status = 'open';
```

**This table is the single most important behavioural difference from current FCP.**

Today, a name that fails to match is silently dropped from a projection set or an optimizer pool. The numbers still look plausible, so nobody notices — and there are four different fuzzy thresholds (80, 75, 85, 90) across four attachment functions, plus two different `normalize_name` implementations that disagree on hyphenated and suffixed names. A player can therefore resolve in one code path and vanish in another.

In V2 a failed match is a row here, counted on the status page, and blocking nothing.

---

## Resolution policy

One ladder, defined once, used by every ingest. No per-call-site thresholds.

| Order | Method | Confidence | Action |
|---|---|---|---|
| 1 | `provider_id` — existing link for this provider entity id | 1.000 | auto-link |
| 2 | `nba_anchor` — provider exposes an NBA person id already crosswalked | 0.990 | auto-link |
| 3 | `exact_name_dob` — normalised name **and** birthdate match | 0.950 | auto-link |
| 4 | `exact_name` — normalised name, unique in the player pool | 0.850 | auto-link, flag for audit |
| 5 | `fuzzy_name` — above threshold and unambiguous | 0.700–0.849 | **queue** |
| 6 | anything else | — | **queue** |

Rules:

- **One `normalize_name`, in the domain layer**, used by every path. Not two, and never one shadowed inside a function as it is today.
- Thresholds live here as data, not as literals at call sites.
- Ambiguity — two candidates within a small margin — always queues regardless of absolute score.
- Auto-linking at step 4 still writes `confidence`, so a later audit can find the weakest links.

---

## Provider adapter contract

Not schema, but binding on this domain. Adapters return FCP DTOs; provider objects never escape the package.

```python
class FantasyProvider(Protocol):
    def fetch_settings(self, conn, season) -> LeagueSettingsDTO: ...
    def fetch_teams(self, conn, season) -> list[TeamDTO]: ...
    def fetch_periods(self, conn, season) -> list[MatchupPeriodDTO]: ...
    def fetch_matchups(self, conn, period) -> list[MatchupDTO]: ...
    def fetch_rosters(self, conn, on_date) -> list[RosterSlotDTO]: ...
    def fetch_transactions(self, conn, window) -> list[TransactionDTO]: ...
```

**Never subclass the provider library.** `espn_api` may be used inside `providers/espn/client.py` as an HTTP convenience or dropped entirely, but its objects must not reach the domain. Current FCP has two classes subclassing `espn_api.basketball.League` and overriding its *private* loaders — which is both the §7 violation and a standing risk that a library patch release breaks analytics silently.

The transport policy from current FCP's `gateway.py` — explicit connect/read timeouts, typed errors, 504/502/500 mapping, and a monkeypatch scoped to the library's own module namespace — is genuinely good work and should be ported into `providers/espn/client.py` largely intact.

---

## Requests against other foundation domains

None. This domain references 01–03; nothing in 01–03 references it except the lineage columns, which are declared there.

---

## Open questions

1. **Matchup-period derivation (blocking, shared with `02-fantasy`).** ESPN does not cleanly expose period→date ranges; current FCP derives them from daily scoring-period windows. Verify against a live league before the schema is committed. If periods cannot be derived reliably the finality model has no input.
2. **Review-queue UI in slice 1?** The table is required in slice 1 (nothing may silently drop). Whether the *review interface* ships in slice 1 or the queue is worked via SQL initially is a scope call. Recommend: table + status-page count in slice 1, UI in slice 2.
3. **Kaggle CSV as a provider.** The NBA backfill should run as a real ingestion run (`provider_key = 'kaggle'`) rather than a bulk import, so lineage is populated honestly and the path gets exercised. Confirms the pipeline on a dataset with genuine name ambiguity.
4. **Payload retention.** Raw payloads grow without bound. Recommend no deletion in V1 (charter §6: data is king, storage is cheap), revisit at ~10 GB.
