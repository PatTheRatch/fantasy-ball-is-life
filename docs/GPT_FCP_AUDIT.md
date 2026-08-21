# GPT FCP Forensic Architecture and Product Audit

**Review date:** 2026-08-21  
**Review type:** Read-only architecture and product investigation  
**Repository:** `fantasy-ball-is-life` / Full Court Press (FCP)

## Executive summary

FCP is currently a multi-league, ESPN-backed fantasy basketball platform for 9-category head-to-head leagues. Its center of gravity is no longer one feature: it combines league operations, matchup analysis, projections, draft planning, standings, weekly editorial recaps, and early projection-model infrastructure.

The implementation began as a single-league “Patriot Games” decision tool and newsroom. Multi-league identity, authentication, persistence, background snapshots, and league creation were added later. That history explains most of the present architectural tension: the user-facing product has become a platform, while several data, authorization, and runtime components still behave like local single-user utilities.

This audit treated the current implementation as evidence of what has been built, not as a constraint on a future architecture. It does not propose a replacement architecture or recommend a rewrite.

The repository knowledge graph was used first for structural exploration and impact analysis. Important findings were then validated against current source, migrations, configuration, tests, and git history.

## 1. Reconstructed product

The clearest original description is still in [`README.md`](../README.md): a GM’s cockpit that connects to ESPN, helps managers decide whom to start, add, or target, and writes a weekly league recap.

What actually exists now is broader.

### Current product surfaces

- Supabase email/password authentication, recovery, and password-update flows.
- Membership-aware home routing:
  - logged out → landing/default league behavior;
  - zero memberships → league lobby;
  - one membership → direct league entry;
  - multiple memberships → league picker.
- Public-league self-join by claiming an unclaimed ESPN team.
- Invite creation and redemption, including admin invites.
- ESPN league creation:
  - preview and validate the ESPN league;
  - optionally supply private-league cookies;
  - create the FCP league and schedule its first refresh.
- League home:
  - the member’s matchup;
  - standings;
  - movers and recent acquisitions;
  - recent recap.
- Matchup pages:
  - current score;
  - projected final score;
  - confidence estimates;
  - category detail;
  - AI commentary.
- Standings and season analytics.
- Newsroom:
  - weekly recap archive;
  - deterministic matchup facts, standings, power rankings, transactions, awards, and season statistics;
  - generated editorial copy;
  - admin draft, publish, history, and rollback;
  - share text suitable for copying to WhatsApp.
- Draft Room:
  - auction draft optimization;
  - up to ten strategy plans;
  - custom targets and exclusions;
  - nomination triage;
  - manual pick logging and undo;
  - budget and roster tracking;
  - broken-plan relaxation;
  - Monte Carlo targets;
  - auction simulation;
  - internal “Forge Value.”
- Projection infrastructure:
  - ESPN Last 15/30 projections;
  - Basketball Monster ingestion;
  - a Hashtag Basketball adapter;
  - active projection-set management;
  - projected-versus-actual accuracy reporting.
- NBA historical-data scaffolding:
  - NBA.com ingestion;
  - CSV backfill;
  - typed season-data reader;
  - baseline backtesting.

### Implemented, partial, and planned scope

| Capability | Status inferred from code |
| --- | --- |
| ESPN league dashboards | Implemented |
| Multi-league accounts and memberships | Implemented, with important correctness and security gaps |
| Weekly editorial recap | Implemented |
| Auction draft optimizer | Implemented |
| External projection uploads | Implemented, but operational persistence is weak |
| Projection accuracy benchmarking | Implemented |
| FCP-owned projection model | Not implemented; data and baseline scaffolding exist |
| Daily roster/score capture | Specified, not implemented |
| Streaming advisor | Specified, not implemented |
| Trade analyzer | Specified, not implemented |
| Automated WhatsApp/Discord delivery | Not implemented; copy/share output only |
| Yahoo/Sleeper support | Aspirational/specification-level |
| Monetization or packaged consumer product | Not evident |

The repository documentation is substantially behind the code. For example, the README still calls the system single-league and says `backend/projections` is empty, although neither is now true.

## 2. Major user workflows

### Account and league entry

1. A user signs up or logs in through Supabase.
2. The browser retrieves that user’s memberships directly from Supabase.
3. FCP routes them to a league or a league picker.
4. A user can self-join a public league and claim an ESPN team, redeem an invite, or create an ESPN-backed league.

Team identity is represented by the ESPN team’s display name stored on the membership, not by a durable ESPN team identifier.

### League creation

1. The browser sends the Supabase bearer token to FastAPI.
2. FastAPI verifies the token against Supabase.
3. `/leagues/preview` connects to ESPN and validates the league and cookies.
4. `/leagues` repeats validation, encrypts ESPN cookies using a Supabase RPC, inserts the league, inserts the owner membership, and schedules an in-process background refresh.
5. The regular refresh timer later brings the league into the snapshot cycle.

