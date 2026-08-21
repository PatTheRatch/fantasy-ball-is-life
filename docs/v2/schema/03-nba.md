# 03 · NBA

**Domain:** the real basketball world — seasons, teams, players, games, performances.
**Depends on:** nothing. Foundation.
**Charter:** Decisions 14 (FCP owns the canonical NBA schedule), 10 (historical depth), 19 (identity crosswalk).

> Read [`README.md`](README.md) first. Conventions there are binding.

---

## Why this domain is foundational

Charter Decision 14: *"FCP owns canonical NBA seasons, teams and games. Fantasy providers map their matchup periods onto those real NBA dates."*

This inverts what current FCP does. Today, "how many games does this player have left this week?" is answered from an ESPN payload, and the week boundaries come from a hand-typed calendar. In V2 the real NBA schedule is the anchor, and a fantasy matchup period is a date range projected onto it. Every question that made the old system fragile — games remaining, playoff-week scheduling, rest-of-week projections, streaming value — becomes a join against real games.

`players` is also the table the whole platform pivots on. Charter non-negotiable: *no player identity strategy based primarily on fuzzy names.* Every other domain references `players(id)`.

---

## Tables

### `nba_seasons`

**Scope:** `global` · **Freshness:** `reference`

```sql
create table nba_seasons (
  id              uuid primary key,
  season_year     int not null unique,      -- 2026 == the 2025-26 season
  label           text not null,            -- "2025-26"
  start_date      date not null,
  end_date        date not null,
  all_star_break_start date null,
  all_star_break_end   date null,
  created_at      timestamptz not null default now()
);
```

Notes:

- `season_year` is the **ending** calendar year, matching ESPN's convention and current FCP's `espn_season`. Documented here once so no domain re-derives it.
- The All-Star break is a column rather than folklore. Current FCP encodes it as an unusually long hand-typed week 17; it is a property of the NBA season, and matchup periods should inherit it rather than restate it.

### `nba_teams`

**Scope:** `global` · **Freshness:** `reference`

```sql
create table nba_teams (
  id              uuid primary key,
  abbreviation    text not null unique,     -- "BOS"
  full_name       text not null,
  conference      text null,
  division        text null,
  created_at      timestamptz not null default now()
);
```

Franchises persist; per-season attributes do not live here.

### `nba_team_seasons`

**Scope:** `global` · **Freshness:** `derived`

```sql
create table nba_team_seasons (
  id              uuid primary key,
  nba_team_id     uuid not null references nba_teams(id),
  nba_season_id   uuid not null references nba_seasons(id),
  pace            numeric(6,2) null,
  offensive_rating numeric(6,2) null,
  defensive_rating numeric(6,2) null,
  unique (nba_team_id, nba_season_id)
);
```

Team context the projection model needs (pace, ratings). Nullable because advanced data arrives in a second ingest pass and may not have run — the model must handle absence explicitly rather than assume zero.

### `players`

**Scope:** `global` · **Freshness:** `reference`

**The canonical FCP player.** Everything player-shaped in every other domain references this.

```sql
create table players (
  id                uuid primary key,
  full_name         text not null,
  first_name        text null,
  last_name         text null,
  birthdate         date null,
  height_inches     int null,
  weight_lbs        int null,
  primary_position  text null,
  debut_season_year int null,
  is_active         boolean not null default true,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index players_last_name_idx on players (lower(last_name));
```

Notes:

- **No `normalized_name` column, and no unique constraint on name.** Two players genuinely can share a name; names change (marriages, legal changes, transliteration). Name-based matching is an *ingest* concern and lives entirely in [`04-provider-ingestion.md`](04-provider-ingestion.md) as `provider_identities` → `identity_links`.
- **No `espn_id`, `nba_person_id`, `bbm_name` columns.** External identifiers are crosswalk rows, per charter Decision 19. Putting them here would make `players` grow a column per provider forever and would tempt joins on them.
- `birthdate` is the highest-value disambiguator for identity resolution and is worth ingesting early.

### `player_seasons`

**Scope:** `global` · **Freshness:** `final` once the season closes, `synced` while in progress

```sql
create table player_seasons (
  id              uuid primary key,
  player_id       uuid not null references players(id),
  nba_season_id   uuid not null references nba_seasons(id),
  nba_team_id     uuid null references nba_teams(id),   -- last/primary team
  age             numeric(4,1) null,

  gp              int null,
  gs              int null,
  minutes_total   numeric(8,1) null,
  minutes_per_game numeric(5,2) null,

  -- volume: makes AND attempts, never bare percentages
  fgm             numeric(6,2) null,
  fga             numeric(6,2) null,
  ftm             numeric(6,2) null,
  fta             numeric(6,2) null,
  tpm             numeric(6,2) null,
  tpa             numeric(6,2) null,
  tov             numeric(6,2) null,

  pts             numeric(6,2) null,
  reb             numeric(6,2) null,
  ast             numeric(6,2) null,
  stl             numeric(6,2) null,
  blk             numeric(6,2) null,

  usage_pct       numeric(5,2) null,

  -- lineage
  ingestion_run_id uuid not null references ingestion_runs(id),
  observed_at      timestamptz not null,
  normalizer_version text not null,
  superseded_by_id uuid null references player_seasons(id),
  superseded_at    timestamptz null,

  created_at      timestamptz not null default now(),
  unique (player_id, nba_season_id, superseded_at)
);
```

