# GPT Greenfield Architecture Exercise for Full Court Press

**Date:** 2026-08-21  
**Authority:** [`PRODUCT_CONSTITUTION.md`](PRODUCT_CONSTITUTION.md)  
**Current-system evidence:** [`GPT_FCP_AUDIT.md`](GPT_FCP_AUDIT.md)  
**Status:** Target architecture and recommendation; no implementation

## Executive decision

If Full Court Press did not exist and development began today, I would build it as a **modular monolith with a canonical PostgreSQL domain model, a Python application used by both API and worker processes, a React web client, and private object storage for source artifacts**.

The system would have three deliberate product layers:

1. **League World** — shared, durable league facts and storytelling.
2. **Manager Lab** — private analytical tools and strategy for an individual user.
3. **Basketball Intelligence** — reusable player, projection, schedule, category, valuation, and matchup capabilities that power both.

Those are not three separate applications. They are modules in one product with explicit ownership boundaries.

The decisive recommendation after comparing this target with the current repository is:

> **Option 4: Preserve domain logic but rebuild the application around it.**

More precisely: construct the new application shell, database, tenancy model, provider boundary, projection system, API contract, and frontend from a clean baseline; then port only current algorithms and concepts that pass focused correctness tests. Do not incrementally refactor the current architecture into the target. Do not discard the valuable basketball logic merely because its present surroundings should be replaced.

This is not a microservice design. It uses one primary database, one deployable Python codebase with two process types, one web application, and no mandatory Redis, message broker, event bus, data warehouse, or Kubernetes cluster.

## 1. Architectural principles

The Product Constitution translates into these enforceable rules.

### 1.1 Every resource has an owner and a visibility class

All persisted and computed resources are one of:

- **platform** — global reference data, such as canonical players and NBA teams;
- **league-shared** — visible to authorized league members, or publicly when explicitly published;
- **user-private** — owned by exactly one FCP user, usually within one league context;
- **service-private** — credentials, raw provider payloads, operational jobs, and audit data.

There is no ambiguous “application global” bucket for league settings, active projections, draft preferences, or private analysis.

### 1.2 FCP owns the domain

ESPN, Yahoo, Sleeper, Basketball Monster, Hashtag, and NBA.com supply data. They do not define FCP’s core types.

Provider data must cross an adapter and normalization boundary before product code consumes it. No feature module accepts `espn_api` objects or provider-specific JSON structures as domain input.

### 1.3 Base facts are separate from decisions and prose

The dependency direction is:

```text
source observations
    ↓
canonical FCP facts
    ↓
deterministic basketball analytics
    ├── shared league outputs
    └── private user outputs
          ↓
presentation and editorial generation
```

An LLM can write about facts. It cannot create authoritative facts.

### 1.4 Historical truth is first-class

Completed matchups, transactions, roster observations, projection snapshots, and published recap inputs are durable. Current state is never used silently to answer a historical question.

FCP uses timestamped snapshots and immutable finalized facts rather than full event sourcing. Event sourcing is not required for this product.

### 1.5 Freshness is contract data

Every API response backed by external or computed data can state:

- when the source was observed;
- when FCP ingested it;
- whether the data is live, periodic, or finalized;
- whether it is stale;
- which methodology/version produced derived output.

Freshness is not hidden in implementation comments.

### 1.6 Domain logic is pure whenever practical

Category math, projection composition, matchup evaluation, valuation, target construction, standings, awards, and optimization consume explicit inputs and return explicit outputs. They do not open database connections, read environment variables, call ESPN, or know about HTTP.

### 1.7 Start simple, leave clean seams

At the expected scale, a modular monolith and PostgreSQL are sufficient. Separation is achieved through modules and contracts, not network boundaries.

## 2. Overall system architecture

```text
                                 ┌────────────────────────────┐
                                 │ React + TypeScript web app │
                                 │                            │
                                 │ League World               │
                                 │ Manager Lab                │
                                 └─────────────┬──────────────┘
                                               │ HTTPS / JSON
                                               │ Supabase JWT
                                 ┌─────────────▼──────────────┐
                                 │ Python modular monolith    │
                                 │ FastAPI application        │
                                 │                            │
                                 │ identity & access          │
                                 │ player catalog             │
                                 │ leagues & seasons          │
                                 │ provider integrations      │
                                 │ projections                │
                                 │ basketball intelligence    │
                                 │ newsroom                   │
                                 │ draft room                 │
                                 └──────┬───────────┬─────────┘
                                        │           │
                     transactional SQL │           │ private artifacts
                                        │           │
                              ┌─────────▼───┐  ┌────▼────────────┐
                              │ PostgreSQL  │  │ Object storage  │
                              │ + RLS       │  │ uploads/raw     │
                              └─────────▲───┘  └────▲────────────┘
                                        │           │
                                 ┌──────┴───────────┴─────────┐
                                 │ Python worker process      │
                                 │ durable Postgres job queue │
                                 └──────┬───────────────┬─────┘
                                        │               │
                               ┌────────▼──────┐  ┌─────▼─────────┐
                               │ ESPN adapter │  │ NBA/projection │
                               │ future:      │  │ source adapters│
                               │ Yahoo/Sleeper│  └────────────────┘
                               └───────────────┘
```

### Deployable processes

There are only three application process types:

1. **Web frontend** — compiled static React assets served by Caddy or a CDN.
2. **API** — stateless FastAPI instances.
3. **Worker** — the same Python package running durable jobs.

A lightweight scheduler inserts due jobs into PostgreSQL. It may run inside one elected worker or as a separate cron command from the same image. It is not a new service with its own domain.

### Why a modular monolith

FCP’s product capabilities share the same canonical players, leagues, rosters, schedules, scoring rules, and projections. Splitting them into services would create distributed consistency problems at a scale that does not justify them.

A modular monolith provides:

- transactional league and membership operations;
- one authorization model;
- direct reuse of basketball intelligence;
- simple local development;
- simple deployment;
- clear module seams that can be separated later only if actual load demands it.

## 3. Product and module boundaries

| Module | Owns | Does not own |
| --- | --- | --- |
| Identity & Access | profiles, memberships, roles, invites, access decisions | fantasy team facts, projections |
| Player Catalog | canonical players, external IDs, aliases, NBA teams | provider league rosters, projections |
| League Domain | leagues, seasons, teams, managers, rules, periods, rosters, matchups, transactions | ESPN clients, private strategy |
| Provider Integrations | connections, provider bindings, sync cursors, raw source observations | canonical business decisions |
| Projections | sources, datasets, horizons, lines, imports, scenarios, adjustments, selection | draft plans, power rankings |
| Basketball Intelligence | category math, schedules, valuation, fit, matchup simulation, all-play | persistence, HTTP, user authorization |
| Newsroom | fact packages, awards, shared rankings, recap editions, editorial jobs | authoritative league ingestion |
| Draft Room | private draft sessions, picks, settings, plans, optimization use cases | shared league publishing |
| Jobs | durable execution, retry, scheduling, leases, job status | domain rules for each job |
| API | authentication, authorization orchestration, validation, serialization | basketball formulas |

Future private tools—streaming, waivers, trades, comparisons, playoff planning—belong beside Draft Room as feature modules. They consume League Domain, Projections, and Basketball Intelligence rather than reimplementing them.

## 4. Frontend architecture

### 4.1 Technology choice

Use:

- React;
- TypeScript in strict mode;
- Vite;
- React Router;
- TanStack Query for server state;
- a generated API client from FastAPI’s OpenAPI document;
- a small, explicit design system;
- a focused client-state library only for complex ephemeral tools such as an active draft board.

Do not access application tables directly from the browser. Supabase JS is used only for authentication/session handling. All FCP data goes through the application API so authorization, data contracts, freshness, and audit behavior have one boundary.