This workflow currently contains a repository-level schema mismatch discussed below.

### Regular in-season use

1. The user enters a slug-scoped league URL.
2. Middleware resolves the slug to stored league configuration and decrypted ESPN credentials.
3. Pages read a mixture of:
   - 15-minute Supabase snapshots;
   - immutable per-week data;
   - published recap snapshots;
   - live ESPN queries.
4. React Query caches browser requests for one minute.
5. Projected matchup tools combine current rosters, NBA schedules, an active projection source, and historical variance estimates.

### Recap workflow

1. An admin chooses a season/week and requests readiness.
2. FCP assembles deterministic facts and runs data-quality checks.
3. Awards are selected deterministically.
4. A versioned fact snapshot is persisted.
5. An LLM generates structured editorial content.
6. Power-ranking blurbs are cached separately and reused across recap regenerations.
7. The resulting recap edition remains a draft until published.
8. Publishing atomically supersedes the previous published edition.
9. An admin can inspect history and roll back to an earlier edition.

Despite comments saying admin generation pulls fresh ESPN data, the current service calls `assemble_weekly_snapshot` without `force_fresh=True`; both readiness and generation therefore use the stored snapshot path by default.

### Draft workflow

The Draft Room is client-authoritative:

1. The browser keeps picks and plan state in `localStorage`.
2. Every recomputation submits the current state to stateless FastAPI endpoints.
3. The backend loads an active season projection set or a legacy BBM file.
4. It removes drafted/excluded players and computes remaining budget and roster constraints.
5. Monte Carlo targets and strategy variations feed a CVXPY mixed-integer solve.
6. It returns plans, health/failure information, nomination triage, or relaxed alternatives.

There is no server-side draft session, concurrency control, revision number, or shared room state.

## 3. Current architecture map

```text
React 19 / Vite SPA
│
├── Supabase JS ──────────────► Supabase Auth
│                               profiles
│                               memberships / invites
│                               browser-enforced RLS
│
└── Axios over /api ─► Caddy ─► FastAPI
                                  │
                                  ├── slug middleware
                                  │     └── league row + decrypted ESPN cookies
                                  │
                                  ├── league/data_feed
                                  │     └── espn-api / ESPN fantasy endpoints
                                  │
                                  ├── draft engine
                                  │     ├── pandas
                                  │     └── CVXPY mixed-integer optimization
                                  │
                                  ├── projection registry
                                  │     └── local Parquet + JSON manifest
                                  │
                                  ├── recap service
                                  │     ├── deterministic snapshot assembly
                                  │     ├── Supabase PostgREST persistence
                                  │     └── Anthropic or DeepSeek
                                  │
                                  ├── consistency analytics
                                  │     └── local SQLite game_logs.db
                                  │
                                  └── NBA ingestion/readers
                                        ├── nba_api / NBA.com
                                        ├── CSV backfills
                                        └── Supabase NBA tables

systemd timer, every 15 minutes
└── POST /api/admin/refresh-all
      └── for every league:
          ESPN live data
          ├── rolling phase snapshots
          ├── per-week scoreboards
          ├── per-week transactions
          ├── ESPN projection benchmark
          └── standings / rankings / season statistics
```

The API application and router composition are in `backend/api/main.py`. The frontend route structure is centralized in `frontend/src/router.tsx`.

## 4. Repository structure

The tracked repository is roughly:

- `frontend/`: 123 files
- `backend/`: 65 files
- `tests/`: 50 files
- `docs/`: 22 files before this audit
- `supabase/`: 13 files

Responsibilities by directory:

- `backend/api`: FastAPI application, middleware, dependencies, routers.
- `backend/league`: ESPN acquisition, transformations, caches, schedules, standings, and legacy league-domain classes.
- `backend/draft`: optimizer, strategy generation, target calculation, valuation, auction simulation.
- `backend/projections`: canonical schema, source adapters, local store, registry, accuracy, backtesting.
- `backend/nbadata`: NBA.com and CSV ingestion plus season readers.
- `backend/recaps`: snapshot assembly, awards, persistence, authentication, publication, sharing.
- `backend/commentary`: prompts, providers, schemas, structured generation.
- `backend/analytics`: historical consistency/confidence calculations.
- `backend/worker`: recurring ESPN refresh orchestration.
- `frontend/src/pages`: route-level screens.
- `frontend/src/components`: shared and feature components.
- `frontend/src/draft`: Draft Room UI and local persistence.
- `frontend/src/season`: season feature.
- `frontend/src/ui`: emerging shared UI primitives.
- `supabase/migrations`: schema and RLS history.
- `deploy`, `Dockerfile`, `docker-compose.yml`, `Caddyfile`: current VPS deployment.
- `render.yaml`: older or alternative Render deployment.
- `docs/specs`: specifications and decision history.
- `data/`, `player_rankings/`: local, mostly gitignored runtime inputs.

