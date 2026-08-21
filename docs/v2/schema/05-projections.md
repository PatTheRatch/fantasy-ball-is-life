# 05 · Projections

**Domain:** projection sources, immutable sets, user adjustments, decision freezes, preferences.
**Depends on:** 01, 03.
**Charter:** Decisions 3 (plurality), 4 (editable without destroying), 6 (FCP eventually owns projections), 22 (immutable versioned beliefs), 24 (deltas + freeze on use).

> Read [`README.md`](README.md) first. Conventions there are binding.

---

## The one thing to preserve from current FCP

The canonical projection schema is the best design asset in the existing codebase and it survives essentially unchanged:

- **One row shape per player**, produced by every source.
- **Consumers read only that shape** — never `p/g`, never `３/g`, never a source-specific column.
- **Makes and attempts, never bare percentages**, so FG%/FT% are derived with correct attempt weighting.

That last rule is what makes an FCP-owned model droppable in later as "just another source" with zero consumer changes (charter Decision 6). Keep it verbatim.

What does **not** survive: the storage. Current FCP keeps projection sets as parquet files plus a `manifest.json` on the container filesystem, with a single **global** `{horizon: set_id}` active map. That means one anonymous caller changes projections for every user in every league, and every uploaded set and weekly benchmark snapshot is destroyed on each deploy. Postgres from here.

---

## Three separate concepts

Charter Decision 5 is explicit that source, horizon and adjustments are distinct, and Decision 24 settles how adjustment works:

```
projection_sets      immutable base — one source × one horizon × one moment
projection_adjustments   a manager's deltas, composed at READ time
projection_freezes   the composed result, captured when it drives a decision
```

Why deltas rather than forking a new set on every edit: a manager who has hand-adjusted forty players must be able to switch base source (BBM → FCP model) and keep those adjustments. Forking welds the edits to one base.

Why freeze anyway: "what exactly was I looking at when I drafted him at $34" must be answerable years later, and recomputing from deltas cannot guarantee that if the base set or the composition rules ever change.

---

## Tables

### `projection_sources`

**Scope:** `global`, or `user` for personal uploads · **Freshness:** `reference`

```sql
create type source_kind    as enum ('fcp_model', 'provider_live', 'upload');
create type source_license as enum ('redistributable', 'user_licensed');

create table projection_sources (
  id              uuid primary key,
  key             text not null,          -- fcp_v1, espn_last15, bbm, hashtag
  name            text not null,
  kind            source_kind not null,
  license         source_license not null,
  owner_user_id   uuid null references users(id),   -- set for personal uploads
  created_at      timestamptz not null default now(),
  unique (key, owner_user_id)
);
```

**`license` is load-bearing, not documentation.** Charter §5 notes FCP may not legally redistribute paid sources, so a user uploads their own licensed copy. The rule the domain layer enforces:

> A `user_licensed` set may never produce league-shared output.

Rejected in `resolve_projections`, not by convention. This is also why the public "our model vs Basketball Monster, measured" page in the old projections spec needs a legal check before it is built — it would publish derived numbers from a user-licensed source.

### `projection_sets`

**Scope:** `global` / `league_season` / `user` per the `scope` column · **Freshness:** `final` once frozen

```sql
create type projection_horizon as enum
  ('rest_of_period', 'next_n_periods', 'rest_of_season', 'full_season');

create type set_scope as enum ('global', 'league_season', 'user');

create table projection_sets (
  id                  uuid primary key,
  source_id           uuid not null references projection_sources(id),
  horizon             projection_horizon not null,
  nba_season_id       uuid not null references nba_seasons(id),

  scope               set_scope not null,
  owner_user_id       uuid null references users(id),
  league_season_id    uuid null references league_seasons(id),
  matchup_period_id   uuid null references matchup_periods(id),   -- short-horizon sets

  as_of               timestamptz not null,     -- what moment this belief describes
  frozen_at           timestamptz null,         -- null = still being written
  row_count           int not null default 0,
  matched_count       int not null default 0,
  unmatched_count     int not null default 0,   -- Decision 28: coverage is data
  provenance          jsonb not null default '{}',
  ingestion_run_id    uuid null references ingestion_runs(id),

  created_at          timestamptz not null default now(),
  check (scope <> 'user'          or owner_user_id is not null),
  check (scope <> 'league_season' or league_season_id is not null)
);

create index projection_sets_lookup_idx
  on projection_sets (source_id, horizon, nba_season_id, as_of desc);
```