### 4.2 Route structure

The URL space makes the shared/private distinction visible.

```text
/login
/signup
/join/:inviteToken

/leagues/:leagueSlug                       shared league home
/leagues/:leagueSlug/seasons/:seasonKey    shared season
/leagues/:leagueSlug/matchups/:periodKey   shared matchup facts
/leagues/:leagueSlug/standings             shared standings
/leagues/:leagueSlug/newsroom              shared archive
/leagues/:leagueSlug/newsroom/:edition     published story

/app                                       authenticated manager home
/app/leagues/:leagueSlug                   personal league dashboard
/app/leagues/:leagueSlug/draft/:sessionId  private Draft Room
/app/leagues/:leagueSlug/projections        private projection settings
/app/leagues/:leagueSlug/watchlist          future private tool
/app/leagues/:leagueSlug/trades             future private tool
```

League routes may still require membership when a league is private. “Shared” means shared within the league, not automatically public on the internet.

### 4.3 Feature organization

Organize the frontend by product capability, not component type alone.

```text
src/
  app/                    router, providers, error boundaries, shell
  api/                    generated client and query-key policy
  auth/
  league-world/
    home/
    matchups/
    standings/
    season/
  newsroom/
  manager-lab/
    draft-room/
    projections/
  shared/
    ui/
    formatting/
    accessibility/
```

Each feature owns its route components, query hooks, view models, and focused UI. The global `shared/ui` directory contains only genuinely reusable primitives.

### 4.4 State rules

- Remote facts and persisted private state live in TanStack Query.
- Draft editing state may be optimistic and local during interaction, but is persisted to a private server-side draft session with a version number.
- No important private strategy exists only in `localStorage`.
- URL parameters identify shareable view state such as season and matchup period.
- Feature code receives typed API DTOs; it does not interpret provider field names.

### 4.5 Privacy in the interface

Private tools receive a visible “Only you” treatment. Shared/published actions use explicit copy such as “Publish to league.” The UI never relies on route obscurity for privacy, but the visual distinction reduces accidental disclosure.

## 5. Backend and application architecture

### 5.1 Technology choice

Use Python because FCP’s most valuable existing logic and its likely future modeling work depend on Python’s numerical ecosystem: pandas or Polars, NumPy, SciPy, CVXPY, and model tooling.

Use FastAPI as the HTTP boundary, but keep FastAPI and Pydantic models out of the domain layer.

Use SQLAlchemy 2.x and Alembic, or a comparably explicit typed SQL repository layer, for transactional PostgreSQL access. Application code should not assemble PostgREST query strings. Supabase remains the managed PostgreSQL/Auth/Storage provider, not the application’s domain API.

### 5.2 Internal layering

Each module follows a shallow version of ports and adapters:

```text
domain.py / domain/
    entities, value objects, invariants, pure calculations

application.py / application/
    use cases, transaction boundaries, authorization requirements

ports.py
    repository and external-provider protocols

infrastructure/
    PostgreSQL repositories, ESPN adapters, object storage, LLM clients

api.py
    HTTP request/response models and route handlers
```

Not every module needs five directories. Small modules can use files. The dependency rule matters more than folder ceremony:

```text
API / worker → application → domain
infrastructure implements ports → application/domain never imports infrastructure
```

### 5.3 Transactions

An application use case owns a database transaction. Examples:

- create league + owner membership + provider binding;
- finalize matchup + category results;
- publish recap edition + supersede previous edition;
- create projection dataset + canonical lines + import issues;
- append draft pick + increment session version.

No workflow leaves a partially created aggregate because two unrelated HTTP writes were issued sequentially.

## 6. Canonical domain model

### 6.1 Identity distinctions

FCP must not conflate these identities:

- **FCP user** — a person with an FCP account.
- **Provider manager** — a manager record reported by ESPN/Yahoo/Sleeper.
- **League franchise** — a durable team identity within an FCP league across seasons.
- **Season team** — the franchise’s representation, name, roster, and provider ID for one season.
- **NBA player** — a canonical FCP player with external source identities.

An FCP user may be linked to a season team through a verified claim or commissioner assignment. Provider manager records may exist even when their humans do not use FCP.

### 6.2 Core aggregates

#### League

```text
League
  id
  slug
  name
  visibility
  timezone
  created_by_user_id

LeagueSeason
  id
  league_id
  season_key
  sport_year
  status
  regular_season_periods
  playoff_periods
  scoring_type

ScoringCategory
  league_season_id
  category_code
  direction: higher_better | lower_better
  aggregation: sum | ratio
  numerator_stat_code?  # FGM / FTM
  denominator_stat_code? # FGA / FTA

RosterSlotRule
  league_season_id
  slot_code
  count
  eligible_positions
```

Category direction and percentage aggregation are data-driven league rules. `TO` is not inverted through scattered special cases.

#### Teams and managers

```text
LeagueFranchise
  id
  league_id
  stable_name

SeasonTeam
  id
  league_season_id
  franchise_id
  display_name
  abbreviation
  logo_url

ProviderManager
  id
  provider
  provider_manager_id
  display_name

TeamManagerAssignment
  season_team_id
  provider_manager_id?
  fcp_user_id?
  assignment_type
  valid_from
  valid_to?
```

#### Periods, matchups, and results

```text
MatchupPeriod
  id
  league_season_id
  period_number
  starts_at
  ends_at
  phase: regular | playoffs | consolation
  status: scheduled | active | final

Matchup
  id
  matchup_period_id
  home_team_id
  away_team_id
  status
  provider_revision
  finalized_at?

MatchupCategoryResult
  matchup_id
  category_code
  home_value
  away_value
  winner_team_id?
  is_tie
```

Completed results are immutable except for explicit correction revisions with an audit trail.

#### Rosters and transactions

```text
RosterSnapshot
  id
  season_team_id
  effective_at
  observed_at
  source_ingestion_run_id
  is_period_end_snapshot

RosterEntry
  roster_snapshot_id
  player_id
  slot_code
  lineup_status
  injury_status_observed

Transaction
  id
  league_season_id
  provider_transaction_id
  transaction_type
  occurred_at
  observed_at
  status

TransactionItem
  transaction_id
  player_id?
  from_team_id?
  to_team_id?
  item_type
  bid_amount?
```

Snapshots answer “who was rostered at this time”; transactions explain changes. FCP does not try to reconstruct old rosters from today’s roster.

## 7. Player identity model

### 7.1 Canonical player

`players.id` is the only canonical player join key inside FCP.

```text
Player
  id UUID
  canonical_name
  birth_date?
  active_status
  merged_into_player_id?

PlayerExternalIdentity
  player_id
  source: nba | espn | yahoo | sleeper | bbm | hashtag
  external_id
  valid_from?
  valid_to?
  UNIQUE(source, external_id)

PlayerAlias
  id
  player_id
  source?
  alias
  normalized_alias
  confidence
  provenance
```

NBA ID is a highly valuable identity but is not assumed to exist for every prospect or imported projection row.

### 7.2 Resolution workflow

1. Prefer exact external ID mapping.
2. Use source-specific aliases.
3. Use normalized-name matching only as a candidate generator.
4. Use corroborating facts such as NBA team, birth date, and position.
5. Auto-resolve only above a conservative threshold.
6. Send ambiguous rows to a private/admin resolution queue.
7. Persist the resulting external-ID or alias mapping so the ambiguity is solved once.

Every projection import reports matched, unmatched, and ambiguous rows. Silent name joins are prohibited for important persisted relationships.

### 7.3 Merges and corrections

Player records are not destructively rewritten. A duplicate can point to `merged_into_player_id`; foreign keys are migrated transactionally, and the merge is audited. External identities remain unique.

## 8. Fantasy-platform normalization

### 8.1 Provider ports

