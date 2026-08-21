# 02 · Fantasy

**Domain:** leagues, seasons, teams, matchup periods, matchups, rosters, transactions, league events.
**Depends on:** [`01-identity.md`](01-identity.md), [`03-nba.md`](03-nba.md). Foundation.
**Charter:** Decisions 8 (identity persists across seasons), 11 (season-specific rules, not nine hardcoded categories), 14–15 (canonical NBA schedule, real matchup periods), 20 (events + snapshots).

> Read [`README.md`](README.md) first. Conventions there are binding.

---

## The two structural moves

**1. League and team identity persist; seasons are instances.**

Charter Decision 8. Current FCP treats a league as one disposable current-season object — `leagues.espn_season` is a single column, so last season simply does not exist. In V2, `leagues` is the franchise and `league_seasons` is the instance that owns settings, categories, teams and results. The same applies one level down: `fantasy_teams` is the franchise, `fantasy_team_seasons` carries the name (which changes almost every year), the logo and the provider id.

Without this split, "this league's history" is not expressible, and the product thesis is league history.

**2. Matchup periods are rows, derived from the provider.**

Charter Decision 15 and non-negotiable *no hardcoded season calendars*. Current FCP hand-types 22 week ranges **twice** — once in Python, once in TypeScript — keyed to one league's one season. Here a matchup period is a real object with dates, a type and a status, imported once per league-season and joined against real `nba_games`.

This is also what makes freshness legible: `matchup_periods.status` is the finality signal that tells every read path whether it is looking at settled history or a moving target.

---

## Tables

### `leagues`

**Scope:** `league` · **Freshness:** `reference`

```sql
create table leagues (
  id              uuid primary key,
  slug            text not null unique check (slug = lower(slug)),
  name            text not null,
  logo_url        text null,
  accent_color    text null,
  created_by_user_id uuid null references users(id),
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
```

The franchise. Deliberately carries **no** provider id, no season, no credentials, no visibility — all of those are season-scoped or connection-scoped and putting them here is what made the current `leagues` table a single-season object.

### `league_seasons`

**Scope:** `league_season` · **Freshness:** `synced` while active, `final` when complete

```sql
create type league_season_status as enum ('pending', 'active', 'complete');

create table league_seasons (
  id                   uuid primary key,
  league_id            uuid not null references leagues(id),
  nba_season_id        uuid not null references nba_seasons(id),
  season_year          int not null,             -- denormalised for readability
  status               league_season_status not null default 'pending',
  visibility           text not null default 'private',   -- private|public

  -- provider binding for THIS season
  provider_key         provider_key not null,
  provider_league_id   text not null,

  -- settings (charter Decision 11 — season-specific)
  scoring_type         text not null,            -- h2h_each_category|h2h_points|roto
  team_count           int null,
  roster_size          int null,
  roster_slots         jsonb null,               -- {"PG":1,"SG":1,...,"BE":3,"IL":2}
  playoff_team_count   int null,
  regular_season_periods int null,
  acquisition_budget   int null,
  uses_faab            boolean null,
  timezone             text not null default 'America/New_York',

  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),
  unique (league_id, nba_season_id),
  unique (provider_key, provider_league_id, season_year)
);
```

Notes:

- **`timezone` is used, not decorative.** Current FCP stores a per-league timezone, loads it into context, and then does all date arithmetic against a hardcoded `Europe/London` constant. Every date boundary in V2 — week ends, lineup locks, transaction days — resolves through this column.
- `roster_slots` as `jsonb` rather than a table: it is read whole, never queried by slot, and its shape varies per provider.
- No credentials here. Those live in `provider_connections` ([`04`](04-provider-ingestion.md)) so rotation and ownership are separable from league identity.

### `categories`

**Scope:** `global` · **Freshness:** `reference`

Charter Decision 11: *"the database should not hardcode exactly nine categories forever."*

```sql
create type category_kind as enum ('counting', 'ratio');

create table categories (
  id                uuid primary key,
  key               text not null unique,      -- PTS, REB, FG_PCT, TO
  display_name      text not null,
  short_name        text not null,             -- "FG%"
  kind              category_kind not null,
  higher_is_better  boolean not null,
  numerator_stat    text null,                 -- ratio only: 'fgm'
  denominator_stat  text null,                 -- ratio only: 'fga'
  created_at        timestamptz not null default now(),
  check (kind = 'counting' or (numerator_stat is not null and denominator_stat is not null))
);
```