Notes:

- **Immutable once `frozen_at` is set** (charter Decision 22). A revised belief is a new set with a later `as_of`, never an edit.
- `as_of` is the belief timestamp, distinct from `created_at`. A set can be *ingested* today describing what a source believed last Tuesday.
- `unmatched_count` makes name-resolution coverage a stored fact. A set that resolved 380 of 500 players is visibly worse than one that resolved 498, and today that difference is invisible.
- `matchup_period_id` scopes short-horizon sets to a real period rather than a bare week integer — which is what makes stale-set detection reliable. Current FCP does this correctly with `week`, and it was a genuinely good fix; this is the same idea against a real object.

### `projection_rows`

**Scope:** inherits its set · **Freshness:** `final` with its set

```sql
create table projection_rows (
  id                uuid primary key,
  projection_set_id uuid not null references projection_sets(id),
  player_id         uuid not null references players(id),

  games             numeric(5,2) null,
  minutes_per_game  numeric(5,2) null,

  -- makes AND attempts. never a bare percentage.
  fgm numeric(6,3) null,  fga numeric(6,3) null,
  ftm numeric(6,3) null,  fta numeric(6,3) null,
  tpm numeric(6,3) null,  tpa numeric(6,3) null,
  tov numeric(6,3) null,

  pts numeric(6,3) null,  reb numeric(6,3) null,
  ast numeric(6,3) null,  stl numeric(6,3) null,
  blk numeric(6,3) null,

  source_value      numeric(8,3) null,   -- the source's own rank/value, if any
  injury_status     text null,

  unique (projection_set_id, player_id)
);

create index projection_rows_player_idx on projection_rows (player_id);
```

**Keyed on `player_id`, never a name.** Name resolution happened in [`04`](04-provider-ingestion.md); anything unresolved is in the review queue and is not silently absent from this table.

### `projection_adjustments`

**Scope:** `manager` (private) · **Freshness:** `event` (superseded, never updated)

```sql
create type adjustment_mode as enum ('absolute', 'multiplier', 'delta');

create table projection_adjustments (
  id                uuid primary key,
  manager_id        uuid not null references managers(id),
  player_id         uuid not null references players(id),
  nba_season_id     uuid not null references nba_seasons(id),
  horizon           projection_horizon null,    -- null = applies to all horizons
  league_season_id  uuid null references league_seasons(id),  -- null = all leagues

  field             text not null,      -- minutes_per_game, games, pts, fga, ...
  mode              adjustment_mode not null,
  value             numeric(10,4) not null,
  note              text null,

  created_at        timestamptz not null default now(),
  superseded_by_id  uuid null references projection_adjustments(id),
  superseded_at     timestamptz null
);

create unique index projection_adjustments_active_idx
  on projection_adjustments (manager_id, player_id, nba_season_id, horizon, field)
  where superseded_at is null;
```

Notes:

- **`manager_id`, not `user_id`** — co-managers share a team's strategy (charter Decision 9), and adjustments are strategy.
- Edits supersede rather than update, so "I thought he'd play 34 minutes in October, 28 by January" is preserved. Charter §6: beliefs are time-dependent.
- Field-level rather than row-level: a manager typically adjusts minutes and games, not fifteen stat lines. Composition applies the delta and lets dependent stats scale.

### `projection_freezes` and `projection_freeze_rows`

**Scope:** `manager` · **Freshness:** `final`

Charter Decision 24's second half — the composed view captured at the moment it drove a decision.

```sql
create type freeze_purpose as enum
  ('draft', 'publication', 'recommendation', 'accuracy_benchmark', 'manual');

create table projection_freezes (
  id                  uuid primary key,
  manager_id          uuid null references managers(id),   -- null = system freeze
  base_set_id         uuid not null references projection_sets(id),
  horizon             projection_horizon not null,
  league_season_id    uuid null references league_seasons(id),
  purpose             freeze_purpose not null,
  context_kind        text null,      -- 'draft_session' | 'recap_edition' | ...
  context_id          uuid null,
  adjustment_ids      uuid[] not null default '{}',   -- exactly what was applied
  composed_at         timestamptz not null default now()
);

create table projection_freeze_rows (
  id                  uuid primary key,
  projection_freeze_id uuid not null references projection_freezes(id),
  player_id           uuid not null references players(id),
  games numeric(5,2) null, minutes_per_game numeric(5,2) null,
  fgm numeric(6,3) null, fga numeric(6,3) null,
  ftm numeric(6,3) null, fta numeric(6,3) null,
  tpm numeric(6,3) null, tpa numeric(6,3) null, tov numeric(6,3) null,
  pts numeric(6,3) null, reb numeric(6,3) null,
  ast numeric(6,3) null, stl numeric(6,3) null, blk numeric(6,3) null,
  unique (projection_freeze_id, player_id)
);
```