Define a capability-oriented provider interface rather than mirroring one ESPN client:

```python
class FantasyProvider(Protocol):
    def validate_connection(...) -> ProviderLeaguePreview: ...
    def fetch_league(...) -> ProviderLeaguePayload: ...
    def fetch_teams_and_managers(...) -> ProviderTeamsPayload: ...
    def fetch_rosters(..., as_of: datetime) -> ProviderRostersPayload: ...
    def fetch_matchup_periods(...) -> ProviderPeriodsPayload: ...
    def fetch_matchups(..., period_key: str) -> ProviderMatchupsPayload: ...
    def fetch_transactions(..., cursor: str | None) -> ProviderTransactionsPayload: ...
    def fetch_pro_schedule(...) -> ProviderProSchedulePayload | None: ...
```

Provider payload DTOs are allowed to be provider-shaped. They exist only in the integration module. A separate normalizer maps them into application commands against canonical FCP entities.

Capability flags describe provider limitations. Product code can show an honest unavailable state rather than assuming every provider exposes an ESPN-equivalent endpoint.

### 8.2 Provider bindings

```text
ProviderConnection
  id
  provider
  created_by_user_id
  credential_secret_reference
  status
  last_validated_at

ProviderLeagueBinding
  id
  league_id
  provider_connection_id
  provider_league_id
  current_provider_season
  sync_policy

ProviderTeamBinding
  season_team_id
  provider
  provider_team_id
```

Credentials are encrypted with a managed secret/key facility and are never returned through ordinary application APIs. A connection can be replaced without changing the FCP league identity.

### 8.3 ESPN boundary

The ESPN adapter owns:

- `espn-api` and any direct ESPN requests;
- SWID and `espn_s2` use;
- timeouts, retries, rate limits, and error classification;
- ESPN request caching;
- translation of ESPN IDs and structures into provider DTOs;
- fixture capture with secrets removed.

The ESPN adapter does not calculate FCP standings, power rankings, awards, projection value, or user recommendations.

### 8.4 Yahoo and Sleeper later

Adding a provider means implementing the capability port, its credential flow, its bindings, and contract fixtures. The normalized league commands and downstream features remain unchanged.

No Yahoo or Sleeper scaffolding beyond the provider protocol and provider enum should be built in the first slice.

## 9. Source ingestion and normalization

### 9.1 Ingestion records

Every provider sync creates an `ingestion_run`:

```text
IngestionRun
  id
  provider_connection_id
  league_id?
  capability
  requested_at
  started_at
  completed_at?
  status
  source_cursor?
  records_received
  records_written
  error_code?
  error_detail_redacted?
  artifact_id?
```

Raw responses or uploaded files are stored as private, encrypted object-storage artifacts when they are useful for audit/replay. PostgreSQL stores metadata, checksum, ownership, parser version, and retention date.

### 9.2 Idempotency

Provider identifiers and natural uniqueness constraints make repeated syncs safe. Examples:

- unique provider league binding;
- unique provider transaction ID per league;
- unique matchup per provider period and matchup ID;
- unique observation fingerprint for a roster snapshot;
- unique projection import checksum per user and source when desired.

Normalization of one coherent provider response happens in a transaction. A failed sync does not leave half a matchup or half a league creation.

## 10. Projection architecture

Projections are immutable datasets plus private selection and adjustment layers.

### 10.1 Projection sources

```text
ProjectionSource
  id
  code: fcp | espn | bbm | hashtag | upload | custom
  display_name
  provider_type
  redistribution_policy
  supported_horizon_kinds
  active
```

`redistribution_policy` describes whether raw lines may be shared, whether only private use is allowed, and whether aggregated derived outputs may be shown. This is application policy metadata, not a substitute for legal review.

### 10.2 Horizons

A projection horizon has both semantic meaning and exact temporal bounds.

```text
ProjectionHorizon
  kind: next_game | rest_of_week | rolling_days | date_range |
        rest_of_season | full_season
  starts_on
  ends_on
  league_season_id?
  matchup_period_id?
  rolling_days?
```

Tools declare which kinds they support. Draft Room requires a season horizon. Streaming can require next-game, rolling-days, or rest-of-week. Trade analysis can compare several horizons.

### 10.3 Immutable datasets and lines

```text
ProjectionDataset
  id
  source_id
  owner_user_id?          # set for private licensed/user uploads
  league_id?              # optional contextual dataset
  visibility: platform | user_private
  horizon_kind
  starts_on
  ends_on
  as_of
  version
  parser_version?
  source_artifact_id?
  status: importing | ready | failed | superseded
  redistributable

ProjectionLine
  dataset_id
  player_id
  games
  minutes_per_game?
  pts_per_game
  reb_per_game
  ast_per_game
  stl_per_game
  blk_per_game
  threes_per_game
  turnovers_per_game
  fgm_per_game
  fga_per_game
  ftm_per_game
  fta_per_game
  source_value?
  source_rank?
  injury_assumption?
```

Makes and attempts are canonical, not just percentages. The original dataset is never mutated.

### 10.4 User uploads

Upload flow:

```text
user requests private upload slot
  → browser uploads directly to private object storage
  → API creates projection import job
  → adapter detects/parses the source
  → player identity resolver maps rows
  → import issues are recorded
  → immutable private ProjectionDataset becomes ready
  → user explicitly selects it for a context
```

The original file remains private to its owner and service jobs. It is never exposed to league members.

### 10.5 Source selection

```text
UserProjectionPreference
  user_id
  league_id
  analysis_context: default | draft | matchup | streaming | trade
  horizon_kind
  dataset_id or source_policy
  updated_at
```

Shared analytics never read this table. They use a league/platform methodology policy that points to an approved shared dataset or FCP model version.

### 10.6 Adjustments and scenarios

```text
ProjectionScenario
  id
  owner_user_id
  league_id
  base_dataset_id
  name
  horizon_kind
  version

ProjectionAdjustment
  scenario_id
  player_id
  field_code
  operation: set | delta | multiplier
  numeric_value
  reason?
  effective_from?
  effective_to?
```

An effective projection is computed as:

```text
immutable base dataset
  + scenario adjustments
  + explicit availability/schedule assumptions
  = effective private projection view
```

This permits “more minutes,” “two missed games,” or “higher assist rate” without overwriting the imported or FCP source.

### 10.7 First-party FCP projections

An FCP model writes a normal immutable `ProjectionDataset` with `source=fcp`, a model version, training-data cutoff, and methodology metadata. Downstream tools do not need a new integration path.

Model training infrastructure is not built until a model exists. The dataset contract is the only required future seam.

## 11. Basketball Intelligence layer

Basketball Intelligence is a library of pure or mostly pure capabilities.

### 11.1 Shared value objects

- `StatCode`
- `ScoringCategory`
- `CategoryDirection`
- `RatioStatDefinition`
- `ProjectionVector`
- `ScheduleWindow`
- `RosterConstraints`
- `LeagueContext`
- `TeamProjection`
- `MatchupProjection`

### 11.2 Capabilities

- Aggregate player rates into team totals using games and schedules.
- Aggregate FG% and FT% from makes/attempts.
- Compare category values using league scoring directions.
- Calculate all-play records.
- Calculate standings from finalized matchup facts.
- Calculate category strength and scarcity.
- Evaluate player contribution and team fit.
- Derive replacement level and auction values.
- Simulate matchup outcomes.
- Generate Monte Carlo draft targets.
- Optimize a roster under budget, position, and category constraints.
- Calculate deterministic award candidates and storyline evidence.

These capabilities receive canonical objects and explicit methodology configuration. They have no hidden current season, default league, file path, or personal do-not-draft list.

### 11.3 Methodology versions

Persisted derived output records:

- `methodology_code`;
- `methodology_version`;
- input fact cutoff;
- projection dataset/scenario IDs where permitted;
- deterministic input fingerprint;
- computed timestamp.

This makes shared power rankings coherent and allows old newsroom facts to remain explainable after formulas evolve.

## 12. Shared and private analytics

### 12.1 Shared analytics

Shared outputs are computed from canonical league facts and a league-wide FCP/default methodology. Examples:

- standings;
- all-play records;
- shared power rankings;
- league awards;
- playoff races;
- league records and trends;
- deterministic storyline candidates.

They carry `league_id` and cannot incorporate an individual user’s private projection preference or adjustments.

### 12.2 Private analytics

Private outputs carry both `owner_user_id` and `league_id`. Examples:

- draft plans;
- target and exclusion lists;
- matchup optimization;
- waiver rankings;
- trade candidates;
- watchlists;
- projection scenarios;
- private valuations.

The application layer checks ownership before loading inputs, not only before returning output. This prevents another user’s private dataset from influencing a calculation indirectly.

### 12.3 Persisted results

Use a common `analysis_runs` header for provenance and feature-owned result tables for important queryable outputs.

```text
AnalysisRun
  id
  analysis_type
  scope: league_shared | user_private
  league_id
  owner_user_id?
  methodology_code
  methodology_version
  input_fingerprint
  data_as_of
  started_at
  completed_at?
  status

PowerRankingRow
  analysis_run_id
  season_team_id
  rank
  score
  component_values JSONB

MatchupProjectionResult
  analysis_run_id
  matchup_id
  category_code
  home_projection
  away_projection
  win_probability?
```

Typed, versioned JSON is acceptable for read-optimized details that do not need relational queries. Canonical facts should not be hidden in generic JSON blobs.

## 13. Newsroom architecture

### 13.1 Fact package

Newsroom generation starts with an immutable deterministic package:

```text
NewsroomFactPackage
  id
  league_id
  league_season_id
  matchup_period_id
  version
  data_as_of
  methodology_versions
  quality_status
  warnings
  facts JSONB              # validated versioned schema
  evidence_manifest JSONB  # canonical record IDs and analysis run IDs
```

The package can contain matchup summaries, standings, power rankings, transactions, awards, records, and storyline candidates. Every factual statement available to editorial generation can be traced back to canonical records or deterministic analysis.

### 13.2 Editorial content

```text
RecapEdition
  id
  fact_package_id
  version
  status: draft | published | superseded
  content_schema_version
  structured_content JSONB
  provider
  model
  prompt_version
  generated_at
  published_at?
  published_by_user_id?
```

Generation is a durable, metered job. The output is schema-validated; failures do not affect the fact package. Publishing is transactional and guarantees one current published edition per league/period while retaining all history.

### 13.3 Multi-season story

League record and trend queries operate on canonical finalized history, not prior prose. A future season narrative can cite previous fact packages and editorial editions, but it recomputes facts from canonical data.

## 14. Draft Room architecture

Draft Room is private from storage through API through UI.

```text
DraftSession
  id
  owner_user_id
  league_season_id
  projection_scenario_id or projection_dataset_id
  status
  budget
  roster_size
  version
  created_at
  updated_at

DraftPreference
  draft_session_id
  category_targets
  favorite_teams
  minimum_games
  valuation_method

DraftPlayerPreference
  draft_session_id
  player_id
  preference_type: target | exclude | avoid | watch
  priority?
  max_price?

DraftPick
  id
  draft_session_id
  sequence
  player_id
  acquiring_team_id?
  price
  is_user_pick

DraftPlan
  id
  draft_session_id
  based_on_session_version
  strategy_code
  methodology_version
  result JSONB
  created_at
```

The optimizer remains a pure engine:

```python
optimize_draft(
    available_players,
    effective_projections,
    league_rules,
    current_roster,
    remaining_budget,
    private_preferences,
    target_profile,
) -> DraftPlanResult
```

It does not load files, inspect environment variables, query ESPN, or know which user invoked it.

Draft session writes use optimistic concurrency: the client sends the last observed version; a conflicting pick returns `409` with current state. This supports multiple tabs safely without introducing real-time collaboration infrastructure.

## 15. Persistence model

### 15.1 Storage choices

| Data | Store | Reason |
| --- | --- | --- |
| Identity, canonical facts, memberships | PostgreSQL | transactions, constraints, RLS |
| Derived analysis metadata/results | PostgreSQL | provenance and queries |
| Projection lines | PostgreSQL | current scale, joins, tenant isolation |
| Raw projection uploads | Private object storage | licensed/private files, size |
| Raw provider payloads worth retaining | Private object storage | audit/replay without bloating core tables |
| Public images/static assets | Object storage/CDN | delivery |
| Durable jobs | PostgreSQL | no broker required at this scale |
| Ephemeral process cache | memory | simple acceleration only |

Parquet can be used later for offline model-training exports or large backtests. It is not the authoritative online projection database.

### 15.2 Proposed table groups

#### Identity and access

- `user_profiles`
- `league_memberships`
- `league_invitations`
- `team_manager_assignments`
- `audit_log`

#### Player catalog

- `players`
- `player_external_identities`
- `player_aliases`
- `nba_teams`
- `player_nba_team_stints`

#### Leagues

- `leagues`
- `league_seasons`
- `scoring_categories`
- `roster_slot_rules`
- `league_franchises`
- `season_teams`
- `provider_managers`
- `matchup_periods`
- `matchups`
- `matchup_category_results`
- `roster_snapshots`
- `roster_entries`
- `transactions`
- `transaction_items`

#### Provider integration

- `provider_connections`
- `provider_league_bindings`
- `provider_team_bindings`
- `ingestion_runs`
- `source_artifacts`

#### Projections

- `projection_sources`
- `projection_datasets`
- `projection_lines`
- `projection_import_issues`
- `user_projection_preferences`
- `projection_scenarios`
- `projection_adjustments`

#### Analytics and products

- `analysis_runs`
- feature-owned result tables
- `newsroom_fact_packages`
- `recap_editions`
- `draft_sessions`
- `draft_preferences`
- `draft_player_preferences`
- `draft_picks`
- `draft_plans`

#### Operations

- `jobs`
- `job_attempts`
- `usage_ledger`
- `audit_log`

### 15.3 Constraints over convention

Use foreign keys, unique constraints, check constraints, and partial indexes to encode invariants:

- one membership per user/league;
- one provider binding per provider league and season as appropriate;
- one published recap per league/period;
- no private analysis without an owner;
- unique external player identity per source;
- one projection line per dataset/player;
- no matchup with the same home and away team;
- finalized periods cannot accept ordinary mutable results;
- draft picks unique by session and sequence.

## 16. Historical data and freshness

### 16.1 Time fields have distinct meanings

- `occurred_at` — when the real/provider event occurred.
- `effective_at` — when a state such as a roster was true.
- `observed_at` — when FCP observed the provider state.
- `ingested_at` — when FCP committed it.
- `data_as_of` — latest input cutoff for derived output.
- `finalized_at` — when FCP considered a fact complete.
- `published_at` — when content became visible.

These must not be collapsed into a generic `created_at`.

### 16.2 Freshness policy

| Data class | Typical policy | Mutation behavior |
| --- | --- | --- |
| Active draft | user command / provider polling while active | versioned mutable session |
| Current roster | near-live, e.g. 5–15 minutes | append observations; latest is current |
| Current matchup | near-live during active period | upsert provisional result revision |
| Recent transactions | cursor sync every few minutes | append immutable transactions |
| Standings and season stats | recompute after relevant fact changes | versioned derived run |
| Shared power rankings | scheduled or explicit publish cadence | immutable analysis run |
| Completed matchups | finalization job after provider closes period | immutable; corrections audited |
| Historical transactions | immutable after ingestion | correction via explicit revision |
| Projection datasets | immutable | new dataset version |
| Published recap facts/content | immutable version | supersede, never overwrite |
| Completed NBA seasons | immutable source version | corrected dataset version |