Two things this buys:

- **Turnovers stop being a special case in code.** `higher_is_better = false` is data. Current FCP encodes it as a module-level `LOWER_IS_BETTER_STATS = {"TO"}` set — which is fine and was the fix for a real inverted-winner bug, but it belongs in the row, not the interpreter.
- **Ratio categories know what they are made of.** `FG_PCT` records that it is `fgm/fga`. This is what lets aggregation stay correct: a team's weekly FG% is `Σfgm / Σfga`, never an average of per-player percentages. Getting this wrong is one of the most common fantasy-analytics errors and the schema now makes the right thing derivable.

### `league_season_categories`

**Scope:** `league_season` · **Freshness:** `synced`

```sql
create table league_season_categories (
  id                uuid primary key,
  league_season_id  uuid not null references league_seasons(id),
  category_id       uuid not null references categories(id),
  ordinal           int not null,
  is_scoring        boolean not null default true,
  unique (league_season_id, category_id),
  unique (league_season_id, ordinal)
);
```

A 9-cat league has nine rows. An 8-cat punt-TO league has eight. A points league has none. The domain layer reads this; nothing anywhere assumes a count.

### `fantasy_teams`

**Scope:** `league` · **Freshness:** `reference`

```sql
create table fantasy_teams (
  id              uuid primary key,
  league_id       uuid not null references leagues(id),
  created_at      timestamptz not null default now()
);
```

The franchise. Intentionally almost empty — it exists so a team has continuity across seasons even when its name, logo and owner all change. Records, rivalries and head-to-head history in [`07-story.md`](07-story.md) attach here.

### `fantasy_team_seasons`

**Scope:** `league_season` · **Freshness:** `synced`

```sql
create table fantasy_team_seasons (
  id                 uuid primary key,
  fantasy_team_id    uuid not null references fantasy_teams(id),
  league_season_id   uuid not null references league_seasons(id),
  name               text not null,
  abbreviation       text null,
  logo_url           text null,
  provider_team_id   text not null,
  draft_position     int null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (league_season_id, fantasy_team_id),
  unique (league_season_id, provider_team_id)
);
```

**This is the table almost everything else references** — matchups, rosters, transactions, rankings. Referencing `fantasy_teams` directly from a result would lose the season, and referencing by team *name* (which current FCP does in several joins) breaks the moment someone renames their team mid-season, which people do constantly.

### `matchup_periods`

**Scope:** `league_season` · **Freshness:** `synced` → `final`

```sql
create type period_type   as enum ('regular', 'playoff', 'championship', 'consolation', 'break');
create type period_status as enum ('scheduled', 'in_progress', 'final');

create table matchup_periods (
  id                  uuid primary key,
  league_season_id    uuid not null references league_seasons(id),
  ordinal             int not null,              -- "week 7"
  label               text null,                 -- "Championship Week"
  type                period_type not null default 'regular',
  status              period_status not null default 'scheduled',
  start_date          date not null,
  end_date            date not null,
  provider_period_id  text null,
  finalized_at        timestamptz null,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (league_season_id, ordinal),
  check (end_date >= start_date)
);

create index matchup_periods_dates_idx
  on matchup_periods (league_season_id, start_date, end_date);
```

**`status` is the finality concept the whole architecture leans on.** Once a period is `final`:

- its matchups, category results and transactions are never refetched;
- standings through that period are a deterministic fold and cannot drift;
- the sync job skips it entirely, so a mid-season league refetches one period per cycle rather than twenty-two.

This single column replaces the three overlapping snapshot tables in current FCP (`league_state_snapshots` + `league_week_scoreboards` + `league_week_transactions`). Those exist only because the old model had no way to say *this week is finished* — the migration comments say so explicitly.

`type = 'break'` covers the All-Star gap that current FCP encodes as an unusually long hand-typed week.

### `matchups`

**Scope:** `league_season` · **Freshness:** `synced` → `final`