## 5. Frontend architecture

The frontend is React 19, TypeScript, Vite, Tailwind v4, React Router, TanStack Query, Axios, and Supabase JS.

The root composition is conventional: `QueryClientProvider → AuthProvider → RouterProvider`, with a one-minute default query freshness window.

### Positive structure

- Routing is centralized.
- Heavy pages are lazy-loaded.
- Authentication context is mounted once.
- Slug-scoped league URLs are now the primary navigation scheme.
- React Query is used for server-state caching.
- The UI has begun extracting primitives into `src/ui`.
- Draft-specific state and types are reasonably isolated under `src/draft`.
- Public league pages and explicitly authenticated account/setup pages are distinguishable in routing.

### Frontend concentration and coupling

Several files remain feature monoliths:

- `SeasonPage.tsx`: approximately 615 lines.
- `Board.tsx`: approximately 564 lines.
- `ScoreboardTools.tsx`: approximately 499 lines.
- `DraftPage.tsx`: approximately 400 lines.
- `api.ts`: approximately 1,090 lines.

`api.ts` combines transport configuration, all endpoint functions, legacy endpoints, request bodies, and response contracts for unrelated features. It also retains two Axios clients because recap generation previously exceeded the Vite proxy’s tolerance. Most recap calls use the direct client, but `getRecapEdition` uses the ordinary client, so even the historical workaround is inconsistently applied.

### Direct database access

The browser directly accesses Supabase for:

- sessions and accounts;
- memberships;
- team claims;
- invites;
- some settings and administration operations.

FastAPI handles ESPN credentials, league creation, recap administration, and service-role persistence paths. Authorization is therefore split between Supabase RLS and FastAPI route dependencies.

### Concrete frontend/backend contract defect

The backend’s current scoreboard endpoint returns:

```json
{"data": [], "fetched_at": "..."}
```

The frontend declares and returns the entire response as `JsonRecord[]`, then passes it into array-processing code in the current-matchup flow. This is not merely a loose type: the runtime value is an object where the consumer expects an array. The corresponding frontend tests mock the expected array and therefore do not test the actual backend contract.

### Duplication

- `components/Card.tsx` and `ui/Card.tsx`.
- `season/Skeleton.tsx`, `ui/Skeleton.tsx`, and a local skeleton in `ScoreboardTools`.
- Repeated card, table, and loading patterns inside feature pages.
- Backend and frontend copies of the 2025–26 matchup calendar.
- Legacy one-line route shims and redirects.
- Older flat API helpers alongside newer slug-scoped helpers.

This looks like an unfinished migration toward a design system and a league-scoped information architecture.

## 6. Backend architecture

FastAPI is organized into routers for league data, draft, legacy optimizer, commentary, projections, recaps, admin refresh, league preview and creation, and legacy redirects.

Most route handlers are synchronous and call synchronous libraries: `requests`, pandas, ESPN API wrappers, CVXPY, and PostgREST.

### League context

A slug middleware resolves `/leagues/{slug}` before route execution. It retrieves the league row using the service-role client, decrypts cookies through Supabase RPC, and stores a league context in a `ContextVar`.

This middleware exists partly because dependency execution in Starlette’s threadpool lost the earlier dependency-created `ContextVar`. It is an effective local solution, but also a historical workaround that makes route resolution, database access, credential handling, and thread-context behavior interdependent.

Legacy flat paths still fall back to a configured or first league.

### ESPN access

The ESPN layer is defensive in several good ways:

- explicit connection and read timeouts;
- typed timeout and unavailable errors;
- a scoped monkeypatch confined to `espn-api` rather than global `requests`;
- per-request connection reuse;
- a 90-second cross-request cache;
- per-league single-flight locks.

The cache was added after production showed some `MyLeague` construction calls taking roughly 140–171 seconds. The result improves survivability, but it also demonstrates how expensive and stateful the current ESPN abstraction can be.

### Persistence access

There is no ORM or direct PostgreSQL client. `RecapStore` is a hand-written service-role PostgREST wrapper. It began as recap persistence and now performs most server-side database work:

- league lookup;
- membership and admin checks;
- snapshots;
- recap editions;
- power-ranking blurbs;
- credentials;
- NBA data;
- weekly scoreboards and transactions.

That class has become a general persistence gateway while retaining recap-specific naming and placement.

### Large backend centers

- `backend/league/data_feed.py`: about 2,700 lines.
- `backend/recaps/assemble.py`: about 880 lines.
- `backend/draft/optimizer.py`: about 800 lines.
- `backend/api/routers/draft.py`: about 700 lines.
- `backend/recaps/store.py`: about 660 lines.
- `backend/worker/refresh.py`: about 500 lines.