Exact polling cadence is provider- and product-policy configuration, not a hardcoded season calendar.

### 16.3 API freshness metadata

An API response can use:

```json
{
  "data": {},
  "meta": {
    "scope": "league_shared",
    "freshness": "periodic",
    "data_as_of": "2026-01-15T18:45:00Z",
    "refreshed_at": "2026-01-15T18:45:07Z",
    "stale": false,
    "methodology": {"code": "power_rankings", "version": "2.1"}
  }
}
```

The client can render “Updated 6 minutes ago” and honest stale states without knowing which table supplied the data.

## 17. Jobs and background processing

### 17.1 Durable Postgres job queue

Use a `jobs` table with:

- job type;
- JSON parameters validated by the job handler;
- ownership/scope metadata;
- scheduled time;
- priority;
- idempotency key;
- attempt count;
- lease owner and expiry;
- status;
- last redacted error.

Workers claim jobs using `FOR UPDATE SKIP LOCKED`. Jobs are retried with bounded exponential backoff. A crashed worker’s lease expires and the job becomes claimable again.

This provides durability and horizontal worker scaling without Redis or a message broker.

### 17.2 Job types

- validate provider connection;
- sync league configuration;
- sync teams and managers;
- sync current rosters;
- sync matchup period;
- sync transactions since cursor;
- finalize completed period;
- backfill historical league facts;
- import projection upload;
- compute shared analytics;
- compute/cached private analysis when not synchronous;
- build newsroom fact package;
- generate recap editorial content;
- import NBA season data;
- evaluate projection accuracy.

### 17.3 Scheduling and deduplication

The scheduler evaluates due work and inserts idempotent jobs. A uniqueness rule such as `(job_type, scope_id, time_bucket)` prevents duplicate refreshes. User-triggered refreshes obey provider-specific cooldowns and usage policy.

### 17.4 Synchronous versus asynchronous

- Fast deterministic calculations under a small latency budget can run in the request.
- Provider calls, uploads, LLM generation, historical backfills, and expensive optimization run as jobs.
- APIs return `202 Accepted` with a job resource where appropriate.
- The frontend polls job state at a modest cadence. WebSockets are unnecessary initially.

## 18. Authentication, authorization, and tenant isolation

### 18.1 Authentication

Keep Supabase Auth unless product requirements later outgrow it. The browser obtains a short-lived JWT. FastAPI validates the JWT locally using the project JWKS, issuer, audience, expiry, and signature. It does not call Supabase once per protected request.

### 18.2 Application authorization

Every use case receives an `ActorContext`:

```text
ActorContext
  user_id?
  platform_roles
  league_memberships {league_id → role/team_assignment}
  request_id
```

Authorization policies are named and testable:

- `can_view_league`
- `can_manage_league`
- `can_publish_newsroom`
- `owns_private_resource`
- `can_use_projection_dataset`
- `can_trigger_provider_sync`

Route handlers do not implement ad hoc role checks.

### 18.3 Database RLS as defense in depth

The backend sets transaction-local actor context for PostgreSQL. RLS policies enforce:

- platform rows: readable according to public policy;
- league-shared rows: members, admins, or public-published readers;
- user-private rows: `owner_user_id = current_actor_user_id` only;
- service-private rows: worker/service role only.

Ordinary API requests do not run with an unrestricted service-role connection. Worker privileges are separate and narrow.

### 18.4 Authorization matrix

| Resource/action | Anonymous | League member | Resource owner | League admin | Worker |
| --- | ---: | ---: | ---: | ---: | ---: |
| Public published recap | Read | Read | Read | Read | Read/write job output |
| Private-league facts | No | Read | Read | Read/write config | Sync |
| Draft session | No | No | Read/write | No, unless owner | Job access for owner-scoped work |
| User projection upload | No | No | Read/write | No, unless owner | Import only |
| Shared power rankings | Public if league public | Read | Read | Trigger/publish | Compute |
| Provider credentials | No | No | No direct read | Replace/manage connection | Decrypt for sync |
| League membership | No | Read permitted subset | Own profile/team link | Manage roles | No ordinary mutation |

A commissioner cannot inspect another manager’s private tools merely because they administer the league.

### 18.5 Cost and abuse controls

The architecture includes a `usage_ledger` from the start, even without billing. Record metered actions such as:

- LLM tokens/cost;
- provider refreshes;
- expensive optimization runs;
- projection upload size;
- model inference later.

Rate limits can begin as PostgreSQL-backed counters or application limits. Redis is introduced only if multi-instance rate limiting becomes a measured problem.

## 19. API design

### 19.1 Style

Use versioned REST JSON under `/api/v1`. IDs are FCP IDs. Provider IDs do not appear as primary resource identifiers.

Examples:

```text
GET  /api/v1/me/leagues
POST /api/v1/leagues
GET  /api/v1/leagues/{league_id}
GET  /api/v1/leagues/{league_id}/seasons/{season_id}
GET  /api/v1/leagues/{league_id}/periods/{period_id}/matchups
GET  /api/v1/leagues/{league_id}/standings
GET  /api/v1/leagues/{league_id}/newsroom

POST /api/v1/me/projection-imports
GET  /api/v1/me/projection-datasets
POST /api/v1/me/leagues/{league_id}/projection-scenarios

POST /api/v1/me/leagues/{league_id}/draft-sessions
POST /api/v1/me/draft-sessions/{session_id}/picks
POST /api/v1/me/draft-sessions/{session_id}/plans

POST /api/v1/leagues/{league_id}/newsroom/fact-packages
POST /api/v1/leagues/{league_id}/recap-editions/{edition_id}/publish

GET  /api/v1/jobs/{job_id}
```

The `/me` namespace is not the security mechanism; it makes ownership visible to clients and developers. Authorization is still enforced in application policies and RLS.

### 19.2 Contracts

- Request and response schemas are explicit and versioned.
- The frontend client is generated from OpenAPI in CI.
- CI fails if generated client changes are uncommitted or if contract tests fail.
- Lists use cursor pagination where unbounded.
- Mutating commands accept idempotency keys where retries are likely.
- Versioned resources use `If-Match`, an explicit version, or both.
- Errors use stable machine-readable codes plus safe user messages.
- Provider/LLM error details are redacted from public responses.

### 19.3 Read models

The API may assemble feature-focused read models, such as League Home, rather than forcing the browser to issue ten requests and reproduce domain joins. A read model remains typed, contains freshness metadata, and is built from canonical data.

## 20. Caching

### 20.1 Primary rule

PostgreSQL holds the last known normalized state. Normal page reads do not call ESPN synchronously. Provider calls happen in jobs, and the UI receives the latest durable state plus freshness metadata.

### 20.2 Cache layers

1. **Provider request coalescing** inside a sync job to avoid duplicate upstream calls.
2. **Normalized PostgreSQL state** as the durable application read source.
3. **Analysis result cache** keyed by deterministic input fingerprint and methodology version.
4. **In-process short TTL cache** for safe reference/configuration reads.
5. **HTTP caching/ETags** for public league and newsroom reads.
6. **CDN caching** for static assets and explicitly public published content.

Do not add Redis initially. Add it only when multiple API instances need a measured shared-cache, lock, or rate-limit capability that PostgreSQL cannot comfortably serve.

### 20.3 Staleness behavior

Stale data is returned with `stale=true` when usable. The API can enqueue a refresh but does not hold an ordinary page request open for a slow ESPN reconstruction. If no valid state exists, it returns an honest typed unavailable state.

## 21. Deployment

### 21.1 Initial production topology

Use:

- Supabase managed PostgreSQL, Auth, and private Storage;
- one modest VPS or simple container platform;
- Caddy for TLS, static frontend, compression, and reverse proxy;
- one API container;
- one worker container from the same Python image;
- one scheduler invocation from the worker or host cron;
- automated database backups and object-storage lifecycle policy.

This is enough for hundreds or thousands of users if queries and jobs are well designed.

### 21.2 Stateless application containers

No authoritative data lives in the API or worker filesystem. Containers can be recreated safely. Temporary upload processing uses bounded scratch space and deletes it after the artifact is persisted.

### 21.3 Delivery pipeline

1. Run domain, integration, security, frontend, and end-to-end tests.
2. Build immutable frontend and Python images/artifacts.
3. Validate migrations against a clean database and a production-like previous schema.
4. Back up production database.
5. Apply forward-compatible migrations.
6. Deploy API and worker.
7. Run smoke checks including database, auth validation, job claiming, and one non-live provider fixture path.
8. Surface deployment version in health/readiness endpoints.

Use separate liveness and readiness checks. Readiness verifies database connectivity and required configuration without calling ESPN on every probe.

## 22. Observability

### 22.1 Structured telemetry

Emit structured JSON logs with:

- request ID;
- trace ID;
- authenticated user ID where appropriate and safe;
- league ID;
- job ID and type;
- provider and capability;
- duration;
- result status;
- data freshness;
- retry count;
- methodology version.

Secrets, provider cookies, uploaded source rows, and private strategy content are never logged.

### 22.2 Metrics and alerts

Track:

- API request rate, p50/p95/p99 latency, and error rate;
- job queue depth, oldest due job, runtime, retries, and dead jobs;
- league freshness lag by capability;
- ESPN success, timeout, authentication failure, and rate-limit rates;
- projection import match/ambiguous/unmatched rates;
- LLM request count, latency, validation failure, tokens, and estimated cost;
- optimization runtime and infeasible-plan rate;
- database pool saturation and slow queries.

Initial tooling can be hosted error monitoring plus a metrics endpoint and simple dashboards. OpenTelemetry-compatible instrumentation keeps future options open without requiring a full observability platform on day one.

### 22.3 Audit log

Security- and publication-relevant actions are durable:

- league creation and provider connection replacement;
- membership and role changes;
- private projection upload deletion;
- recap generation and publication;
- manual historical corrections;
- player identity merges;
- administrative job triggers.

## 23. Testing strategy

### 23.1 Domain tests

Fast pure tests for:

- category direction;
- ratio aggregation from makes/attempts;
- standings reconstruction;
- all-play math;
- schedules and games-in-window;
- projection adjustment composition;
- valuation and replacement level;
- draft constraints and invariants;
- deterministic awards and fact-package construction.

Use property-based tests for invariants such as:

- swapping home and away swaps results;
- adding makes and attempts aggregates ratios correctly;
- lower-is-better categories reverse comparisons;
- finalized standings equal the sum of finalized matchup category results;
- applying no projection adjustments returns the base dataset unchanged;
- a user cannot receive a plan containing an unavailable player.

### 23.2 Provider contract tests

Each adapter has sanitized raw fixtures and tests that assert normalized commands, identities, time semantics, missing fields, and error classification. The same provider capability suite can be applied to future Yahoo/Sleeper adapters.

Limited live smoke tests run manually or on a controlled schedule, never on every PR.

### 23.3 Database and RLS tests

Run against real PostgreSQL/Supabase locally:

- schema constraints;
- transaction rollback;
- migration forward paths;
- job lease/retry behavior;
- every row-level security policy;
- a cross-user/cross-league access matrix;
- service-role separation;
- private projection and Draft Room isolation.

Security tests must attempt forbidden reads and writes through the same API path production uses.

### 23.4 API contract tests

- OpenAPI schema snapshot.
- Generated TypeScript client compilation.
- response-envelope and freshness semantics.
- idempotency behavior.
- optimistic concurrency conflicts.
- typed upstream unavailable states.
- authorization policy tests at use-case and HTTP levels.

### 23.5 Frontend tests

- unit tests for formatters and view-model transforms;
- component tests for shared/private states and honest empty/stale states;
- accessibility tests for core screens;
- Playwright end-to-end flows for login, joining a league, viewing shared facts, uploading private projections, using Draft Room, and generating/publishing a recap;
- an explicit two-user privacy scenario proving one league member cannot access another’s strategy.

### 23.6 Algorithm adoption tests

Before porting an existing algorithm, capture representative golden inputs and outputs, then add correctness cases designed to expose known risks. Preserve behavior only where it is intentional. Golden tests are evidence, not a command to retain bugs.

## 24. Repository and file structure

```text
fcp/
├── apps/
│   └── web/
│       ├── src/
│       │   ├── app/
│       │   ├── api/
│       │   ├── auth/
│       │   ├── league-world/
│       │   ├── newsroom/
│       │   ├── manager-lab/
│       │   └── shared/
│       └── tests/
│
├── server/
│   ├── pyproject.toml
│   ├── src/fcp/
│   │   ├── api/                  FastAPI entry and cross-cutting HTTP
│   │   ├── worker/               job runner and scheduler
│   │   ├── identity/
│   │   ├── players/
│   │   ├── leagues/
│   │   ├── integrations/
│   │   │   ├── fantasy/
│   │   │   │   ├── port.py
│   │   │   │   └── espn/
│   │   │   ├── nba/
│   │   │   └── llm/
│   │   ├── projections/
│   │   ├── intelligence/
│   │   │   ├── categories/
│   │   │   ├── schedules/
│   │   │   ├── valuation/
│   │   │   ├── matchups/
│   │   │   └── optimization/
│   │   ├── newsroom/
│   │   ├── draft_room/
│   │   ├── jobs/
│   │   └── infrastructure/
│   │       ├── db/
│   │       ├── storage/
│   │       └── telemetry/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       ├── contracts/
│       └── security/
│
├── migrations/
├── docs/
│   ├── architecture/
│   │   ├── overview.md
│   │   ├── data-ownership.md
│   │   ├── freshness.md
│   │   └── authorization.md
│   ├── decisions/                short ADRs
│   └── product/
├── deploy/
├── scripts/                      thin operational entrypoints only
├── tests/e2e/
└── Makefile or justfile          discoverable common commands
```

### Comprehensibility rules

- Each module has a short README naming its entities, tables, public use cases, and dependencies.
- `docs/architecture/data-ownership.md` lists every table by scope: platform, league, user, service.
- `docs/architecture/freshness.md` lists every major read model and refresh policy.
- There is no generic `utils.py`, giant API client, or universal data-feed module.
- Import boundaries are checked in CI.
- Provider types cannot be imported by League Domain, Projections, Intelligence, Newsroom, or Draft Room.
- Private feature modules cannot publish league-shared output without an explicit application use case and permission.

## 25. Important end-to-end data flows

### 25.1 Connect and synchronize an ESPN league

```text
authenticated user
  → validate ESPN connection
  → ESPN adapter returns provider preview
  → user confirms
  → one DB transaction creates:
       League
       LeagueSeason
       owner Membership
       ProviderConnection secret reference
       ProviderLeagueBinding
  → durable initial-sync job
  → ESPN adapter fetches provider payloads
  → normalizer resolves teams/managers/players
  → canonical facts committed
  → shared analytics jobs enqueued
  → API serves normalized league state with data_as_of
```

### 25.2 Upload private Basketball Monster projections

```text
user
  → private signed upload URL
  → encrypted object storage
  → import job
  → BBM adapter parses source rows
  → player resolver maps to FCP IDs
  → immutable user-private dataset + import issues
  → user selects dataset for Draft Room
  → no league member or commissioner can read the file or lines
```

### 25.3 Compute a private Draft Room plan