```sql
create type matchup_result as enum ('home', 'away', 'tie');

create table matchups (
  id                       uuid primary key,
  league_season_id         uuid not null references league_seasons(id),
  matchup_period_id        uuid not null references matchup_periods(id),
  home_team_season_id      uuid not null references fantasy_team_seasons(id),
  away_team_season_id      uuid null references fantasy_team_seasons(id),  -- null = bye
  status                   period_status not null default 'scheduled',

  computed_result          matchup_result null,   -- from our category tally
  provider_result          matchup_result null,   -- what the provider says
  result_source            text null,             -- 'computed' | 'provider_tiebreak'

  ingestion_run_id         uuid not null references ingestion_runs(id),
  observed_at              timestamptz not null,
  normalizer_version       text not null,
  superseded_by_id         uuid null references matchups(id),
  superseded_at            timestamptz null,

  created_at               timestamptz not null default now(),
  unique (matchup_period_id, home_team_season_id, superseded_at)
);
```

Notes:

- **`computed_result` and `provider_result` are separate columns.** Current FCP found this the hard way: a 4–4 playoff matchup with one tied category read as an undecided tie in the recap, because the code computed its own tally and never consulted ESPN's authoritative `winner`. Storing both — and recording in `result_source` which one was used — means the disagreement is visible data rather than a bug discovered in a published recap.
- `away_team_season_id` nullable for byes. Current FCP's playoff all-play bug (14 rankings for 11 active teams, ghosts each awarded 11 turnover wins) came from zero-filling missing matchups; a bye is now explicitly representable.

### `matchup_category_results`

**Scope:** `league_season` · **Freshness:** `final` with its matchup

```sql
create table matchup_category_results (
  id                uuid primary key,
  matchup_id        uuid not null references matchups(id),
  category_id       uuid not null references categories(id),

  home_value        numeric(10,3) null,
  away_value        numeric(10,3) null,
  -- ratio categories keep their components so aggregation stays correct
  home_numerator    numeric(10,2) null,
  home_denominator  numeric(10,2) null,
  away_numerator    numeric(10,2) null,
  away_denominator  numeric(10,2) null,

  result            matchup_result null,
  unique (matchup_id, category_id)
);
```

Storing numerator and denominator alongside the ratio is what makes season-to-date FG% correct. Without them, any aggregation across periods is an average of averages.

### `roster_snapshots` and `roster_slots`

**Scope:** `league_season` · **Freshness:** `snapshot`

```sql
create table roster_snapshots (
  id                      uuid primary key,
  league_season_id        uuid not null references league_seasons(id),
  fantasy_team_season_id  uuid not null references fantasy_team_seasons(id),
  as_of                   date not null,
  matchup_period_id       uuid null references matchup_periods(id),

  ingestion_run_id        uuid not null references ingestion_runs(id),
  observed_at             timestamptz not null,
  normalizer_version      text not null,

  created_at              timestamptz not null default now(),
  unique (fantasy_team_season_id, as_of)
);

create table roster_slots (
  id                  uuid primary key,
  roster_snapshot_id  uuid not null references roster_snapshots(id),
  player_id           uuid not null references players(id),
  slot_code           text null,          -- PG, C, BE, IL
  is_starting         boolean null,       -- null when lineup detail unavailable
  acquisition_type    text null,          -- draft|add|trade|waiver
  injury_status       text null,
  unique (roster_snapshot_id, player_id)
);

create index roster_slots_player_idx on roster_slots (player_id);
```

Charter Decision 10 wants lineup state "when obtainable." `is_starting` is nullable rather than defaulted, because *we do not know* and *they were benched* are different facts and conflating them would quietly corrupt any later manager-performance analysis.

**This data cannot be reconstructed later** — charter §11.7 makes that point. If V2 does not capture daily rosters from the first sync, that history is gone permanently. See open question 2.

### `transactions` and `transaction_items`

**Scope:** `league_season` · **Freshness:** `event`