`data_feed.py` in particular mixes ESPN connection code, player normalization, schedules, transactions, roster projections, matchups, standings, power rankings, value enrichment, file inputs, and legacy CLI output.

## 7. Database and data model

Supabase/PostgreSQL contains four broad groups of data.

### Identity and league configuration

- `profiles`
- `leagues`
- `league_memberships`
- `league_invites`

`leagues` contains slug, branding, visibility, recap voice, ESPN league identity, season, encrypted cookies, timezone, and both `owner_user_id` and `admin_user_id`.

Memberships contain user, league, role, and optional claimed ESPN team name.

Authority is duplicated between league owner/admin columns and membership roles. League creation currently records the creator as both owner/admin in the league row but gives the membership the role `admin`, not `owner`.

### Recap history

- `league_week_snapshots`
- `recap_editions`
- `power_ranking_editions`

These are versioned and largely immutable. Only one recap edition can be published for a league, season, and week. Publication uses a database function to supersede the former edition atomically.

This is one of the strongest parts of the data design.

### Operational league snapshots

- `league_state_snapshots`: one rolling row per league, season, and phase.
- `league_week_scoreboards`: one row per league, season, and week.
- `league_week_transactions`: one row per league, season, and week.

The rolling table originally supported the fast read-path flip away from ESPN. Per-week tables were added later after past weeks displayed current scoreboards, transactions, or end-of-season standings.

This creates three overlapping representations:

1. rolling current state;
2. immutable per-week operational facts;
3. versioned recap fact snapshots.

### NBA historical data

- `nba_player_bio`
- `nba_player_seasons`

These store player identity and per-season averages, makes and attempts, and context for future projection work.

### JSON-heavy model

Most fantasy facts remain JSON payloads rather than normalized relational entities. There are no durable first-class database records for fantasy teams, NBA/fantasy player identity mappings, rosters, matchups, category results, transactions, schedules, or daily lineup slots.

The current schema is well suited to cached read models and immutable recap evidence, but the same JSON approach now carries operational state that future streaming, trading, longitudinal analysis, and data-lineage features would need to query.

### Concrete creation/schema mismatch

Current league creation includes an `id` field when inserting `league_memberships` in `backend/api/routers/create_league.py`.

The repository schema defines no `id` column for that table; its primary key is `(league_id, user_id)`. No later migration adds an `id`.

Against the repository’s schema, that PostgREST insert is invalid. The league insert occurs first and the two writes are not transactional, so membership failure can leave a league without its creator membership. Tests mock the persistence client and assert the same invalid payload, so they do not catch this integration failure.

Production database drift could theoretically make production different, but there is no migration evidence for that.

The Supabase config also enables `./seed.sql`, but that file is absent from the repository.

## 8. Fantasy basketball domain logic

The implemented domain is specifically ESPN 9-category H2H:

- PTS
- REB
- AST
- STL
- BLK
- 3PM
- FG%
- FT%
- TO, lower being better

### Matchups and standings

The code:

- canonicalizes matchup and category rows;
- calculates category winners and records;
- preserves ESPN’s authoritative matchup winner where category evidence ties;
- assigns evidence identifiers;
- tracks games played;
- derives standings from accumulated weekly category wins, losses, and ties;
- distinguishes regular-season, consolation, semifinal, and championship contexts.

### Power rankings

The current composite is approximately:

- 35% full-season all-play win rate;
- 35% recent all-play win rate;
- 20% actual record;
- 10% category dominance.

The live-only power-ranking implementation ranks every category descending, including turnovers. Elsewhere, such as the worker’s season-stat ranks, turnovers are correctly inverted. This is a domain-rule inconsistency in the `force_fresh` branch. That branch is currently latent because admin generation does not pass `force_fresh=True`.

### Percentage categories

Player projections preserve FGA and FTA and derive percentages from makes and attempts, which is the correct basis for aggregating ratio categories.

Some season aggregation paths take means of weekly FG% and FT% values and label that behavior correct. Whether the underlying `all_play` frame has already weighted those figures by attempts needs a focused numerical audit; the repository does not make that conclusion safe without test fixtures containing strongly unequal attempt volumes.

### Draft domain

The draft model includes:

- auction budget;
- roster size and position eligibility;
- category target percentiles;
- favorite-team representation;
- minimum-value-player counts;
- individual target players;
- exclusions;
- season games thresholds;
- rival picks and the user’s acquired players;
- lower-is-better turnovers;
- source values versus internal Forge values;
- strategy diversity and plan health.

Some supposed “league-owner” choices remain global environment configuration, including a personal default do-not-draft list and an Anthony Davis position override. These can affect every league in a multi-league deployment.

## 9. Projection, player, league, and calculated-data flow

### Projection schema and sources