```text
authorized owner requests plan
  → load league rules and current available-player facts
  → load owner's selected projection dataset/scenario
  → load owner's draft session/preferences/picks
  → call pure optimization engine
  → persist owner-private plan with input fingerprint/session version
  → return result only to owner
```

### 25.4 Publish a weekly recap

```text
period finalized
  → deterministic shared analytics complete
  → immutable fact package built with evidence IDs
  → admin requests editorial generation
  → metered LLM job receives only approved shared facts
  → structured output validated
  → draft edition saved
  → admin publishes transactionally
  → league members/public readers see edition according to league visibility
```

### 25.5 View Week 7 in a later season

```text
request historical period
  → finalized Matchup + CategoryResult records
  → period-end RosterSnapshots
  → transactions with occurred_at inside/cumulative through cutoff
  → analysis run whose data_as_of matches the period
  → published fact package/edition version
```

No current ESPN roster or rolling snapshot is used implicitly.

## 26. Initial vertical slice and deliberate omissions

The first rebuilt vertical slice should prove the architecture rather than implement every constitutional possibility.

It should contain:

- Supabase authentication;
- multi-league membership and explicit shared/private authorization;
- canonical players with ESPN and NBA identity mapping;
- one ESPN provider adapter;
- normalized league, season, teams, rules, current roster, matchups, and transactions;
- durable current and completed-period history;
- shared league home, matchup, standings, and Newsroom fact package;
- versioned recap generation/publication;
- one private projection upload path;
- private Draft Room sessions using a selectively ported optimizer;
- durable jobs and freshness metadata;
- deployment, monitoring, and cross-user isolation tests.

It should not contain Yahoo, Sleeper, billing, streaming, trades, chat, mobile applications, generalized sports, real-time play-by-play, a first-party production model, or a separate analytics platform.

This vertical slice exercises both product pillars and the shared Intelligence layer without building speculative features.

## 27. Comparison with the current repository

The labels below apply to the **current subsystem or implementation**. The “preserve” column distinguishes concept, algorithm, data model, and implementation.

| Current subsystem or concept | Classification | Preserve | Rationale / target treatment |
| --- | --- | --- | --- |
| Dual product pillars: league experience + private tools | **KEEP** | Concept | The Product Constitution makes this the product’s identity. Make it explicit in modules, routes, and access scopes. |
| Python numerical/domain stack | **KEEP** | Implementation technology | Python remains the best fit for CVXPY, modeling, ingestion, and current domain IP. |
| FastAPI | **KEEP BUT CLEAN UP** | Implementation technology | Retain as a thin typed HTTP boundary; replace current route/business/data-access mixing. |
| React + TypeScript + Vite | **KEEP BUT CLEAN UP** | Implementation technology | Appropriate and operationally simple; rebuild feature organization and contracts. |
| React Router and TanStack Query | **KEEP BUT CLEAN UP** | Concept and technology | Retain server-state and routing approach with shared/private route separation and generated types. |
| Current frontend route information architecture | **REFACTOR** | Selected concepts | Preserve league slug navigation, Newsroom, standings, matchup, and Draft Room surfaces; make private routes explicit and remove default-league ambiguity. |
| `frontend/src/api.ts` hand-written universal client | **REPLACE** | Nothing material | Replace with generated OpenAPI client plus feature-owned query hooks. |
| Browser direct access to application Supabase tables | **REPLACE** | Supabase Auth only | All application data goes through API authorization; retain browser auth session handling. |
| Large frontend pages/components | **REPLACE** | Selected UI behavior | Rebuild as feature slices and view components; do not port monolith structure. |
| Emerging `src/ui` primitives | **KEEP BUT CLEAN UP** | Selected implementation | Evaluate individual accessible primitives; establish one design system and delete duplicates. |
| Supabase Auth | **KEEP** | Concept and implementation service | Suitable for expected scale; validate JWTs locally in backend. |
| Membership and invite concepts | **KEEP BUT CLEAN UP** | Concept and selected policy logic | Preserve roles, invitations, redemption locking, and self-service flows; replace duplicate owner/admin authority and schema flaws. |
| Current RLS policy work | **KEEP BUT CLEAN UP** | Security concepts/tests | Preserve defense-in-depth intent and useful policy tests; redesign policies around all application data and private ownership. |
| Slug middleware + `ContextVar` league credentials | **REPLACE** | Slug route convenience only | Resolve an FCP league ID through application use cases; credentials belong to provider bindings, not ambient context. |
| Global/default league fallbacks | **DELETE** | Nothing | They violate fundamental multi-league semantics and hide missing context. |
| `backend/league/data_feed.py` | **REPLACE** | Individual formulas after review | Split provider acquisition, normalization, canonical repositories, and intelligence. Do not preserve the universal module. |
| `MyLeague` / `WeeklyScoreboard` domain work | **REFACTOR** | Algorithms and test fixtures | Extract all-play, schedule, and standings logic into canonical pure services; remove ESPN object and IO coupling. |
| Category direction rules | **KEEP BUT CLEAN UP** | Concept and tests | Make them data-driven scoring rules; retain proven lower-is-better behavior and strengthen ratio tests. |
| Historical standings reconstruction | **KEEP BUT CLEAN UP** | Algorithm/concept | Preserve its intent and validated math; run it from canonical finalized results rather than JSON snapshots. |
| ESPN gateway timeout/error hardening | **KEEP BUT CLEAN UP** | Implementation and policy | It is genuinely good. Move it wholly inside the ESPN adapter and add rate/fixture contracts. |
| ESPN request/TTL/single-flight cache | **REFACTOR** | Concept | Retain request coalescing where useful; move normal reads to durable normalized state and provider work to jobs. |
| ESPN as internal league model | **REPLACE** | ESPN as first adapter | Provider DTOs stop at the normalization boundary. |
| Current league credential encryption RPC | **REFACTOR** | Encrypted-at-rest concept | Use provider connections and managed secret references/key management with narrow worker access. |
| `RecapStore` manual PostgREST gateway | **REPLACE** | Nothing beyond repository need | Replace with transactional typed repositories located with owning modules. |
| Current Supabase schema as a whole | **REPLACE** | Selected constraints and publication function concepts | Build normalized canonical facts and explicit ownership. Do not evolve the JSON snapshot schema into the target. |
| `league_state_snapshots` rolling JSON phases | **DELETE** | Freshness/read-model concept only | Canonical tables hold latest durable state; typed read models and metadata replace phase blobs. |
| Per-week scoreboard and transaction snapshots | **REFACTOR** | Immutable historical concept | Replace JSON payload tables with canonical matchups, results, transactions, and roster snapshots. |
| Versioned recap fact snapshots | **KEEP BUT CLEAN UP** | Concept/data lifecycle | Recast as validated immutable Newsroom fact packages with evidence references. |
| Recap edition versioning, publish, rollback | **KEEP BUT CLEAN UP** | Concept and selected DB invariants | Preserve atomic one-published-edition semantics and history in the new schema. |
| `assemble_weekly_snapshot` orchestration | **REPLACE** | Canonicalization/quality ideas | Replace the coupled implementation with fact-package use cases over canonical data. Port only validated transformations. |
| Deterministic award selection | **KEEP BUT CLEAN UP** | Algorithm and concept | Preserve and version after correcting any category/input issues. |
| Structured LLM recap generation | **KEEP BUT CLEAN UP** | Concept, schemas, provider abstraction | Move to durable metered jobs; retain validation and fact/prose separation. |
| Legacy commentary endpoints | **DELETE** | Potential prompt ideas only | Unauthenticated parallel generation paths conflict with the Newsroom model and cost controls. |
| `PlayerProjection` canonical adapter shape | **KEEP BUT CLEAN UP** | Concept and much of data shape | Add FCP player IDs, explicit temporal bounds, makes, ownership, provenance, and immutable dataset identity. |
| ESPN projection adapter | **REFACTOR** | Parsing/calculation logic | Make it a projection-source adapter over canonical player mappings; remove ambient league context. |
| BBM and Hashtag adapters | **KEEP BUT CLEAN UP** | Adapter algorithms/fixtures | Port parsers into private import jobs with durable identity resolution and licensing scope. |
| Local Parquet/manifest `ProjectionStore` | **REPLACE** | Immutable dataset/version concept | Use PostgreSQL and private object storage; no global active horizon or ephemeral container state. |
| Global active projection selection | **DELETE** | Selection concept only | Replace with per-user, per-league, per-context preferences and a separate shared methodology policy. |
| Projection accuracy evaluation | **KEEP BUT CLEAN UP** | Algorithm/concept | Run against durable dataset versions and finalized canonical outcomes; preserve honest unscoreable states. |
| NBA API ingestion and CSV backfill | **KEEP BUT CLEAN UP** | Adapters, retry policy, fixtures | Integrate with canonical player IDs, durable jobs, source versions, and observable import runs. |
| SQLite consistency database | **REPLACE** | Statistical idea subject to validation | Store source observations/results durably in PostgreSQL or reproducible artifacts; validate the confidence model before porting. |
| Draft optimizer CVXPY engine | **KEEP BUT CLEAN UP** | Algorithm | High-value domain IP. Extract pure inputs/outputs, remove IO/config, add solver/invariant tests, and version methodology. |
| Diverse draft strategies | **KEEP BUT CLEAN UP** | Algorithms | Port individually after quality evaluation; make preferences user-private and explicit. |
| Monte Carlo category targets | **KEEP BUT CLEAN UP** | Algorithm | Preserve after deterministic seed, input, performance, and correctness tests. |
| Forge Value | **KEEP BUT CLEAN UP** | Concept/algorithm | Treat as a versioned valuation methodology in Intelligence, not UI/API glue. |
| Auction simulation | **KEEP BUT CLEAN UP** | Algorithm | Preserve as an optional private analysis with bounded resource use. |
| Personal global do-not-draft list and position override | **DELETE** | User-preference concept only | Recreate as owner-private preferences and canonical eligibility data. |
| Client-only Draft Room persistence | **REPLACE** | Responsive local editing behavior | Use private server-side versioned sessions with optimistic UI; local storage may cache, never own. |
| Legacy `/optimizer/*` endpoints | **DELETE** | Optimizer algorithm lives elsewhere | Expose one private Draft Room application API. |
| Current 15-minute snapshot worker | **REFACTOR** | Scheduled refresh, failure isolation, backfill concepts | Replace with durable capability-specific jobs, cursors, idempotency, freshness targets, and canonical writes. |
| FastAPI in-process initial refresh | **DELETE** | Immediate scheduling intent | Enqueue a durable initial-sync job transactionally. |
| Hardcoded 2025–26 matchup calendars | **DELETE** | Schedule-window concept | Calendar periods come from normalized provider/league season data. |
| Current Docker/Caddy/VPS topology | **KEEP BUT CLEAN UP** | Deployment shape | Add stateless API/worker containers, durable external storage, readiness, backups, and one authoritative deployment path. |
| `render.yaml` alternative deployment | **DELETE** | Nothing if VPS remains authoritative | One production topology avoids configuration drift. |
| Current test suite | **KEEP BUT CLEAN UP** | Domain fixtures, algorithms, RLS intent | Carry forward high-value behavioral tests; replace mocks that encode broken schemas and add integration/E2E/privacy coverage. |
| Current docs/specification history | **KEEP BUT CLEAN UP** | Product knowledge | Preserve as archive/decision evidence; create concise authoritative architecture and ownership docs. |
| Giant comments carrying PR history in code | **DELETE** | Decisions worth retaining move to ADRs | Production modules should explain invariants, not narrate project chronology. |

