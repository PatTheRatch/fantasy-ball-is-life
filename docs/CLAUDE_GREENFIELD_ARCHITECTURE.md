# FCP Target Architecture

**Phase:** Architecture. Design and recommendation only — no code changes.
**Authority:** [`PRODUCT_CONSTITUTION.md`](PRODUCT_CONSTITUTION.md) governs. Where the audit's inferred vision conflicts, the constitution wins.
**Inputs:** [`CLAUDE_FCP_AUDIT.md`](CLAUDE_FCP_AUDIT.md) (forensic findings), [`CONSTITUTION_TRACEABILITY.md`](CONSTITUTION_TRACEABILITY.md) (clause-by-clause gap analysis), [`GREENFIELD_EXERCISE.md`](GREENFIELD_EXERCISE.md) (brief).

**Bottom line up front:** **Option 4 — preserve the domain logic, rebuild the application around it.** New repository skeleton, new application architecture, with roughly 4,000 lines of genuinely good basketball IP ported in deliberately, module by module, each stripped of its infrastructure dependencies and covered by tests as it lands. Reasoning in [Part C](#part-c--recommendation).

---

# Part A · The greenfield design

*Written as if FCP did not exist and the constitution were the only input.*

## A0 · The three decisions everything else follows from

Before any diagram, three choices do most of the work. Each is forced by a specific clause.

**1. A canonical FCP domain sits between providers and features (§7, §8).** Nothing above the provider boundary ever sees an ESPN object or a player name as a key. This single rule kills the ESPN subclassing, the four fuzzy-match paths, and the Yahoo-is-a-rewrite problem simultaneously.

**2. Basketball intelligence is a pure library, parameterized per call (§4, §5).** Not a service, not a singleton reading ambient state. Every domain function takes its projection view as an argument. This is what lets the *same* code produce league-shared numbers (pinned default source) and private numbers (the user's source plus their adjustments) without two implementations.

```
shared  → compute(facts, source = league.default_source, adjustments = ∅)
private → compute(facts, source = user.preferred_source, adjustments = user.adjustments)
```

**3. Week finality is a first-class concept (§10, §11).** A league week is `scheduled` → `in_progress` → `final`. Once final, its rows are immutable and never refetched. This one idea replaces three snapshot tables, makes every read path's freshness self-evident, and makes historical questions answerable by construction rather than by reconciliation.

---

## A1 · Overall system architecture

A **modular monolith**: one codebase, two processes, one database. Constitution §16 (hundreds to thousands, not millions) and §20 (boring and explicit; no queues or microservices for fashion) both point here, and nothing in the workload argues otherwise.

```
                        ┌──────────────────────────────┐
   Browser ──────────►  │  Caddy  (TLS, static, /api)  │
                        └──────────────┬───────────────┘
                                       │
                        ┌──────────────▼───────────────┐
                        │   fcp-api   (FastAPI, N=1+)  │
                        │   stateless — no local disk  │
                        └──────────────┬───────────────┘
                                       │
   ┌───────────────────────────────────┼────────────────────────────────┐
   │                                   │                                │
┌──▼───────────────┐        ┌──────────▼──────────┐        ┌────────────▼────────┐
│    PostgreSQL    │◄───────┤   fcp-worker (N=1)  │───────►│  External providers │
│  single source   │        │  polls job queue    │        │  ESPN / NBA / LLM   │
│    of truth      │        │  SKIP LOCKED        │        └─────────────────────┘
└──────────────────┘        └─────────────────────┘
```

**Properties that matter:**

- **The API is stateless and has no local disk.** Every piece of durable state is in Postgres. This is the direct fix for the audit's highest-severity finding — uploads and benchmark snapshots destroyed on every `--force-recreate`.
- **The worker is a separate process, not an HTTP endpoint.** Refresh becomes N small per-league jobs rather than one 900-second synchronous request looping every league.
- **No Redis, no Celery, no message broker.** A Postgres job queue using `SELECT … FOR UPDATE SKIP LOCKED` is durable, transactional with the data it produces, requires zero new infrastructure, and comfortably handles thousands of leagues at 15-minute cadence. Adding a broker later is a contained change if it is ever justified; adding one now is complexity without a reason (§20).
- **No application cache tier.** With final weeks stored and immutable, the hot reads are indexed Postgres queries over small tables. The current system's four bespoke caches exist to avoid re-fetching ESPN inside a request; once nothing fetches inside a request, they have no purpose.

### Identity provider

Keep **Supabase Auth** (GoTrue) for identity only — signup, login, password reset, email delivery. Replacing identity is undifferentiated work and the existing auth surfaces are good.

But **stop using Supabase as an application data path.** No PostgREST, no service-role key, no browser→database access. Two consequences, both required by §17:

- JWTs are verified **locally against the JWKS** rather than by an HTTP round trip to `/auth/v1/user` per request.
- There is exactly **one** authorization model (the application's), instead of RLS for the browser path and ad-hoc checks for the API path with a service-role key that bypasses RLS entirely.

Postgres may still be Supabase-hosted — it is competent managed Postgres. The change is architectural, not vendor.

---

## A2 · Canonical domain model

The entities FCP owns, independent of any provider. This is the answer to §21's first six questions.

### Identity and tenancy

```
users                    FCP account. auth_subject (from IdP), email, display_name.
players                  THE canonical player. fcp_player_id (uuid). Never a name.
player_external_ids      (player_id, source, external_id) UNIQUE(source, external_id)
                         source ∈ {nba, espn, yahoo, sleeper, bbm, hashtag}
player_aliases           (player_id, normalized_name, source, confidence,
                          resolved_by, resolved_at) — ingest-time resolution, audited
player_alias_queue       unresolved names awaiting review. Never silently dropped.
```

`players` is the keystone. §8 says names must not be the canonical join key; `player_external_ids` is how every source maps in, and `player_aliases` is how fuzzy matching becomes a **one-time, recorded, reversible ingest decision** instead of a repeated query-time guess with four different thresholds.

### Fantasy domain (provider-neutral)

```
leagues                  fcp_league_id, provider, provider_league_id, season,
                         name, slug, visibility, timezone, default_projection_source_id
league_connections       league_id, provider, encrypted_credentials, status,
                         last_verified_at        ← separate from `leagues`
league_settings          league_id, season, scoring_type, categories[], roster_slots,
                         playoff_team_count, reg_season_weeks, acquisition_budget
league_weeks             league_id, season, week, start_date, end_date,
                         status ∈ {scheduled, in_progress, final}   ← DERIVED, never typed
fantasy_teams            league_id, team_id, name, provider_team_id, logo
league_members           league_id, user_id, role ∈ {owner,admin,member},
                         fantasy_team_id NULL   ← the anchor for all private data
matchups                 league_id, season, week, home_team_id, away_team_id,
                         status, winner_team_id, provider_winner
matchup_categories       matchup_id, category, home_value, away_value, result
roster_slots             league_id, team_id, as_of_date, player_id, slot, injury_status
transactions             league_id, week, occurred_at, type, player_id,
                         from_team_id, to_team_id, bid_amount, group_id
```

Two things worth calling out:

- **`league_weeks` is derived from provider settings and stored per league**, replacing the hand-typed 22-week calendar duplicated across Python and TypeScript. Its `status` column is the finality concept from A0.
- **`league_members.fantasy_team_id`** is what makes §2 ("one league may contain multiple FCP users") and §3 (private data) work. Every private row hangs off `(user_id, league_id)`.

### NBA source data

```
nba_teams                team_id, abbreviation, name
nba_games                game_id, date, home_team_id, away_team_id, season
nba_player_seasons       player_id, season, gp, gs, minutes, mpg,
                         fgm, fga, ftm, fta, tpm, tpa, tov, usg_pct,
                         pts, reb, ast, stl, blk, team_pace, team_ortg
nba_player_games         player_id, game_id, date, minutes, <9-cat + makes/attempts>
nba_player_bio           player_id, dob, height, weight, position,
                         draft_year, draft_round, draft_pick, experience
```

`nba_player_games` is **new and fills a real gap**: it is what the current `data/game_logs.db` SQLite file was supposed to be — the file that is gitignored, absent from the container, created by nothing in the repo, and whose absence makes `/confidence` and `/matchup-confidence` return 500 in production. Consistency and confidence become first-class, durable, and computable.

All NBA tables key on `players.player_id`, with `person_id` living in `player_external_ids`.

### Projections — source × horizon × adjustments as three separate things (§5)

```
projection_sources       source_id, key, name,
                         kind ∈ {fcp_model, provider_live, upload},
                         license ∈ {redistributable, user_licensed}
projection_sets          set_id, source_id, horizon, season, week NULL,
                         scope ∈ {global, league, user},
                         owner_user_id NULL, league_id NULL,
                         status, created_at, frozen_at      ← IMMUTABLE once frozen
projection_rows          set_id, player_id, games, minutes,
                         fgm, fga, ftm, fta, tpm, tov,
                         pts, reb, ast, stl, blk, value, injury_status
projection_adjustments   user_id, player_id, season, field,
                         mode ∈ {absolute, multiplier}, value, note
                         ← LAYERED, never mutates the source
user_projection_prefs    user_id, league_id, horizon, source_id
```

Four properties, each mapping to a clause:

| Property | Clause |
|---|---|
| `projection_rows` carries **makes and attempts**, never bare percentages | Existing design; preserved verbatim |
| Sets are **immutable once frozen** — "what did ESPN project in week 7" is answerable forever | §10, and the whole point of the accuracy scoreboard |
| `license` distinguishes redistributable from user-licensed | §5's BBM constraint — a `user_licensed` set can never back league-shared output |
| Adjustments compose at read time and never overwrite | §5 explicitly |

Resolution is one pure function:

```python
def resolve_projections(
    *, season: int, horizon: Horizon,
    source: ProjectionSource,
    adjustments: Sequence[Adjustment] = (),
) -> ProjectionView:
    ...
```

`ProjectionView` is an immutable, player_id-keyed lookup. Every downstream domain function takes one as a parameter. Nothing reads "the active projections" from global state.

### Derived and private

```
-- derived, recomputable, league-shared
power_rankings           league_id, season, week, computed_at, payload
standings                (not stored — a deterministic fold over final weeks)
projection_accuracy      league_id, season, week, source_id, category, mae, bias, rho

-- newsroom (preserved from the current design)
recap_facts              league_id, season, week, version, frozen_at, facts_json
recap_editions           league_id, season, week, version, facts_id, status,
                         content_json, created_by, published_at

-- private to a user (§3) — none of this exists today
draft_sessions           user_id, league_id, config_json, status, created_at
draft_picks              session_id, pick_no, player_id, price, is_user
draft_plans              session_id, plan_id, label, config_json, roster_json, health
user_watchlists          user_id, league_id, player_id, note
user_player_notes        user_id, player_id, body
user_do_not_draft        user_id, league_id, player_id
user_league_prefs        user_id, league_id, games_per_week, min_games_filter, …
```

The last block is the largest net-new build the constitution implies. Note that `user_do_not_draft` and `user_league_prefs` are the per-user, per-league homes for what are currently **process-global environment variables** shared by every league on the deployment.

---

## A3 · Player identity model (§8)

The single most important structural change, because it is the join key for the entire domain.

```
ingest payload
      │
      ▼
┌─────────────────────┐   hit    ┌──────────────────────┐
│ external id lookup  │─────────►│  players.player_id   │
│ (source, ext_id)    │          └──────────────────────┘
└──────────┬──────────┘                     ▲
           │ miss                           │ hit
           ▼                                │
┌─────────────────────┐                     │
│ alias lookup        │─────────────────────┘
│ (normalized_name)   │
└──────────┬──────────┘
           │ miss
           ▼
┌─────────────────────┐  ≥ threshold  ┌────────────────────────────┐
│ fuzzy candidate     │──────────────►│ write alias + external id, │
│ generation          │               │ record confidence + source │
└──────────┬──────────┘               └────────────────────────────┘
           │ below threshold
           ▼
┌────────────────────────────────────────────┐
│ player_alias_queue — surfaced for review,   │
│ counted in data-quality metrics.            │
│ NEVER silently dropped.                     │
└────────────────────────────────────────────┘
```

Rules:

1. **One** `normalize_name` in the domain layer. Not two, not shadowed inside a function.
2. **One** fuzzy threshold, defined once, not four values scattered across four attachment functions.
3. Fuzzy matching runs **only at ingest**, never at query time. Queries join on `player_id`.
4. Every resolution is written to `player_aliases` with its confidence and origin — auditable and reversible.
5. Unmatched names land in a queue and appear on the status page. Silent drops are the current failure mode and the most insidious one, because the numbers still look plausible.

---

## A4 · Provider normalization and the ESPN boundary (§7)

```
providers/
  base.py                 # Protocol — returns FCP DTOs, never provider objects
  espn/
    client.py             # HTTP only: auth, timeouts, retries, typed errors
    mapper.py             # raw payload → FCP DTOs
    schemas.py            # provider-shaped models, never leave this package
  yahoo/     (later)
  sleeper/   (later)
```

The contract:

```python
class FantasyProvider(Protocol):
    def fetch_settings(self, conn: Connection, season: int) -> LeagueSettingsDTO: ...
    def fetch_teams(self, conn: Connection, season: int) -> list[TeamDTO]: ...
    def fetch_weeks(self, conn: Connection, season: int) -> list[WeekDTO]: ...
    def fetch_matchups(self, conn: Connection, week: int) -> list[MatchupDTO]: ...
    def fetch_rosters(self, conn: Connection, on: date) -> list[RosterSlotDTO]: ...
    def fetch_transactions(self, conn: Connection, w: WeekWindow) -> list[TransactionDTO]: ...
    def fetch_player_pool(self, conn: Connection, season: int) -> list[PlayerRefDTO]: ...
```

Three rules that make §7 real:

1. **Never subclass the provider library.** `espn_api` may be used *inside* `espn/client.py` as an HTTP convenience, or dropped for direct calls. Either way its objects never escape the package. The current `MyLeague(League)` and `ScoreboardLeague(League)` — which override the library's *private* loaders — are exactly what this forbids.
2. **Raw payloads are persisted before mapping.**
   ```
   provider_payloads   league_id, provider, endpoint, params_hash,
                       fetched_at, payload jsonb
   ```
   This buys replayability (a mapping bug is fixed and re-run without refetching), free sanitized test fixtures, and an audit trail for §9's "source data" layer. It is cheap and it is the difference between debugging from logs and debugging from evidence.
3. **DTOs are FCP-shaped from the first line of the mapper.** No stage of the pipeline handles an ESPN dict outside `espn/`.

**Adding Yahoo later** is then: implement `yahoo/client.py` + `yahoo/mapper.py`, add an enum value, add credential handling. Zero changes to domain, services, API, or frontend. That is the clause's stated success criterion.

---

## A5 · The basketball intelligence layer (§4)

Pure Python. No database, no HTTP, no config globals, no I/O. Everything takes explicit arguments and returns values.

```
domain/
  categories.py      9-cat definitions, direction, comparison, tie handling
  scoring.py         matchup scoring, all-play / universe wins
  standings.py       deterministic fold over final weeks → standings as of week N
  valuation.py       z-scores, category values, auction values (Forge Value)
  projections.py     resolve_projections(), ProjectionView, adjustment composition
  schedule.py        games in window, playoff weeks, games-per-week
  consistency.py     tier distributions, confidence from game logs
  targets.py         Monte Carlo category targets
  optimizer/
    model.py         cvxpy integer program
    strategies.py    plan diversity / portfolio generation
    engine.py        per-pick health check + selective re-solve
  recap/
    facts.py         deterministic fact assembly
    awards.py        deterministic award computation
```

**The purity rule is what makes §4 true rather than aspirational.** A tool cannot accidentally reinvent player matching or projection resolution if the only way to get numbers is to call a function that demands a `ProjectionView` and a set of `MatchupFacts`.

It also collapses the §4/§5 tension. `power_rankings` for the league newsroom and a private "what if I trade for Sabonis" both call `valuation.category_values(view, …)`; they differ only in which `ProjectionView` they pass.

And it makes the test strategy trivial: the highest-value, most intricate code in the product becomes fast, fixture-light unit tests with no database and no network.

---

## A6 · Application architecture

```
api/          HTTP only: routing, request/response schemas, authz enforcement
services/     use cases: orchestration, transaction boundaries
domain/       pure basketball logic (A5)
repos/        persistence, tenant-scoped by construction
providers/    external adapters (A4)
jobs/         background task definitions
```

Dependency direction is strictly downward: `api → services → domain`, with `services → repos` and `services → providers`. **`domain` imports nothing from the other layers.** A lint rule enforces this in CI; it is the structural guarantee that `data_feed.py` cannot happen again.

### Tenant isolation, made structural (§12, §17)

The current system's failure was not a bad auth design — it was 53 routes where someone forgot to add a check. The fix is to make forgetting impossible rather than to remember harder.

```python
@dataclass(frozen=True)
class LeagueScope:
    user_id: UUID
    league_id: UUID
    role: Role

class LeagueRepo:
    def __init__(self, session: Session, scope: LeagueScope):  # scope REQUIRED
        ...
```

- Repositories that touch league data **cannot be constructed without a `LeagueScope`.** There is no unscoped method to call by accident.
- `LeagueScope` is produced by one FastAPI dependency that resolves membership and role, returning 404 (not 403) for non-members so league existence does not leak.
- Private user data goes through `UserScope`, filtered on `user_id`, with no cross-user accessor in the API at all.
- **Defense in depth:** Postgres RLS stays enabled on multi-tenant tables, with `SET LOCAL app.current_user_id` per transaction. Because there is now exactly one database role and no service-role bypass path, this is a genuine second layer rather than the split-brain the audit found.
- **Authorization matrix test:** a test enumerates every route and asserts an explicit policy exists. A new route with no declared policy **fails CI**. This is the direct structural answer to "53 of 71 routes have no authentication."

---

## A7 · API design

Two namespaces, no third.

```
/api/v1/leagues/{league_id}/...      league-scoped   → requires membership
/api/v1/me/...                       user-scoped     → requires auth, filtered to caller
/api/v1/public/leagues/{slug}/...    explicitly public (published recaps only)
```

**No flat global routes, ever.** The current split — half the API league-scoped, half falling back to "the first league in the database" — is impossible to express in this scheme.

Representative surface:

```
GET  /leagues/{id}/standings?through_week=7      derived from final weeks
GET  /leagues/{id}/weeks                         calendar + finality status
GET  /leagues/{id}/matchups/{week}
GET  /leagues/{id}/power-rankings/{week}
GET  /leagues/{id}/transactions?week=            
GET  /leagues/{id}/recaps                        published archive
POST /leagues/{id}/recaps/{week}/generate        admin
POST /leagues/{id}/recaps/{week}/publish         admin
GET  /leagues/{id}/projection-accuracy

GET  /me/leagues
GET  /me/projection-preferences
PUT  /me/projection-preferences
GET  /me/adjustments
PUT  /me/adjustments/{player_id}
POST /me/leagues/{id}/draft-sessions
POST /me/draft-sessions/{sid}/picks
GET  /me/draft-sessions/{sid}/plans
GET  /me/watchlist
```

Cross-cutting conventions:

- **Every response carries freshness metadata** — `{ data, as_of, freshness: "live" | "synced" | "final", stale: bool }`. §11's requirement that freshness be understandable without reverse-engineering the implementation is satisfied at the wire format, not by convention.
- **Empty states are honest and typed** — `{ data: null, reason: "not_yet_synced" }`, never a 500. This preserves a genuine strength of the current system and generalizes it.
- **OpenAPI is the contract**, and the frontend client is generated from it. This deletes the hand-maintained 1,090-line `api.ts` and the type drift it invites.
- Rate limits and per-user budgets on LLM-invoking endpoints (§17: "not free unlimited LLM usage").

---

## A8 · Persistence, historical data, and freshness

**Postgres only.** SQLAlchemy 2.0 (typed) + Alembic. Connection pooling. Real transactions. No parquet on disk, no SQLite, no PostgREST.

### Week finality drives everything

```
scheduled ──► in_progress ──► final ──► (immutable forever)
```

| Class | Tables | Refresh policy |
|---|---|---|
| **Live** | draft session state, in-progress matchup scores | On request, from cache-free reads |
| **Synced** | current rosters, teams, settings, standings inputs | Job every 15 min |
| **Final** | `matchups`, `matchup_categories`, `transactions` for final weeks, `recap_facts`, frozen `projection_sets`, `nba_player_seasons`, `nba_player_games` | **Never refetched** |

Consequences:

- **Standings as of week N** = a deterministic fold over final weeks 1..N. Never stored as "current," so it cannot go stale or be reconstructed from today's rosters.
- **One `matchups` table** replaces `league_state_snapshots` + `league_week_scoreboards` + `league_week_transactions`. The duplication existed only because the model had no way to say "this week is finished."
- **Recap facts are frozen at generation**, editions reference a facts id, exactly as today.
- Sync cost drops sharply: a mid-season league refetches one week, not twenty-two.

---

## A9 · Jobs and background processing

A Postgres-backed queue. No broker.

```sql
jobs(id, kind, payload jsonb, league_id, run_after, attempts, max_attempts,
     status ∈ {pending,running,succeeded,failed}, locked_by, locked_at,
     last_error, created_at, finished_at)
```

Claim pattern:

```sql
UPDATE jobs SET status='running', locked_by=$worker, locked_at=now()
WHERE id = (
  SELECT id FROM jobs
  WHERE status='pending' AND run_after <= now()
  ORDER BY run_after
  FOR UPDATE SKIP LOCKED
  LIMIT 1
) RETURNING *;
```

Job kinds:

| Kind | Trigger | Idempotent by |
|---|---|---|
| `sync_league_settings` | schedule / on create | upsert on (league, season) |
| `sync_league_week` | schedule | week + finality check |
| `finalize_week` | week end + grace period | status transition guard |
| `ingest_nba_stats` | nightly | upsert on (player, season/game) |
| `snapshot_projections` | weekly | unique (source, horizon, league, week) |
| `compute_power_rankings` | after week sync | upsert on (league, season, week) |
| `generate_recap` | admin request | version increment |
| `resolve_player_aliases` | after any ingest | queue drain |

Properties: **one job per league per unit of work** (not one loop over all leagues); every job idempotent and safely retryable; exponential backoff with a dead-letter status; every run recorded in `job_runs` as queryable operational history. Failure of one league's job never touches another's — preserving the genuine strength of the current worker's failure isolation while removing its 900-second synchronous shape.

---

## A10 · Authentication and authorization

| Concern | Approach |
|---|---|
| Identity | Supabase Auth (GoTrue). Signup, login, reset, email. |
| Token verification | **Local JWKS verification.** No per-request round trip. |
| User record | Own `users` table keyed by `auth_subject`. |
| Session | Short-lived access token + refresh, handled by the SDK client-side. |
| Authorization | Application-layer, via `LeagueScope` / `UserScope` (A6). |
| Defense in depth | Postgres RLS with `SET LOCAL app.current_user_id`. |
| Provider credentials | Encrypted **application-side** (envelope encryption, key in env/KMS), stored in `league_connections`. |
| Admin actions | Role on `league_members`, checked in the service layer, enforced by DB constraint where atomicity matters (as `publish_recap_edition` already does well). |
| Machine access | Signed service tokens for the worker, scoped per job kind — not one shared `WORKER_SECRET`. |

Credential encryption moves out of the database deliberately. The current design POSTs the encryption key to Postgres as an RPC parameter on every league resolution — the migration comment claims the key never touches the database, which is self-contradictory, and it costs two extra round trips per request.

---

## A11 · Shared vs private analytics (§3)

The rule that makes the two product layers coexist:

| | Shared (league-facing) | Private (user-facing) |
|---|---|---|
| Projection source | `league.default_projection_source_id`, pinned | `user_projection_prefs`, user's choice |
| Adjustments | none | `projection_adjustments` for that user |
| License constraint | must be `redistributable` | may be `user_licensed` |
| Storage | league-scoped tables | user-scoped tables |
| API namespace | `/leagues/{id}/...` | `/me/...` |
| Visibility | all league members | that user only — **no admin override** |

Two hard rules:

1. **A `user_licensed` projection set can never produce league-shared output.** Enforced in `resolve_projections` by rejecting the combination, not by convention. This is §5's BBM redistribution constraint made mechanical.
2. **There is no API path that returns another user's private analytics.** Not gated by role — structurally absent. League admins are not exempt; §3 says another manager must not see these, and an admin is another manager.

---

## A12 · Frontend architecture

React + Vite + TypeScript + Tailwind. The audit found no framework problem and the constitution asks for none.

```
src/
  app/            router, providers, layout shell
  features/
    newsroom/     components + hooks + queries
    matchup/
    standings/
    draft/
    projections/
    league-admin/
    onboarding/
  shared/
    ui/           ONE design system
    lib/          pure helpers (dates, formatting, category display)
    api/          GENERATED from OpenAPI + thin react-query wrappers
  types/          generated
```

Decisions:

- **Generated API client.** Deletes the 1,090-line hand-written `api.ts` and makes backend contract changes fail at type-check rather than at runtime.
- **react-query for all server state.** Already the dominant pattern (21 of 22 data modules); make it universal.
- **One design system.** The current duplicate `Card` and `Skeleton` pairs collapse into `shared/ui`.
- **No build-time league identity.** League comes from the route and the user's memberships. `VITE_RECAP_LEAGUE_SLUG` disappears; a second league stops requiring a rebuild.
- **Freshness is rendered, not hidden.** Because every response carries `as_of` and `freshness`, the UI can show "synced 6 minutes ago" or "final" instead of silently presenting stale numbers as live.
- **No client-side calendar constant.** Week metadata comes from `GET /leagues/{id}/weeks`, killing the duplicated `matchupWeeks.ts`.
- Draft state moves to the server (`draft_sessions`), so a mid-draft device change or refresh is survivable. `localStorage` remains only as an offline resilience cache.

---

## A13 · Observability

The audit's most telling pattern: **every failure this system has produced was silent.** A headline feature returning 500 in production, unnoticed. Players dropped from projection sets on a name mismatch. A 140–171s construction found only by reading logs. A documented CLI command that could never have run. Observability is therefore a design constraint, not tooling — I recommend inserting it into §20's priority list between testability and feature velocity.

| Layer | Mechanism |
|---|---|
| Logs | Structured JSON with `request_id`, `league_id`, `user_id`, `job_id` |
| Errors | Sentry (or equivalent) — one dependency, disproportionate value |
| Operational history | `job_runs` and `sync_runs` as queryable tables, not log lines |
| Data quality | First-class metrics: unresolved alias count, projection coverage %, leagues with stale syncs, weeks missing results |
| Status page | `/internal/status` — per-league last successful sync, staleness, failing jobs, alias queue depth |
| Product analytics | Recap generation success rate, LLM token spend per league, solver timeout rate |

**The governing rule: no silent degradation.** If confidence data is unavailable, the API returns `{ data: null, reason: "game_logs_unavailable" }` *and* increments a counter that surfaces on the status page. Honest empty states are already a strength of the current system — this makes them observable as well as honest.

---

## A14 · Testing strategy

| Layer | Approach | Why |
|---|---|---|
| `domain/` | Pure unit tests, no fixtures, no DB | Where the value and the intricacy are; fast enough to run constantly |
| Optimizer | **Committed synthetic projection fixture** | Fixes 20 tests that currently skip on a gitignored `.xls`, leaving the flagship untested in CI |
| `providers/` | Golden-file tests against sanitized `provider_payloads` | Real payloads become fixtures automatically |
| `repos/` + `services/` | Real Postgres (testcontainers or CI service) | Mocked persistence tests prove nothing about tenancy |
| Authorization | **Route × role matrix**, auto-enumerated | A route without a declared policy fails CI |
| Tenant isolation | Two-league / two-user fixtures asserting non-leakage | The §3 and §12 guarantee, tested rather than assumed |
| API | Contract tests against the OpenAPI schema | Keeps the generated client honest |
| Frontend | vitest + testing-library on data shaping and key flows | Current coverage is 15 files against 84 components |
| Migrations | Applied forward and rolled back in CI | Deploy already gates on migrations; make them provably reversible |

Two habits from the current repo are worth carrying over verbatim: **the autouse secret-scrubbing fixture** in `conftest.py` (which makes local runs structurally match clean CI), and **named regression tests for every production bug**.

One addition: a **dependency check at session start**, since the audit's two "failing" tests turned out to be a stale local venv missing a declared dependency rather than real defects.

---

## A15 · Deployment

Deliberately unchanged in shape, corrected in substance.

```
Caddy  →  fcp-api (container, stateless)
       →  static SPA bundle
          fcp-worker (container)
          Postgres (managed — Supabase, Neon, or RDS)
```

| Concern | Decision |
|---|---|
| Disk state | **None.** The API and worker write nothing to local disk. This is the fix for the highest-severity audit finding. |
| Migrations | Run as a gated release step before the new image serves traffic (current `deploy.yml` already does this well) |
| Config | Environment only; no league-specific or user-specific values in env |
| Secrets | Env/KMS; nothing beyond public config baked into the frontend bundle |
| Rollback | Image tag rollback; migrations forward-compatible one version |
| Scaling | API scales horizontally because it is stateless; worker stays at 1 and scales by adding workers when the queue is the bottleneck |

`render.yaml` and `cron_entrypoint.py` do not exist in the target — the Render deployment is gone and the systemd curl trigger is replaced by the worker loop.

---

## A16 · Repository structure

```
fcp/
├── backend/
│   ├── domain/            PURE — no I/O, imports nothing below
│   │   ├── categories.py  scoring.py  standings.py  valuation.py
│   │   ├── projections.py schedule.py consistency.py targets.py
│   │   ├── optimizer/     model.py strategies.py engine.py
│   │   └── recap/         facts.py awards.py
│   ├── providers/
│   │   ├── base.py
│   │   └── espn/          client.py mapper.py schemas.py
│   ├── nba/               ingest.py backfill.py
│   ├── projections/       sources/ (bbm, hashtag, espn_live, fcp_model)
│   ├── repos/             tenant-scoped persistence
│   ├── services/          use cases, transaction boundaries
│   ├── jobs/              queue.py + one module per job kind
│   ├── api/
│   │   ├── deps.py        CurrentUser, LeagueScope, UserScope
│   │   ├── routers/       leagues/ me/ public/
│   │   └── schemas/
│   ├── platform/          config, logging, db, auth, encryption
│   └── migrations/        Alembic
├── frontend/              as A12
├── tests/
│   ├── domain/  providers/  repos/  services/  api/  authz/
│   └── fixtures/          synthetic projections, sanitized payloads
└── docs/
```

Every one of §21's seventeen questions is answerable from this tree without archaeology:

| Question | Answer |
|---|---|
| Where does external data enter? | `providers/` and `nba/`. Nowhere else. |
| What is the canonical player? | `domain` `Player`, table `players`, id `player_id` |
| Canonical league / team / roster / matchup? | `leagues`, `fantasy_teams`, `roster_slots`, `matchups` |
| Canonical projection? | `ProjectionView` from `domain/projections.py` |
| Where does basketball logic live? | `domain/` — and nothing else may |
| Where does user-specific logic live? | `services/` reading `UserScope`, surfaced at `/me/**` |
| What is current vs historical? | `league_weeks.status`, echoed in every API response |
| What belongs to a user vs a league? | `user_*` tables and `/me/**` vs `league_*` and `/leagues/**` |
| What can each user access? | The authorization matrix test enumerates it |
| Where does a new feature go? | A service + a router + pure functions in `domain/` |

---

# Part B · Classification of the current system

Concept / algorithm / data model / implementation assessed separately, per the brief.

## B1 · Domain logic and algorithms

| Subsystem | Concept | Algorithm | Data model | Implementation | Verdict |
|---|---|---|---|---|---|
| 9-cat semantics, `LOWER_IS_BETTER`, `category_result` | keep | keep | keep | keep | **KEEP** |
| All-play / universe wins (`WeeklyScoreboard`) | keep | **keep** | n/a | de-ESPN it | **KEEP BUT CLEAN UP** |
| Playoff-aware all-play (ghost-team exclusion) | keep | keep | n/a | keep | **KEEP** |
| Auction optimizer (`OptimizeLineup`, cvxpy) | keep | **keep** | replace inputs | rewrite surround | **KEEP ALGORITHM · REPLACE SURROUND** |
| Plan diversity / strategy map | keep | keep | n/a | clean | **KEEP BUT CLEAN UP** |
| Draft engine (per-pick health + selective re-solve) | keep | keep | **replace** (server sessions) | keep | **KEEP BUT CLEAN UP** |
| Monte Carlo category targets | keep | keep | n/a | keep | **KEEP** |
| Forge Value / auction valuation | keep | keep *(unverified)* | n/a | clean | **KEEP BUT CLEAN UP** |
| Consistency / confidence tiers | keep | keep | **replace** (Postgres game logs) | refactor | **REFACTOR** |
| Deterministic awards | keep | keep | n/a | keep | **KEEP** |
| Power rankings | keep | keep | n/a | clean | **KEEP BUT CLEAN UP** |
| Historical standings reconstruction | keep | keep | **replace** (fold over final weeks) | simplify | **REFACTOR** |

> The optimizer carries a caveat: 798 lines of cvxpy with **zero CI coverage**, because 20 tests skip on a gitignored `.xls`. Port it behind a committed synthetic fixture and characterization tests — do not port it on trust.

## B2 · Projections

| Subsystem | Concept | Algorithm | Data model | Implementation | Verdict |
|---|---|---|---|---|---|
| `PlayerProjection` canonical schema | **keep** | n/a | extend (`player_id`, license) | keep | **KEEP** |
| Adapter protocol + BBM/Hashtag/ESPN adapters | keep | keep | n/a | refactor | **KEEP BUT CLEAN UP** |
| Week-scoped set invalidation | **keep** | keep | keep | keep | **KEEP** |
| `ProjectionStore` (parquet + `manifest.json`) | keep concept | n/a | **replace** | **replace** | **REPLACE** |
| Registry precedence / `get_active_projections` | keep concept | n/a | replace | **replace** | **REPLACE** → explicit `resolve_projections(source, horizon, adjustments)` |
| Global `active` horizon map | — | — | — | — | **DELETE** — replaced by per-user prefs |
| Accuracy scoreboard (M-2) | **keep** | keep | replace storage | keep | **KEEP BUT CLEAN UP** |
| Backtest harness + naive baseline (M-3a) | keep | keep | n/a | keep | **KEEP** |
| NBA ingest + CSV backfill | keep | keep | extend (`player_id` FK) | clean | **KEEP BUT CLEAN UP** |
| `nba_player_seasons` / `nba_player_bio` | keep | n/a | **keep** + `player_id` | n/a | **KEEP BUT CLEAN UP** |

## B3 · Newsroom

| Subsystem | Concept | Algorithm | Data model | Implementation | Verdict |
|---|---|---|---|---|---|
| Facts / editions separation | **keep** | n/a | **keep** | keep | **KEEP** |
| Versioning + one-published partial index | **keep** | n/a | **keep** | keep | **KEEP** |
| `publish_recap_edition` atomic RPC | keep | n/a | keep | keep | **KEEP** |
| `recaps/service.py` authorization | keep | n/a | n/a | port | **KEEP** — the only correct authz in the repo |
| `assemble.py` fact assembly | keep | keep | n/a | **refactor** | **REFACTOR** — strip the three-way reconciliation fallbacks |
| LLM prompts + voice spec | keep | n/a | n/a | refactor | **KEEP BUT CLEAN UP** |
| Structured generation (JSON repair + retry) | keep | n/a | n/a | **replace** | **REPLACE** — use native structured outputs, not repair |
| `/matchup-commentary`, `/league-recap`, `/season-commentary` | — | — | — | — | **DELETE** — superseded, unauthenticated, unmetered |

## B4 · Platform, data access, and infrastructure

| Subsystem | Verdict | Note |
|---|---|---|
| ESPN gateway (timeouts, typed errors, status mapping) | **KEEP** | Relocate into `providers/espn/client.py`; genuinely good work |
| `MyLeague` / `ScoreboardLeague` (subclassing `espn_api.League`) | **REPLACE** | The §7 violation; the highest-leverage single change |
| `data_feed.py` (2,699 lines) | **DELETE after extraction** | Mine `normalize_name`, `category_result`, scoreboard math, transaction reconstruction; discard the module |
| `RecapStore` (32 methods, six aggregates) | **REPLACE** | → scoped repositories with pooled connections |
| PostgREST as the data path | **REPLACE** | → SQLAlchemy; no service-role bypass |
| `league_state_snapshots` + 2 per-week tables | **REPLACE** | → one `matchups`/`transactions` model + week finality |
| `league_week_snapshots` + `recap_editions` | **KEEP** | Migrate data forward |
| `leagues` / `league_memberships` / `league_invites` | **KEEP BUT CLEAN UP** | Extend with `league_connections`, `fantasy_team_id`, settings |
| RLS policies + `is_league_admin` / `is_league_member` | **KEEP BUT CLEAN UP** | Retain as defense in depth; app becomes primary |
| Team-claim column-grant model | **KEEP** | Elegant; the pattern generalizes |
| pgcrypto credential RPC | **REPLACE** | → application-side envelope encryption |
| Slug middleware + `_LEAGUE_CTX` ContextVar | **REPLACE** | → explicit `LeagueScope` dependency injection |
| Four caching layers (`league/cache.py`) | **DELETE** | No purpose once nothing fetches inside a request |
| `_resolve_ctx()` single-league fallback | **DELETE** | The §12 violation |
| `config.py` personal globals (`DO_NOT_DRAFT`, `POSITION_OVERRIDES`, `GAMES_PER_WEEK`) | **DELETE** | → `user_league_prefs` / `league_settings` |
| Hardcoded week calendars (Python **and** TypeScript) | **DELETE** | → derived `league_weeks` |
| `worker/refresh.py` | **REPLACE** | Keep the failure-isolation *concept*; replace the synchronous loop |
| Per-phase / per-league failure isolation | **KEEP** | Concept survives into job design |
| `render.yaml`, `cron_entrypoint.py` | **DELETE** | Dead Render artifacts |
| `data/game_logs.db` dependency | **REPLACE** | → `nba_player_games` in Postgres; fills a real data gap |
| `/optimizer/multiple-plans` (`out_prefix` → `to_csv`) | **DELETE** | Arbitrary file write; the CSV-writing path has no place in an API |
| `legacy_redirects.py` (17 routes) | **DELETE** | Its own docstring says remove after cutover |

## B5 · Frontend

| Subsystem | Verdict | Note |
|---|---|---|
| React 19 + Vite + Tailwind + react-query stack | **KEEP** | No framework problem |
| `api.ts` (1,090 lines, hand-maintained) | **REPLACE** | → generated from OpenAPI |
| Dual axios clients (`client` / `directClient`) | **DELETE** | A dev-proxy workaround in production code |
| `ui/` design system | **KEEP BUT CLEAN UP** | Absorb the duplicate `components/Card`, `season/Skeleton` |
| `components/Card.tsx`, `season/Skeleton.tsx` | **DELETE** | Duplicates |
| Newsroom / standings / matchup / awards surfaces | **KEEP BUT CLEAN UP** | Reorganize into `features/`, rebind to the generated client |
| Draft UI (board, rail, controls, editors) | **KEEP BUT CLEAN UP** | Well decomposed already |
| `draft/storage.ts` (localStorage as system of record) | **REFACTOR** | → server sessions; keep as offline cache |
| `lib/navigation.ts`, `useLeagueSlug`, `stateUtils` | **KEEP** | Small, pure, tested |
| `lib/matchupWeeks.ts` | **DELETE** | Duplicated hardcoded calendar |
| Direct browser→Supabase data calls (invites, memberships) | **REPLACE** | → API endpoints; Supabase for auth only |
| Auth surfaces (login, signup, reset, update) | **KEEP** | Work fine |
| `pages/InSeason.tsx`, `pages/Season.tsx` shims | **DELETE** | P-7 leftovers |

## B6 · Testing and tooling

| Subsystem | Verdict |
|---|---|
| `conftest.py` autouse secret scrubbing | **KEEP** — best test infrastructure in the repo |
| Stub `LeagueContext` fixture | **REFACTOR** → scope fixtures |
| Named regression tests for production bugs | **KEEP** (the habit, and the tests) |
| RLS boundary suite (16 tests) | **KEEP BUT CLEAN UP** — retarget at app authz + RLS backstop |
| Draft integration tests skipping on a gitignored file | **REFACTOR** — commit a synthetic fixture |
| CI: dual pytest runs across two workflows | **KEEP BUT CLEAN UP** — one gate |
| Migration-gated deploy | **KEEP** — good practice |

---

# Part C · Recommendation

## The verdict

> ### Option 4 — preserve the domain logic, rebuild the application around it.
>
> Stand up a new repository skeleton with the target architecture, then port the basketball IP module by module: stripped of infrastructure dependencies, given a real test harness, and landed behind a vertical slice that works end to end.

## Why not the alternatives

**Option 1 — continue as-is.** Untenable. Three of the audit's findings are critical and none is incrementally fixable in place: state destroyed on every deploy, 53 unauthenticated routes, a headline feature 500ing in production. §17 forbids the trusted-user assumptions the current system is built on.

**Option 2 — refactor selected areas.** This is the tempting answer and it fails on entanglement. The three highest-leverage changes — canonical player identity, the provider boundary, tenant isolation — each require touching nearly every module simultaneously. Introducing `player_id` means changing every join; removing the ESPN subclassing means rewriting every analytics caller; adding `LeagueScope` means changing every route and every client call. Sequencing those as safe incremental refactors inside a codebase where one 2,699-line module is imported by everything is *more* work than porting the good parts into a clean structure, and it leaves you with a half-migrated system — which is precisely the state the audit found, five times over.

**Option 3 — rebuild major subsystems.** Close, but it understates the scope. The subsystems needing replacement (persistence, provider boundary, tenancy, jobs, API shape, frontend data layer) constitute the entire application. What is left after replacing them is exactly the domain library. That *is* Option 4, described less clearly.

**Option 5 — full greenfield restart.** Overshoots, and §18 explicitly forbids rebuilding for cleanliness alone. It would discard the auction optimizer, plan-diversity engine, Monte Carlo targets, valuation model, all-play math, category-direction rules, recap facts/editions model, deterministic awards, the projection schema, the accuracy scoreboard, and the ESPN transport hardening. That is months of hard-won basketball work that the audit rates as genuinely good and that a rewrite would most likely reproduce worse. §19's instruction is to evaluate on merit; on merit, that code survives.

## Why Option 4 is right here

The audit's summary judgement was: **the domain modelling is better than the infrastructure, and the infrastructure is better than the boundaries between subsystems.** That maps exactly onto this recommendation — keep the layer that is good, replace the layers that are not, and impose the boundaries that were never there.

Three specifics make it decisive:

1. **The good code is already nearly pure.** `draft/engine.py` has no cvxpy, pandas, or ESPN imports and injects its solver. `WeeklyScoreboard` takes injected data. `playoff_schedule.py` is pure functions. `PlayerProjection` is a plain dataclass. This code was *written* to be portable; someone was already reaching for the target architecture. Porting it is mostly deletion of import statements, not redesign.

2. **The bad parts are structural, not local.** You cannot decompose `data_feed.py` while forty call sites import it. You cannot add tenancy to 18 flat routes without changing every consumer. You cannot make projections durable while a global on-disk manifest is the system of record. These need a new home, not a patch.

3. **Zero migration cost changes the calculus entirely.** §18 removes the usual reason to prefer incremental refactoring — the risk and cost of a cutover. With downtime and effort free, the only question is which endpoint state is better, and a clean architecture carrying proven algorithms beats a half-migrated one carrying the same algorithms.

## What this is not

It is **not** a rewrite of the basketball logic. Roughly 4,000 lines of domain code port largely intact. It is a rewrite of the ~6,000 lines of plumbing around them, plus genuinely new work (player identity, per-user data, the job queue) that does not exist today in any form.

## Sequencing

Each phase ends with something that works end to end. Nothing is built speculatively (§15, §22).

| Phase | Scope | Done when |
|---|---|---|
| **0 · Decisions** | Resolve the four open questions in [`CONSTITUTION_TRACEABILITY.md`](CONSTITUTION_TRACEABILITY.md) §D — especially **data vs code** under §18 | Written down |
| **1 · Skeleton** | Repo structure, Postgres + Alembic, auth with local JWKS, `LeagueScope`/`UserScope`, authorization matrix test, CI, observability baseline | An authenticated `/me/leagues` returns real data with a passing authz matrix |
| **2 · Provider + domain core** | `providers/espn`, `provider_payloads`, canonical entities, **player identity + alias resolution**, `league_weeks` with finality, sync jobs | A league syncs; standings as of any past week are correct |
| **3 · Newsroom vertical slice** | Port facts/awards/power rankings; migrate `recap_editions` + `league_week_snapshots`; public archive; admin publish | The league reads its recaps on the new system |
| **4 · Projections** | `projection_sets`/`rows` in Postgres, adapters, `resolve_projections`, per-user prefs, adjustments, accuracy scoreboard | BBM vs ESPN measurable again — on durable storage |
| **5 · Draft Room** | Port optimizer/strategies/engine/targets **behind a committed synthetic fixture**; server-side sessions; private per user | A full draft runs, resumable across devices |
| **6 · Cutover** | DNS, decommission old stack | Old repo archived |
| **7 · FCP model (M-3)** | The projection model, into the framework built in phase 4 | Beats the naive baseline on the M-2 scoreboard |

Phase 1 is where the audit's critical findings die: no local disk, tenancy structural, authorization enumerated and tested.

## The one thing to decide before starting

**Does §18's zero-sunk-cost rule apply to data as well as code?** Replaceability differs sharply:

| Data | Replaceable? |
|---|---|
| NBA seasons + bios (8,341 / 1,915 rows) | Yes — re-backfill from the Kaggle CSV |
| ESPN league data (matchups, transactions, rosters) | Yes — refetch from ESPN |
| Users, memberships, team claims | No — live accounts |
| **Published recap editions** | **No** — LLM output bound to a specific week's facts, and §13 promises multi-season league history |

Recommendation: migrate `users`, `league_memberships`, `recap_facts`, and `recap_editions` forward; re-derive everything else. That is a small, well-understood migration rather than a full data port, and it protects the one irreplaceable asset.

---

*Architecture phase only. No code modified. Current as of `8092789`.*