```sql
create type transaction_kind as enum ('add', 'drop', 'trade', 'draft', 'waiver_claim', 'ir_move');

create table transactions (
  id                  uuid primary key,
  league_season_id    uuid not null references league_seasons(id),
  matchup_period_id   uuid null references matchup_periods(id),
  kind                transaction_kind not null,
  occurred_at         timestamptz not null,
  bid_amount          numeric(10,2) null,
  provider_txn_id     text null,

  ingestion_run_id    uuid not null references ingestion_runs(id),
  observed_at         timestamptz not null,
  normalizer_version  text not null,

  created_at          timestamptz not null default now(),
  unique (league_season_id, provider_txn_id)
);

create table transaction_items (
  id                    uuid primary key,
  transaction_id        uuid not null references transactions(id),
  player_id             uuid not null references players(id),
  action                text not null,        -- add|drop|receive|send
  from_team_season_id   uuid null references fantasy_team_seasons(id),
  to_team_season_id     uuid null references fantasy_team_seasons(id)
);

create index transaction_items_player_idx on transaction_items (player_id);
```

**The header/item split is what makes trades representable.** A trade is one transaction with several items moving in both directions. Current FCP flattened transactions into per-player rows, which is why trades had to be reconstructed heuristically, why "Moves" counted add/drop pairs as two, and why a season's trades were effectively invisible. A multi-player trade here is one row plus N items, and counting is a `group by kind`.

### `league_events`

**Scope:** `league_season` · **Freshness:** `event`

```sql
create table league_events (
  id                  uuid primary key,
  league_season_id    uuid not null references league_seasons(id),
  matchup_period_id   uuid null references matchup_periods(id),
  occurred_at         timestamptz not null,
  event_kind          text not null,      -- matchup_final|trade|streak_started|record_broken|...
  subject_team_season_id uuid null references fantasy_team_seasons(id),
  subject_player_id   uuid null references players(id),
  related_transaction_id uuid null references transactions(id),
  payload             jsonb not null default '{}',
  created_at          timestamptz not null default now()
);

create index league_events_season_time_idx
  on league_events (league_season_id, occurred_at desc);
```

Charter Decision 20's event half, and the spine of the story engine. Append-only, never rewritten. Events are *emitted* by ingestion and by derived computations — they are not a second source of truth, they are a queryable narrative index over facts that live in the tables above.

---

## Standings are not a table

Deliberately. Standings through period N are a deterministic fold over `matchups` and `matchup_category_results` for `final` periods 1..N.

Current FCP stored standings as rolling latest state, which meant every past-week view rendered the end-of-season table, and the fix was to recompute from per-week scoreboards anyway. Storing a derivable, order-dependent aggregate is how that class of bug happens. If profiling later shows the fold is too slow, it becomes a materialised view keyed on `(league_season_id, matchup_period_id)` — recomputed, never authored.

---

## Requests against other foundation domains

- `01-identity` defines `users(id)`, `managers(id)`, `fantasy_team_season_managers` — the last references `fantasy_team_seasons(id)` defined here.
- `03-nba` defines `nba_seasons(id)`, `players(id)`.
- `04-provider-ingestion` must define `ingestion_runs(id)` and the `provider_key` enum.

---

## Open questions

1. **Matchup-period date derivation (blocking).** Charter Decision 15 requires importing periods rather than hand-maintaining them, but ESPN does not directly expose period→date ranges; current FCP derives them from daily `scoringPeriodId` windows. This must be verified against a live ESPN league before the schema is committed, because if periods cannot be derived reliably, the finality model that everything above depends on has no input. Owner: `04-provider-ingestion`. **Highest-priority unknown in the schema phase.**
2. **Daily roster capture from day one.** Roster snapshots cannot be backfilled — ESPN does not serve historical daily rosters. Capturing them from the first sync costs one request per team per day; not capturing them means manager-performance analytics (charter §3) is permanently impossible for the current season. Recommend: capture daily from slice 1, decide later what to do with it.
3. **Bye and consolation semantics in playoffs.** `period_type` and nullable `away_team_season_id` cover the storage; the *rules* (who is eliminated, which bracket is real) are league-configurable and belong in the domain layer, not here. Current FCP got this wrong twice.
4. **Keeper and dynasty leagues.** `fantasy_teams` persisting across seasons makes these representable later. No columns proposed now — out of scope per charter §22.