`adjustment_ids` records the exact deltas applied, so a freeze is explicable and not just a wall of numbers.

**Freeze on real decisions only** — a draft session, a published ranking, a recorded recommendation, a benchmark snapshot. Freezing every page render would be write amplification for nothing.

### `manager_projection_prefs`

**Scope:** `manager` · **Freshness:** `reference`

```sql
create table manager_projection_prefs (
  id                uuid primary key,
  manager_id        uuid not null references managers(id),
  league_season_id  uuid null references league_seasons(id),   -- null = default
  horizon           projection_horizon not null,
  source_id         uuid not null references projection_sources(id),
  updated_at        timestamptz not null default now(),
  unique (manager_id, league_season_id, horizon)
);
```

This is what replaces the global on-disk active map. Two managers in one league can run entirely different projections privately (charter §5), while league-shared output pins to `league_seasons.default_projection_source_id`.

### `projection_accuracy_scores`

**Scope:** `league_season` · **Freshness:** `derived`

```sql
create table projection_accuracy_scores (
  id                    uuid primary key,
  league_season_id      uuid not null references league_seasons(id),
  matchup_period_id     uuid not null references matchup_periods(id),
  projection_set_id     uuid not null references projection_sets(id),
  category_id           uuid null references categories(id),   -- null = overall
  metric_definition_id  uuid not null references metric_definitions(id),

  mae                   numeric(10,4) null,
  bias                  numeric(10,4) null,
  rank_correlation      numeric(6,4) null,
  sample_size           int null,

  status                computation_status not null,
  reason                text null,
  computed_at           timestamptz not null default now(),
  unique (matchup_period_id, projection_set_id, category_id, metric_definition_id)
);
```

The M-2 benchmark harness, made durable. Its design is sound — score every stored week-horizon set against real results, report unscoreable weeks rather than guessing — and the only thing wrong with it today is that its inputs live on a filesystem wiped every deploy.

`status`/`reason` carry the honest empty states it already produces (`unscoreable`, `no roster source`) as data rather than as a JSON field nobody can query.

---

## Resolution contract

One function. Every consumer — draft optimizer, projected scoreboard, streaming advisor, power rankings — goes through it.

```python
def resolve_projections(
    *,
    nba_season_id: UUID,
    horizon: Horizon,
    source: ProjectionSource,
    adjustments: Sequence[Adjustment] = (),
    as_of: datetime | None = None,
) -> ProjectionView: ...
```

Rules:

1. **Pure.** No ambient state, no reading "the active set." The caller supplies source and adjustments. This is what lets the same code serve shared and private paths (charter §4/§5) — the tension the traceability matrix flagged, resolved by parameterisation.
2. Shared callers pass the league default and no adjustments; private callers pass the manager's preference and their deltas.
3. A `user_licensed` source with a shared caller raises. Not a warning.
4. Missing players are **absent and counted**, never zero-filled. `ProjectionView` exposes coverage so a caller can refuse to act on a bad set.

---

## Requests against other foundation domains

- `02-fantasy` should carry `league_seasons.default_projection_source_id uuid null references projection_sources(id)` for the pinned shared methodology.
- `06-intelligence` defines `metric_definitions(id)` and the `computation_status` enum, referenced above.

---

## Open questions

1. **Adjustment composition semantics.** If a manager sets `minutes_per_game` to 34 on a player projected for 28, do dependent counting stats scale proportionally, or only the field named? Recommend: scale rate stats proportionally by default with an explicit opt-out, because "more minutes" is what a manager means. Needs a product decision before the domain function is written.
2. **Cross-season adjustment carry-over.** Adjustments are season-scoped. Whether a preseason belief carries into the next season is a product question; recommend no, with an explicit copy action.
3. **Set retention.** Frozen sets accumulate one per source per period per season. That is small; recommend no pruning.
4. **FCP model output.** When the model ships (charter Decision 6, old spec's M-3), it writes a `projection_sets` row like any other source. No schema change anticipated — that is the point of this design.