`PlayerProjection` is a meaningful canonical boundary. Consumers can work with normalized player identity, positions, games, per-game categories, attempts, percentages, source value, injury status, and fantasy roster ownership.

Sources include:

- ESPN Last 15 and Last 30;
- Basketball Monster;
- Hashtag Basketball;
- reserved internal and custom sources.

The Hashtag adapter exists but is not wired into the current upload API or UI. The public upload flow primarily exposes BBM.

### Local projection store

Projection sets are Parquet files plus a JSON manifest under `data/projections`.

Useful semantics include:

- source and horizon;
- week scoping;
- league slug for ESPN benchmark sets;
- active set per horizon;
- an ESPN live virtual sentinel;
- atomic Parquet file replacement;
- non-activating benchmark snapshots.

Weak runtime semantics include:

- process-local filesystem state;
- manifest writes without cross-process locking;
- new `ProjectionStore` construction on most lookups despite a docstring calling it a singleton;
- global active-horizon selection rather than league- or user-scoped selection;
- no durable container volume.

### Projected matchup flow

1. Resolve the league and current roster from ESPN.
2. Resolve the active week projection source.
3. Attach player projections and remaining NBA games.
4. Aggregate totals by fantasy team.
5. Compare projected category results.
6. Scale team totals into a player-game-like basis.
7. Query consistency distributions from SQLite for confidence estimates.
8. Return projected outcomes to the matchup UI.

### Accuracy flow

The worker records one ESPN Last-15 snapshot per league/week without making it active. Accuracy reporting later compares stored weekly projection sets with actual weekly team scoreboards. BBM/global projections need a roster-to-team mapping before they can be scored. The current week is excluded to avoid comparing projections with partial actuals.

### NBA data flow

The NBA ingestion code retrieves standard and advanced season data through `nba_api`, retries with backoff and request spacing, merges results, and upserts player biographies and seasons into Supabase. A CSV adapter supports historical backfill when NBA.com access is unreliable.

No scheduled NBA ingestion job was found. Unlike ESPN refresh, NBA population appears to be CLI/manual.

## 10. Authentication and account architecture

Supabase owns user identity and sessions. The browser restores and refreshes sessions, listens for auth-state changes, performs sign-up/login/recovery, and reads membership data directly through RLS.

The backend verifies bearer tokens by making a network call to Supabase’s `/auth/v1/user` endpoint for each protected operation. It does not locally validate JWTs or cache verification.

Backend admin authorization then queries memberships and the owner/admin columns using the service-role key.

### Important boundary issue

Most slug-scoped league routes have no user dependency. The slug middleware resolves any league, including private leagues, with the service-role key, and the backend subsequently reads snapshots or ESPN data while bypassing RLS.

Therefore, database RLS does not protect those API routes. Based on the repository, knowledge of a private league slug is sufficient to call many private-league endpoints. Recap public methods explicitly check `visibility`, but the general league router does not.

Similarly:

- draft endpoints are unauthenticated;
- projection upload and activation endpoints are unauthenticated;
- projection accuracy is unauthenticated;
- legacy AI commentary endpoints are unauthenticated;
- those commentary endpoints can incur external LLM cost.

### Signup and invite behavior

The production-facing signup form is hidden unless open signup is enabled or any non-empty `?invite=` parameter exists. The token is not validated before showing signup, so this is a cosmetic gate rather than an authorization boundary.

Invites themselves are stronger:

- stored tokens;
- expiry and single-use behavior;
- database RPC redemption;
- locking and race protection;
- admin RLS policies.

Team claims are protected by a unique lowercase team-name index and column-level update grants. Their weakness is identity durability: a team rename can break the connection between account and ESPN team.

## 11. External sources and integrations

- ESPN fantasy basketball through `espn-api` and direct ESPN request objects.
- ESPN private-league cookies (`SWID`, `espn_s2`), encrypted before storage.
- Supabase Auth, Postgres, RLS, PostgREST, and RPC.
- Anthropic as the default structured recap provider.
- DeepSeek as an optional recap provider.
- Legacy Anthropic commentary endpoints.
- Basketball Monster projection spreadsheets.
- Hashtag Basketball format support.
- NBA.com data through `nba_api`.
- CSV historical backfill.
- GitHub Actions.
- Caddy and Docker Compose on a VPS.
- WhatsApp-style sharing through generated copy, not a messaging integration.

ESPN and NBA.com are upstream dependencies without a formal first-party product API contract in this repository.

## 12. Background work and ingestion

The deployed timer runs every 15 minutes using `deploy/fcp-snapshot-refresh.timer`. It invokes a systemd oneshot service that posts a worker secret to `/admin/refresh-all`.

For each league, the worker:

- resolves and decrypts credentials;
- connects to ESPN;
- stores settings;
- derives standings;
- stores the rolling current scoreboard;
- stores the current immutable weekly scoreboard;
- backfills missing past scoreboards;
- stores current and past weekly transactions;
- records a weekly ESPN projection benchmark;
- computes power rankings;
- computes season statistics.

Failures are isolated by league, phase, and historical week.

League creation additionally uses FastAPI `BackgroundTasks` for an immediate first refresh. That job is process-bound and has no durable queue semantics.

No background system was found for NBA historical refresh, daily roster snapshots, daily score snapshots, model training, recap generation, or automated recap delivery.

## 13. Deployment and infrastructure

The current primary deployment appears to be:

- a VPS;
- Docker Compose;
- one FastAPI backend container;
- one Caddy container;
- static frontend files mounted from the host;
- external Supabase;
- a host-level systemd refresh timer;
- GitHub Actions deployment.

Caddy strips `/api`, proxies to FastAPI, serves the SPA, terminates TLS, and adds basic security headers.

GitHub Actions:

1. tests RLS against local Supabase;
2. runs backend tests;
3. pushes migrations to production;
4. builds the frontend with production environment values;
5. copies the static bundle to the VPS;
6. force-updates the server checkout to `main`;
7. rebuilds and recreates the Compose stack.

An older `render.yaml` still defines a Render web service, cron, and static site, but current deploy files and workflow indicate that this is historical or alternative infrastructure.

### Runtime persistence gaps

The Docker image copies only `backend/`. Compose mounts no backend data volume.

Consequences from the checked-in configuration:

- `data/projections` is created inside the backend container and lost on recreation.
- Uploaded projection sets and manifests are ephemeral.
- Weekly ESPN benchmark projections are ephemeral.
- `data/game_logs.db` is not copied into the image, so confidence endpoints cannot find their SQLite input unless production has an undocumented mount or image modification.
- `player_rankings/BBM_Projections.xls` is not copied, so the draft optimizer’s legacy fallback is absent.
- No volume or object-store persistence is documented for these inputs.

The health check only verifies that FastAPI returns `{"status":"ok"}`; it does not verify Supabase, ESPN configuration, projection storage, or historical-data availability.

Observability is logging-only. No metrics, tracing, error aggregation, job dashboard, or data-freshness alerting appears in the repository.

### Sensitive working-tree state observed during the audit

At review time, the uncommitted working-tree copy of `docs/DEPLOY.md` contained plaintext values that resembled live deployment credentials and API keys. The committed `HEAD` version contained empty placeholders, so those values were not present in the committed history inspected by this audit. No secret values are reproduced here.

## 14. Testing strategy

Safe local test suites were run without pytest cache or bytecode writes.

### Backend

- 554 passed
- 36 skipped
- 1 failed
- approximately 25 seconds

The one failure was the NBA ingestion rate-limit test because the current local `.venv` did not contain `nba_api`, although `requirements.txt` declares it. CI installs requirements from scratch, so this appears primarily to be local environment drift.

Backend coverage is especially strong around:

- recap assembly and storage;
- draft strategies and integration;
- projection schemas and adapters;
- projection accuracy;
- NBA ingestion;
- transactions;
- snapshot caching;
- auth and RLS policies;
- fantasy category behavior.

Most tests are hermetic and mock ESPN, Supabase, or persistence boundaries.

### Frontend

- 15 test files passed
- 62 tests passed
- approximately 8 seconds

Frontend tests cover routing, navigation, league home, creation, joining, redirects, accuracy, standings, and several utilities.

Coverage is comparatively weak around the largest components: Season, ScoreboardTools, DraftPage/Board, and full Newsroom orchestration.

### CI strengths and gaps

Strengths:

- Python 3.11 is aligned between CI and the Dockerfile.
- Frontend build, type-checking, tests, and lint exist.
- RLS policies are tested against a real local Supabase instance.
- Production migrations gate deployment.
- The Supabase CLI version is pinned.
- Frontend build output is checked for required production environment values.

Gaps:

- no end-to-end browser, API, and database test;
- no real backend/frontend contract test;
- no coverage threshold;
- no Python type-checking, linting, or security scan;
- live ESPN and real projection-file paths skip in CI;
- deployment does not depend on the separate frontend CI job, and its own workflow only repeats build and type-checking;
- Python dependencies use lower bounds rather than a lockfile;
- mocked persistence allowed the membership schema mismatch to pass;
- current-scoreboard frontend tests mock the incorrect contract.

## 15. Clean responsibility boundaries

The following areas are genuinely well separated:

- The canonical projection schema isolates consumers from BBM and ESPN column formats.
- Deterministic recap facts are separated from AI-generated prose.
- Recap snapshot, edition, and publication concepts are explicit.
- Awards are deterministic and testable.
- Provider-specific LLM logic is separated from recap service orchestration.
- ESPN transport timeouts and error translation are isolated in a gateway.
- The worker deliberately calls the live data layer instead of reading the snapshots it is populating.
- Snapshot refresh failures are isolated by phase.
- Immutable per-week data supports historical reconstruction.
- NBA ingestion, reading, and backtesting are separate modules.
- Frontend route structure and auth context are centralized.
- Supabase migrations provide an auditable history of authorization changes.

