# 06 · Intelligence

**Domain:** versioned derived metrics, private manager tooling, draft sessions, the sharing boundary.
**Depends on:** 01, 02, 05.
**Charter:** Decisions 12 (shared vs private), 21 (reproducible analytics), 24 (freeze on use), 26 (tenancy from day one), 27 (sharing boundary modelled), 28 (no silent degradation).

> Read [`README.md`](README.md) first. Conventions there are binding.
> **This domain owns `metric_definitions` and `computation_status`,** which [`05`](05-projections.md) and [`07`](07-story.md) both reference. It is the only cross-link between non-foundation domains.

---

## Two responsibilities

**1. Making derived numbers reproducible.** Charter Decision 21: facts are permanent, derived metrics are versioned, so a historical score can be reproduced and compared as methodology improves. A week-7 power ranking computed under v1 must stay explicable after v2 ships.

**2. Holding everything private.** Charter §3 names the private categories — draft strategy, targets, do-not-draft, waiver targets, trades considered, private evaluations, watchlists, notes. **None of this exists in current FCP in any form.** The only per-user surface in the entire current database is `league_memberships.team_name`; draft state lives in browser `localStorage`, and the do-not-draft list is a process-global environment variable shared by every league on the deployment.

This is the largest net-new build in the schema. It is not debt — it is absent.

---

## Shared infrastructure

### `metric_definitions`

**Scope:** `global` · **Freshness:** `reference`

```sql
create table metric_definitions (
  id            uuid primary key,
  key           text not null,          -- power_ranking, projection_mae, streaming_value
  version       int not null,
  description   text not null,
  input_spec    jsonb not null default '{}',   -- what it consumes
  algorithm_ref text null,               -- module path / git ref of the implementation
  released_at   timestamptz not null default now(),
  is_current    boolean not null default true,
  unique (key, version)
);

create unique index metric_definitions_current_idx
  on metric_definitions (key) where is_current;
```

Every derived row anywhere in the schema references one of these. A methodology change increments `version`; old results keep pointing at the version that produced them, and a comparison across methodologies becomes a query rather than an archaeology project.

### `computation_status`

**Scope:** `global` (enum) · Charter Decision 28.

```sql
create type computation_status as enum
  ('ok', 'partial', 'insufficient_data', 'failed');
```

Every derived table carries `status` plus a `reason` required when status is not `ok`. The rule, stated once here for the whole schema:

> A missing row and a row saying "could not compute, here is why" are different things, and the second is almost always what we want.

Current FCP's failures were all of the first kind — an endpoint 500ing in production unnoticed, players silently dropped from a projection set, a computation running on partial inputs and reporting a confident number.

---

## Private manager tables

All of these are scope `manager`. The access rule from [`01-identity.md`](01-identity.md) applies without exception, **including for league admins**: charter §3 says another manager must not see these, and an admin is another manager.

### `draft_sessions`, `draft_picks`, `draft_plans`

**Scope:** `manager` · **Freshness:** `event` / `derived`

```sql
create table draft_sessions (
  id                  uuid primary key,
  manager_id          uuid not null references managers(id),
  league_season_id    uuid not null references league_seasons(id),
  name                text null,
  status              text not null default 'active',   -- active|completed|abandoned
  config              jsonb not null default '{}',      -- budget, roster size, weights
  projection_freeze_id uuid null references projection_freezes(id),
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

create table draft_picks (
  id                uuid primary key,
  draft_session_id  uuid not null references draft_sessions(id),
  pick_number       int not null,
  player_id         uuid not null references players(id),
  price             numeric(8,2) null,
  is_mine           boolean not null default false,
  recorded_at       timestamptz not null default now(),
  unique (draft_session_id, pick_number)
);

create table draft_plans (
  id                uuid primary key,
  draft_session_id  uuid not null references draft_sessions(id),
  plan_key          text not null,
  label             text not null,
  config            jsonb not null default '{}',
  roster            jsonb not null default '[]',
  health            text not null,          -- alive|broken
  health_reason     text null,
  metric_definition_id uuid null references metric_definitions(id),
  status            computation_status not null default 'ok',
  reason            text null,
  computed_at       timestamptz not null default now(),
  unique (draft_session_id, plan_key)
);
```

Notes:

- **Server-side, so a draft survives a device change.** Current FCP holds all of this in `localStorage` under a schema version. That was a deliberate decision (stateless backend, spec D12) and it is defensible for a solo tool — but a draft is the highest-stakes hour of the fantasy year, and losing it to a browser refresh is not acceptable for a product. `localStorage` remains as an offline resilience cache, not the system of record.
- `projection_freeze_id` is charter Decision 24 in practice: the moment a draft session starts, the composed projection view is frozen, so every pick is explicable against exactly the numbers the manager saw.
- `draft_plans.status` means an infeasible or timed-out solve is recorded as such rather than silently missing — preserving current FCP's genuinely good "never freeze on a bad input" principle as data.

### `manager_watchlists`, `manager_player_notes`, `manager_do_not_draft`

**Scope:** `manager` · **Freshness:** `reference`

```sql
create table manager_watchlists (
  id                uuid primary key,
  manager_id        uuid not null references managers(id),
  league_season_id  uuid null references league_seasons(id),
  name              text not null default 'Watchlist',
  created_at        timestamptz not null default now()
);

create table manager_watchlist_items (
  id                uuid primary key,
  watchlist_id      uuid not null references manager_watchlists(id),
  player_id         uuid not null references players(id),
  priority          int null,
  note              text null,
  added_at          timestamptz not null default now(),
  unique (watchlist_id, player_id)
);

create table manager_player_notes (
  id                uuid primary key,
  manager_id        uuid not null references managers(id),
  player_id         uuid not null references players(id),
  league_season_id  uuid null references league_seasons(id),
  body              text not null,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create table manager_do_not_draft (
  id                uuid primary key,
  manager_id        uuid not null references managers(id),
  league_season_id  uuid not null references league_seasons(id),
  player_id         uuid not null references players(id),
  reason            text null,
  created_at        timestamptz not null default now(),
  unique (manager_id, league_season_id, player_id)
);
```