Notes:

- **Per-game averages**, matching current FCP's ingest contract; `minutes_total` is the season total. Stated once here so no consumer guesses.
- **Makes and attempts, never percentages.** A ratio derived from stored makes/attempts aggregates correctly; a stored percentage does not. This is the single most important stat-modelling rule in the product and it is inherited from the one genuinely good piece of the current projection schema.
- Every column nullable except identity: charter Decision 28. A missing value is `null` and stays distinguishable from zero. Current FCP's season-stats bug — every category reading 0 — was exactly a null-vs-zero conflation.

### `nba_games`

**Scope:** `global` · **Freshness:** `final` once played

```sql
create table nba_games (
  id              uuid primary key,
  nba_season_id   uuid not null references nba_seasons(id),
  game_date       date not null,
  tipoff_at       timestamptz null,
  home_team_id    uuid not null references nba_teams(id),
  away_team_id    uuid not null references nba_teams(id),
  status          text not null default 'scheduled',   -- scheduled|final|postponed
  home_score      int null,
  away_score      int null,
  created_at      timestamptz not null default now()
);

create index nba_games_date_idx on nba_games (game_date);
create index nba_games_team_date_idx on nba_games (home_team_id, game_date);
create index nba_games_away_date_idx on nba_games (away_team_id, game_date);
```

This table answers "how many games does this team play between date A and date B," which is the basis of games-remaining, streaming value, and the playoff-week planner. Current FCP asks ESPN for this inside a request; here it is a local indexed query.

### `player_games`

**Scope:** `global` · **Freshness:** `final` once the game is final

```sql
create table player_games (
  id              uuid primary key,
  player_id       uuid not null references players(id),
  nba_game_id     uuid not null references nba_games(id),
  nba_team_id     uuid not null references nba_teams(id),
  game_date       date not null,             -- denormalised for range queries

  did_play        boolean not null,
  did_start       boolean null,
  dnp_reason      text null,
  minutes         numeric(5,2) null,

  fgm numeric(4,1) null,  fga numeric(4,1) null,
  ftm numeric(4,1) null,  fta numeric(4,1) null,
  tpm numeric(4,1) null,  tpa numeric(4,1) null,
  pts numeric(4,1) null,  reb numeric(4,1) null,
  ast numeric(4,1) null,  stl numeric(4,1) null,
  blk numeric(4,1) null,  tov numeric(4,1) null,

  ingestion_run_id uuid not null references ingestion_runs(id),
  observed_at      timestamptz not null,
  normalizer_version text not null,

  created_at      timestamptz not null default now(),
  unique (player_id, nba_game_id)
);

create index player_games_player_date_idx on player_games (player_id, game_date desc);
```

**This table does not exist in current FCP, and its absence is a live production bug.** `/confidence` and `/matchup-confidence` read a SQLite file (`data/game_logs.db`) that is gitignored, absent from the container, and created by nothing in the repository — so both endpoints return 500, and the win-probability feature that depends on them is silently broken.

Game logs are what make player consistency, confidence intervals, recent-form analysis, and the streaming advisor possible. Charter Decision 10 ("more data is preferable while storage is cheap") applies directly: at ~500 players × ~70 games × 15 seasons this is a few hundred thousand rows, which is nothing.

### `player_availability`

**Scope:** `global` · **Freshness:** `snapshot`

```sql
create table player_availability (
  id              uuid primary key,
  player_id       uuid not null references players(id),
  as_of           timestamptz not null,
  status          text not null,             -- active|out|day_to_day|gtd|suspended
  detail          text null,
  source_provider text not null,
  created_at      timestamptz not null default now()
);

create index player_availability_player_asof_idx
  on player_availability (player_id, as_of desc);
```

A snapshot series, not a mutable column on `players`. "Was he listed out when I set that lineup?" is a question a history platform should answer, and it cannot be if availability is overwritten in place.

---

## Requests against other foundation domains

- `04-provider-ingestion` must define `ingestion_runs(id)`, referenced by every lineage block above. Until it exists, treat those columns as declared-but-unenforced.

---

## Seeding note

Charter Decision 25 says V2 starts empty, but the NBA data in current FCP is *real* — 8,341 player-seasons and 1,915 bios from a Kaggle dataset via `csv_backfill.py`, not mock data.

Recommendation: re-ingest it through the V2 ingestion path rather than copying tables across. It is the cheapest possible end-to-end exercise of `04-provider-ingestion` — a real dataset with real name-matching ambiguity — and it gives the projection work real data to sit on from day one. Running it *as an ingestion run* rather than a bulk import also means the lineage columns are populated honestly from the start.

---

## Open questions

1. **Game-log source.** `nba_api` is IP-blocked from the current host; the Kaggle CSV covers season aggregates but game logs are a separate dataset. Decide the source before committing to `player_games` coverage depth. This gates the consistency/confidence features.
2. **Historical depth.** 15 seasons of season aggregates is settled. Game logs at the same depth is ~2M rows — still trivial for Postgres, but the ingest time and source availability are not. Recommend: full depth for `player_seasons`, most-recent-3-seasons for `player_games` initially, widening later since it is append-only.
3. **Two-way players / G-League.** Out of scope for V1 but the `players` table should not preclude it.