## 16. Coupled or unclear responsibilities

The most significant coupling is concentrated in a few hubs:

- `league/data_feed.py` is acquisition layer, domain service, transformer, projection joiner, scheduler helper, and legacy CLI.
- `recaps/assemble.py` understands storage shapes, ESPN reads, standings, power rankings, transactions, playoffs, data quality, and canonical API output.
- `RecapStore` is the application-wide database gateway despite living in the recap package.
- `frontend/api.ts` is the client contract for every feature and retains obsolete functions.
- The slug middleware performs routing, database lookup, credential decryption, and request-context construction.
- Draft Room combines per-league ESPN settings with global local projection state and global personal configuration.
- Confidence analytics depends on an implicit local SQLite file rather than a declared service boundary.
- Browser authorization and backend authorization are two different systems with different visibility semantics.
- Snapshot readers, live ESPN readers, and recap edition readers can supply different freshness and historical meanings to neighboring UI components.

## 17. Duplication and contract drift

Notable duplication includes:

- three snapshot representations;
- two frontend Card components and several Skeleton implementations;
- backend and frontend matchup calendars;
- multiple aliases for the same fields, such as `Team`/`team`, normalized percentage-rank keys, and older capitalized names;
- legacy flat routes plus slug routes;
- legacy optimizer endpoints plus Draft Room endpoints;
- legacy commentary endpoints plus structured recap generation;
- two Axios clients;
- current VPS deployment plus retained Render configuration;
- owner/admin columns plus membership roles;
- multiple mechanisms for “current league” resolution.

The large number of normalization fallbacks and alias lookups is evidence that the API contract has evolved through patches rather than through one versioned schema.

## 18. Most important weaknesses

### Critical correctness and security findings

1. **Private league API isolation is not enforced consistently.** Slug-scoped backend routes use the service role and generally lack user or membership checks, so RLS does not protect those responses.
2. **League creation does not match the repository schema.** It inserts a nonexistent membership `id`, and league plus membership creation is non-transactional.
3. **The live/current scoreboard frontend contract is wrong.** The backend returns an envelope; the active frontend path expects an array.
4. **Sensitive plaintext credentials existed in the uncommitted deployment document at review time.** They were not present in committed `HEAD`.
5. **Projection mutation and paid AI routes are unauthenticated.** Projection state is global and mutable; commentary routes can create external cost.

### Architectural weaknesses

- Local files act as production databases for projections and confidence analytics.
- Those files are not copied or persisted by the checked-in deployment.
- Multi-league identity exists, but projection activation and several draft settings remain global.
- Fantasy facts are stored mainly as JSON read models, limiting queryability and lineage.
- Team identity relies on mutable display names.
- Current versus historical data required successive overlapping snapshot fixes.
- Snapshot and live boundaries are not visible in the public contract beyond occasional `fetched_at` fields.
- League-specific time and season behavior is undermined by hardcoded 2025–26 calendars.
- There is no durable job system.
- The synchronous refresh path grows linearly with leagues and can be slow.
- External-service verification occurs on each protected request.
- Large files concentrate change risk.
- Documentation and comments frequently describe superseded behavior.

### Domain correctness risks

- Turnovers are mishandled in the live power-ranking dominance path.
- Ratio-category season aggregation needs a weighted-attempt audit.
- The confidence model uses a proxy team score as `player_avg` after rescaling, which is an approximation documented in code rather than a validated domain model.
- Global do-not-draft and position overrides can leak one owner’s judgment into every league.
- `DRAFT_LEAGUE_YEAR_DEFAULT=2025` can diverge from the selected league season.

## 19. Historical artifacts of expanding scope

Git history shows a compressed expansion:

- July 8: consolidation of older codebases.
- July 9–12: Draft Room and backend restructuring.
- July 12–15: recap persistence and projection framework.
- July 16 onward: React and product-platform overhaul.
- July 18–23: auth, memberships, invites, multi-league routes, and league creation.
- July 23–26: repeated historical-week correctness fixes.
- July 24: streaming, trades, daily snapshots, and FCP projection specs.
- August 6–21: NBA ingestion, accuracy scoring, backtesting, and CSV hardening.

The strongest historical artifacts are:

- “Patriot Games” defaults and owner-specific draft rules.
- Flat default-league paths retained beside slug-scoped routes.
- The default-league fallback.
- An originally local Parquet projection store in a deployed multi-league service.
- Rolling snapshots supplemented by per-week tables after historical-view defects.
- The recap-specific store becoming the general database access layer.
- Legacy commentary and optimizer APIs retained after newer products appeared.
- Render configuration beside a VPS deployment.
- Duplicated season calendars.
- 2025 and 2026-specific defaults.
- Extensive PR and phase-number commentary embedded in production code.
- README and dossier claims that no longer describe the system.
- Worker comments saying snapshots are in shadow mode even though reads have already flipped.
- Comments saying admin recap generation is force-fresh when the current call path is not.

## 20. Most important strengths

1. **Substantial domain IP already exists.** The draft engine, matchup canonicalization, standings reconstruction, power-ranking model, deterministic awards, projection accuracy, and historical consistency calculations are real product logic rather than UI scaffolding.
2. **The recap model is unusually disciplined.** Facts, data quality, generated prose, versioning, publication, and rollback are distinct concepts.
3. **Historical correctness has received serious attention.** Immutable weekly scoreboards and transactions allow “as of week” reconstruction rather than silently showing today’s state.
4. **Projection abstraction is sound.** Canonical fields, attempts-based percentage inputs, adapter boundaries, horizon and week scoping, and non-activating benchmark sets are thoughtful.
5. **External failure handling is pragmatic.** ESPN timeouts, typed errors, caching, single-flight behavior, honest empty states, and worker failure isolation address real production conditions.
6. **The authorization work is not superficial.** Although the backend boundary is incomplete, database policies include column-level membership updates, invite redemption locking, team uniqueness, role protection, and local RLS tests.
7. **Tests are extensive for a project of this age.** More than 550 backend tests protect the most complicated domain code.
8. **The repository preserves decision history.** Specs and git history make it possible to distinguish built features from future intent and to understand why overlapping systems exist.

## Areas requiring deeper investigation

These cannot be resolved confidently from source alone:

- The actual production Supabase schema, especially whether it has drifted from migrations and whether the membership `id` exists there.
- A live authorization audit of private-league endpoints.
- Production filesystem mounts or manual data copied into the backend container.
- Whether projection uploads and ESPN benchmark sets currently survive a deploy.
- Whether `game_logs.db` is available in production.
- Actual systemd execution duration, failures, and overlap behavior across multiple leagues.
- ESPN request volume and rate behavior under concurrent page loads and refresh jobs.
- Production Supabase signup, email-confirmation, SMTP, and redirect configuration.
- Numerical validation of FG% and FT% aggregation with unequal attempts.
- End-to-end multi-league isolation, especially global projection activation and draft configuration.
- Actual data coverage in `nba_player_bio` and `nba_player_seasons`.
- How NBA ingestion is run operationally.
- The full blast radius of the scoreboard response mismatch in deployed UI behavior.
- Current use of legacy optimizer and commentary routes.
- Whether the uncommitted credentials observed in `docs/DEPLOY.md` correspond to active systems.
- Production usage, latency, retention, and error telemetry; none is in the repository.
- Projection-source licensing and the legal ability to store or redistribute BBM-derived data.
- Whether the knowledge graph’s remaining stale community nodes reflect removed migrations or indexing residue.

## Product questions the repository cannot answer

- Who is the primary user now: commissioner, individual manager, league group, content creator, or fantasy power user?
- Which is the core product: Draft Room, matchup decision support, Newsroom, or FCP projections?
- Is FCP intended for one trusted league, invited private leagues, or open public signup?
- Should every league member see all league analysis, or should some tools be private to one manager?
- Who is allowed to choose or upload the active projection source?
- Is projection choice global, per league, per manager, or per matchup?
- Is the Draft Room a private competitive advantage or a league-shared surface?
- Should private leagues be discoverable or accessible by slug?
- What freshness guarantee does a user expect: live, 15 minutes, daily, or “as of last successful refresh”?
- How should the product behave during ESPN outages or slowdowns?
- Is ESPN the permanent source of truth, or must leagues survive platform migration?
- Are Yahoo and Sleeper real roadmap commitments?
- How are renamed ESPN teams, transferred ownership, and season-to-season identities meant to work?
- Is the projection accuracy page internal, commissioner-only, or customer-facing?
- Is FCP expected to generate its own projections or mainly compare licensed sources?
- What are the acceptable LLM costs and who is authorized to incur them?
- Is recap editorial quality a retention feature, a commissioner utility, or the main differentiator?
- Is direct WhatsApp, Discord, or Slack delivery required?
- What multi-season history should be retained?
- What deletion, privacy, data-export, and credential-retention obligations apply?
- What scale is expected in users, leagues, and simultaneous drafts?
- Is mobile browser support sufficient, or is a mobile application part of the product?
- What is the planned process for season rollover and calendar updates?
- What evidence exists that current users value each major surface?

---

This document is a forensic reconstruction of the current repository. It intentionally does not design or recommend a replacement architecture.