## 28. What survives the rebuild

### Preserve as concepts

- Shared League World and private Manager Lab.
- Deterministic Newsroom facts followed by generated prose.
- Projection source adapters and explicit horizons.
- Immutable projection sets and accuracy measurement.
- Immutable historical week facts.
- Draft plans, strategies, targets, and relaxation.
- Honest empty/stale states.
- Worker failure isolation.

### Preserve as algorithms, after verification

- auction roster optimization;
- diverse strategy generation;
- Monte Carlo category targets;
- Forge Value;
- auction simulation;
- all-play calculations;
- historical standings reconstruction;
- category comparison rules;
- deterministic awards;
- projection normalization;
- projection accuracy scoring;
- selected schedule calculations.

### Preserve selected implementation

- Python numerical stack;
- FastAPI as HTTP technology;
- React/TypeScript/Vite;
- Supabase Auth/PostgreSQL/Storage;
- ESPN timeout/error gateway techniques;
- some projection parser code and fixtures;
- recap structured-output validation patterns;
- atomic recap publication semantics;
- useful tests.

### Do not preserve as target structure

- the present database schema;
- manual PostgREST store;
- giant data-feed and API modules;
- ambient slug/provider context;
- global projection state;
- browser-direct application data access;
- client-only private persistence;
- rolling JSON phase snapshots;
- hardcoded league/season defaults;
- unauthenticated cost-bearing endpoints;
- ephemeral production file stores.

## 29. Decisive recommendation

### Chosen option

**4. Preserve domain logic but rebuild the application around it.**

### Why not continue or selectively refactor in place

The current application’s most consequential problems are structural, not cosmetic:

- provider objects and provider timing leak into product code;
- shared and private ownership are not consistently modeled or enforced;
- application data access is split between browser RLS and a service-role backend;
- canonical players, teams, rosters, matchups, and transactions do not exist as durable domain entities;
- projections are global and filesystem-backed despite being private, user-selectable product inputs;
- current, historical, recap, and snapshot meanings overlap;
- normal deployment recreates authoritative local state;
- the core user-private Draft Room is client-authoritative;
- API contracts have drifted across hand-written layers.

Correcting those issues in place would require touching nearly every persistence and application boundary while preserving compatibility with structures that the target no longer wants. That path would spend complexity on transition rather than product quality, and migration effort has explicitly been declared irrelevant.

### Why not discard everything

A full greenfield restart that ignores current domain work would throw away tested and potentially differentiated logic. The auction optimizer, strategies, Monte Carlo targets, valuation, all-play calculations, historical standings, recap fact discipline, projection normalization, accuracy evaluation, and ESPN hardening deserve individual evaluation.

Their surrounding IO, global configuration, schemas, and route coupling are not reasons to discard the underlying mathematics or concepts.

### The recommended rebuild shape

Begin from an empty target application and database schema. Implement the canonical identity, league, provider, projection, ownership, history, and job boundaries first. For each current domain capability:

1. define its canonical target inputs and outputs;
2. build correctness and invariant tests independent of the old implementation;
3. run the current algorithm against representative fixtures;
4. port it when it is correct and valuable;
5. rewrite or discard it when it is not.

This is a **greenfield application architecture with selective domain-IP transplantation**.

It produces the best FCP because it aligns the system directly with the Product Constitution:

- the League World is shared and historically durable;
- the Manager Lab is private by construction;
- Basketball Intelligence is reusable and provider-independent;
- projections are first-class, user-selectable, adjustable, and license-aware;
- ESPN is the first adapter rather than the domain;
- canonical player identity belongs to FCP;
- freshness and methodology are visible;
- the Newsroom remains factual and auditable;
- operational complexity stays appropriate to hundreds or thousands of users.

That is the target architecture I would choose if FCP began today, and it is also the architecture I recommend building now.

---

This exercise ends at target design and architectural recommendation. It does not authorize implementation or modification of application code.