`manager_do_not_draft` is the per-manager, per-league home for what is currently `config.DO_NOT_DRAFT` — a comma-separated env var of player names (including a misspelling of Jayson Tatum) applied process-wide to every league on the deployment. It is also keyed on `player_id`, so a name typo cannot silently no-op.

### `manager_league_prefs`

**Scope:** `manager` · **Freshness:** `reference`

```sql
create table manager_league_prefs (
  id                    uuid primary key,
  manager_id            uuid not null references managers(id),
  league_season_id      uuid not null references league_seasons(id),
  games_per_week        numeric(4,2) null,
  min_season_games      int null,
  position_overrides    jsonb not null default '{}',
  solver_time_limit_s   numeric(6,2) null,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),
  unique (manager_id, league_season_id)
);
```

The rest of `config.py`'s global tunables — `GAMES_PER_WEEK`, `MIN_SEASON_GAMES_FILTER`, `POSITION_OVERRIDES`, `SOLVER_TIME_LIMIT_SECONDS` — given the per-manager, per-league scope their own code comment already claims they have.

---

## Derived analytics

### `analysis_results`

**Scope:** varies by `subject_kind` · **Freshness:** `derived`

One table for point-in-time analytical output, rather than a table per tool.

```sql
create type analysis_subject as enum
  ('league_season', 'matchup', 'fantasy_team_season', 'manager', 'player');

create table analysis_results (
  id                    uuid primary key,
  metric_definition_id  uuid not null references metric_definitions(id),
  subject_kind          analysis_subject not null,
  subject_id            uuid not null,
  league_season_id      uuid null references league_seasons(id),
  manager_id            uuid null references managers(id),   -- set = PRIVATE
  matchup_period_id     uuid null references matchup_periods(id),
  projection_freeze_id  uuid null references projection_freezes(id),

  value                 numeric(14,4) null,
  detail                jsonb not null default '{}',

  status                computation_status not null,
  reason                text null,
  inputs                jsonb not null default '{}',
  computed_at           timestamptz not null default now()
);

create index analysis_results_subject_idx
  on analysis_results (subject_kind, subject_id, metric_definition_id, computed_at desc);

create index analysis_results_private_idx
  on analysis_results (manager_id) where manager_id is not null;
```

**`manager_id` is the privacy switch.** Null means league-shared; set means private to that manager. One column decides, and the repository layer keys off it — rather than the shared/private distinction being implied by which table a tool happened to write to.

Streaming value, trade evaluations, matchup category edges and manager-performance scores all land here with different `metric_definition_id`s. Tools that need bespoke structure get their own table later; this covers the common case without seven near-identical tables.

---

## The sharing boundary

Charter Decision 27: model the boundary in V2, build the surface later. Non-negotiable: *no private strategy leaking into shared league storytelling without explicit user action.*

```sql
create type share_audience as enum ('league', 'manager');

create table share_grants (
  id                    uuid primary key,
  owner_manager_id      uuid not null references managers(id),
  league_season_id      uuid not null references league_seasons(id),
  subject_kind          text not null,     -- watchlist_item|analysis_result|note|signal
  subject_id            uuid not null,
  audience              share_audience not null,
  audience_manager_id   uuid null references managers(id),
  message               text null,
  granted_at            timestamptz not null default now(),
  revoked_at            timestamptz null,
  check (audience <> 'manager' or audience_manager_id is not null)
);

create index share_grants_active_idx
  on share_grants (league_season_id, subject_kind, subject_id)
  where revoked_at is null;
```

Four properties, all deliberate:

- **Nothing is shared by default.** Absence of a grant is the secure state.
- **Explicit and attributable** — who shared what, with whom, when.
- **Revocable** without destroying the record that it was once shared.
- **Additive.** No private table needs a `visibility` column, so no private table can accidentally default to visible.

This covers charter §3's "optional manager-published signals" (categories sought, players of interest, trade availability) when that surface is eventually built — without a migration, which is the whole point of modelling it now.

---

## Requests against other foundation domains

- `01-identity` defines `managers(id)` — the private scope key throughout.
- `02-fantasy` defines `league_seasons(id)`, `matchup_periods(id)`, `fantasy_team_seasons(id)`.
- `05-projections` defines `projection_freezes(id)`.

---

## Open questions

1. **Optimizer port is gated, not free.** Charter §8 lists draft optimization and Monte Carlo targets under preserve, and that is right — but the current implementation is 798 lines of cvxpy with **zero CI coverage**, because 20 tests skip on a gitignored `.xls` fixture. Port it behind a committed synthetic projection fixture and characterization tests captured from current FCP as an oracle (charter §9 names it as one). Do not port on trust.
2. **Manager-performance analytics depth.** Charter §3 wants process distinguished from outcome luck. Scoring a decision needs to know what alternatives were available at the time — the free-agent pool on that date. That is derivable from daily roster snapshots only if they were captured (see `02-fantasy` open question 2). Flagged here because it is the strongest argument for capturing them from slice 1.
3. **`analysis_results` vs bespoke tables.** The generic table is right for v1 breadth. Trade evaluation in particular may outgrow it, since a trade is n-sided and `subject_id` is single-valued. Revisit when the trade analyzer is actually built; not a slice-1 concern.
