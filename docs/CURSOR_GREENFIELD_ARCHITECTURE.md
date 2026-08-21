# FCP Greenfield Architecture

**Date:** 2026-08-21  
**Author:** Cursor  
**Phase:** Architecture (after forensic audit)  
**Authority:** [`PRODUCT_CONSTITUTION.md`](PRODUCT_CONSTITUTION.md). Where the 2026-08-21 audit’s inferred product vision conflicts with the constitution, the constitution wins.  
**Constraint:** sunk development cost is zero. Do not rebuild something merely because greenfield is cleaner.  
**This document does not implement anything.**

The question this phase answers:

> If FCP did not exist today and we were starting from an empty repository with this Product Constitution, what architecture would you choose?

Then: classify the current repository against that design, and pick one rebuild strategy.

---

## 0. Design thesis

FCP is one product with two faces, powered by one intelligence layer:

```
                    ┌─────────────────────────┐
                    │  Basketball intelligence │
                    │  (pure, explicit inputs) │
                    └────────────┬────────────┘
           shared facts          │         private view
                 ▼               │              ▼
     League world (newsroom,     │    Manager weapons (draft,
     standings, awards,          │    streaming, trades,
     published recaps)           │    projections, adjustments)
```

That split is not a navigation preference. It is the tenancy, persistence, and API model.

Three rules make the rest of the design small:

1. **Providers are adapters.** ESPN never leaks into domain types.
2. **Every computation is a pure function of explicit inputs.** Shared mode and private mode are the same functions with different projection views. There is no ambient “active projections” singleton.
3. **Week finality is a first-class state.** Live, periodic, and immutable are properties of rows, not of whichever handler a PR happened to write.

Scale target: hundreds to thousands of users and leagues. One API process, one worker process, one Postgres. No microservices, no Kafka, no “the active league on this container.”

---

## 1. Overall system architecture

Three deployable units, one codebase:

```
           HTTPS
             │
           Caddy
          /     \
        SPA     /api
         │        │
      static    FastAPI  ────── Postgres (hosted)
                  │
                  │  same image, second process
                  ▼
              job worker
           (claim rows from `jobs`)
                  │
                  ├── ESPN / Yahoo / Sleeper adapters
                  ├── NBA ingest
                  └── LLM (recap prose only)
```

**Why this, not more:**

- Constitution §16/§20: operational simplicity, realistic scale.
- The current refresh-all-leagues-in-one-HTTP-call model fails in the *tens* of leagues. A per-league job row is the smallest thing that actually fixes that. A queue product is not required.
- The current dual client (browser → FastAPI **and** browser → Supabase RLS) is how private data, authz, and “where does a feature go?” became unanswerable. The browser talks **only** to FastAPI. Postgres is not a public API.

**What hosted services are for:**

| Need | Choice |
|---|---|
| Database | Hosted Postgres (Supabase as vendor is fine) |
| Auth | Supabase Auth *or* first-party sessions. Either is fine. FastAPI is the authorization boundary either way. |
| Files | Almost none. Projections live in Postgres. Uploads are parsed and discarded. |
| Cache | Postgres for periodic facts. Process memory only inside a single job run. |
| Object storage | Optional later for original upload bytes (audit trail). Not required for v1. |

Not in v1: Redis, Celery, Next.js, Kubernetes, a second region, billing.

---

## 2. Frontend architecture

Keep a **React 19 + Vite + Tailwind SPA**. The Draft Room and matchup tools are client-state-dense. SSR/Next.js does not earn its cost here (constitution non-goal: native apps, SEO farm). Two public surfaces need shareable URLs — landing and published recaps — and FastAPI can prerender those if unfurling matters.

### Information architecture

Shared league world and private weapons are different route trees, not different tabs of the same page.

```
/                                 landing / home resolver
/login  /signup  /reset-password

/leagues/:slug                    League Home (shared)
/leagues/:slug/matchups/:week     matchup results (shared facts)
/leagues/:slug/standings
/leagues/:slug/newsroom/:season/:week
/leagues/:slug/history            multi-season archive (shared)

/leagues/:slug/me                 private hub for this league
/leagues/:slug/me/draft           Draft Room
/leagues/:slug/me/projections     source + horizon + adjustments
/leagues/:slug/me/watchlist       later

/leagues/new                      create / connect (auth)
/settings                         account, memberships
```

Nav for a league you belong to:

**Home · Matchup · Newsroom · Standings · My tools**

“My tools” is the private tree. Draft does not sit in a public More sheet as if it were a league page.

### Data fetching

- TanStack Query for all reads.
- Reads auto-load. Buttons are only for mutations that cost money or change durable state (generate recap, run solver, upload projections, publish).
- Every payload the UI cares about includes `{ as_of, freshness }`. The UI can show a stale stamp without reverse-engineering the backend.
- No direct Supabase table access from the browser for business data. Auth session only.

### Component split

- `ui/` primitives used everywhere (one Card, one StateBlock).
- `league/` shared surfaces.
- `me/` private surfaces (Draft Room lives here).
- Domain types generated from or mirrored with the API, not a second calendar hardcoded in TypeScript.

### What not to do

- Do not default the app to Draft Room.
- Do not keep a client-side “admin mode” toggle that is not backed by a membership role.
- Do not persist private strategy only in `localStorage`.

---

## 3. Backend / application architecture

Python stays. The valuable math is already Python (numpy/pandas/cvxpy). Rewriting it in TypeScript would be cleanliness, not quality.

### Layers (the constitution’s §9, as packages)

```
backend/
  domain/          # pure basketball + fantasy rules. No HTTP, no ESPN, no SQL.
  app/             # use-cases. Orchestrates domain + ports. Transactions.
  adapters/
    espn/          # transport + mapping to normalized DTOs
    nba/
    projections_io/# BBM / Hashtag file parsers
    llm/           # prose only, never facts
    persistence/   # SQL repositories
  api/             # FastAPI. Authn/authz. Thin.
  jobs/            # worker loop. Same app services as API.
```

**Import rule:** `domain` imports nothing in `adapters`, `api`, or `jobs`. `api` and `jobs` both call `app`. If a new feature cannot find a home without importing ESPN into `domain`, the design is already failing.

### Domain is pure functions of explicit inputs

Constitution §4 and §5 are in tension (one intelligence layer vs per-user projections). The resolution:

```
shared  = compute(facts, projection_view = league.default, adjustments = none)
private = compute(facts, projection_view = user.choice,    adjustments = user.adjustments)
```

`get_active_projections()` as a process-global singleton is forbidden. Every valuing function takes a `ProjectionView`.

### Application services (examples)

| Service | Does |
|---|---|
| `ConnectLeague` | Validate provider credentials, persist encrypted, enqueue first refresh |
| `RefreshLeague` | Adapter pull → normalize → upsert current + maybe finalize weeks |
| `AssembleWeekFacts` | Deterministic story inputs from frozen/live facts |
| `GenerateRecap` | Facts → LLM prose → draft edition |
| `PublishRecap` | Atomic publish (one published row per week) |
| `OptimizeDraft` | ProjectionView + league settings + user prefs → plans |
| `IngestProjectionUpload` | Parse → resolve player ids → store set (private to user) |
| `SetProjectionPreference` | Per (user, league, horizon) |

---

## 4. Canonical domain model

FCP owns these concepts. Provider objects never *are* these concepts.

| Entity | Meaning |
|---|---|
| **User** | A manager (or commissioner). May belong to many leagues. |
| **League** | An FCP league. Has a provider, a season, scoring/roster settings, visibility. |
| **Membership** | User ↔ League. Role + which **FantasyTeam** they claim. |
| **FantasyTeam** | A franchise in a league. Stable FCP id. Provider team id is a mapping, not the PK. |
| **Season** | League-year. Settings can change across seasons; history does not. |
| **MatchupPeriod** | One fantasy week. Has `status`: `upcoming` \| `live` \| `final`. |
| **Matchup** | Two teams, 9 category scores, winner (including provider tiebreak). |
| **RosterSlot** | Player on a team at a time, with lineup slot. |
| **Transaction** | Add/drop/trade with a timestamp and period. |
| **Player** | FCP person. Not a name string. |
| **ProjectionSet / ProjectionRow** | A source × horizon snapshot of per-player rates. |
| **ProjectionAdjustment** | User overlay; never mutates the set. |
| **RecapFactSnapshot** | Deterministic week facts. |
| **RecapEdition** | Editorial prose bound to a fact snapshot. |
| **DraftSession** | Private per-user draft state. |

Scoring: v1 assumes **9-cat H2H each-category** (`PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, TO` with TO lower-is-better). Settings are data on the league so a later format is a settings change, not a rewrite — but v1 does not implement other formats.

---

## 5. Player identity model

Names are an ingest heuristic. They are never a join key.

```
players
  id              uuid PK
  display_name    text not null
  nba_person_id   int unique null
  birthdate, position, ...     -- from NBA bio when known
  created_at

player_external_ids
  player_id       uuid FK
  source          text  -- 'espn' | 'nba' | 'bbm' | 'hashtag' | 'yahoo' | 'sleeper'
  external_id     text
  unique (source, external_id)

player_aliases
  id
  player_id       uuid FK
  normalized_name text
  source          text
  unique (source, normalized_name)
```

**Resolution pipeline (ingest only):**

1. Exact `player_external_ids` hit.
2. Alias table hit.
3. Fuzzy name match against aliases, **queued for review** if below a high threshold.
4. Unmatched rows are stored on the ingest report. They are **not** silently omitted from a private upload without telling the user. They are **never** allowed to vanish from shared league facts.

All domain joins: `player_id`.

The current `PlayerProjection.player_key` (normalized name) becomes `player_id`. Display name remains a field, not an identity.

---

## 6. League / provider normalization

```
leagues
  id, slug, name, visibility, timezone
  provider            text  -- 'espn' | 'yahoo' | 'sleeper'
  provider_league_id  text
  provider_season     int
  scoring_settings    jsonb  -- normalized, not ESPN-shaped
  roster_settings     jsonb
  default_horizon_source  -- FK to a redistributable ProjectionSet (FCP or ESPN)
  recap_voice         text
  owner_user_id

league_credentials
  league_id
  ciphertext          -- pgcrypto or app-level encrypt
  last_ok_at, last_error
  -- service-role / backend only

fantasy_teams
  id, league_id, display_name
  provider_team_id    text
  unique (league_id, provider_team_id)

memberships
  league_id, user_id
  role                -- owner | admin | member
  fantasy_team_id     null  -- claimed team
  unique (league_id, user_id)
  unique (league_id, fantasy_team_id) where not null
```

**Normalized pull DTO** (adapter output, not a table):

```text
NormalizedLeaguePull
  settings, teams[],
  current_period,
  matchups[] (period, home, away, cat scores, winner),
  rosters[]  (team, as_of, slots[]),
  transactions[]
```

Domain code consumes this DTO. It never sees `espn_api.basketball.League`.

---

## 7. ESPN integration boundary

One package, two jobs: **talk to ESPN** and **map ESPN → NormalizedLeaguePull**.

```
adapters/espn/
  gateway.py     # timeouts, typed errors (KEEP the existing idea)
  client.py      # cookies, mTransactions2, box scores, settings
  map.py         # ESPN structures → NormalizedLeaguePull
```

Rules:

- No domain class subclasses `espn_api` types.
- Timeouts are mandatory (5s connect / 15s read is a proven policy).
- ESPN request volume scales with `leagues × job cadence`, never with page views.
- Raw provider payloads may be stored as `provider_payloads(league_id, pulled_at, kind, json)` for replay and debugging. They are **source data**, not the read model.

Private-league cookies stay encrypted, decrypted only in the worker/connect path, never returned to the browser.

---

## 8. Future Yahoo / Sleeper

Do not implement them.

Implement the **port**:

```python
class FantasyProvider(Protocol):
    def preview(self, creds) -> LeaguePreview: ...
    def pull(self, creds) -> NormalizedLeaguePull: ...
    def pro_schedule(self, season) -> ProSchedule: ...
```

Yahoo/Sleeper become another adapter + `player_external_ids` source. If adding them requires editing `domain/matchup.py`, the boundary has already failed.

Landing copy may say “ESPN now, Yahoo/Sleeper later.” The schema already has `provider`.

---

## 9. Projection model and projection-source architecture

Keep the **idea** of a canonical per-player row every adapter must emit. Change the identity field and store it in Postgres.

```
projection_sources:  fcp | espn | bbm | hashtag | custom
projection_horizons: rest_of_week | rest_of_season | preseason | custom_window

projection_sets
  id
  source, horizon
  owner_user_id     null = platform/league-shared
  league_id         null = global (FCP model, ESPN-last-15 template)
  visibility        'private' | 'league_shared' | 'platform'
  created_at, row_count, unmatched_count
  -- paid third-party uploads: owner_user_id set, visibility=private always

projection_rows
  set_id, player_id
  games, minutes_pg
  pts_pg, reb_pg, ast_pg, stl_pg, blk_pg, tpm_pg, to_pg
  fgm_pg, fga_pg, ftm_pg, fta_pg     -- makes AND attempts
  fg_pct, ft_pct                     -- derived if missing
  nba_team, positions[]
  unique (set_id, player_id)
```

**Adapters** parse native formats into rows, then the ingest service resolves `player_id`. Consumers never see BBM column names.

**FCP’s own model** (not required in the first rebuilt version) is another adapter that *writes* a `projection_sets` row with `source='fcp'`. No consumer changes. That is the property worth preserving from today’s framework.

**Redistribution:** Basketball Monster / Hashtag uploads are **private to the uploading user**. They cannot be a league’s shared default. Shared newsroom/power rankings use a **pinned redistributable** source (ESPN-derived or, later, FCP). Constitution §5 is a legal constraint, not a UX preference.

---

## 10. User projection uploads

Flow:

1. Authenticated POST `/leagues/{slug}/me/projections` with file + declared source + horizon.
2. Adapter `detect` / `parse`.
3. Resolve names → `player_id`; return unmatched list (user-visible, not silent).
4. Persist set + rows. Original file optional in object storage.
5. Does **not** become “active for the deployment.” It becomes a set the **user** may select.

No `pd.read_excel(server_path)`. No world-writable disk manifest.

---

## 11. Projection horizons

Horizon is a column, not a filename convention.

| Horizon | Used by |
|---|---|
| `rest_of_week` | streaming, live matchup projection, add/drop |
| `rest_of_season` | trades, roster construction, playoff planning |
| `preseason` | Draft Room |
| `custom_window` | later (e.g. “next 3 weeks”) |

A user’s preference is per `(user, league, horizon)`. Draft Room does not silently use last week’s streamer sheet.

---

## 12. User projection adjustments

Adjustments **compose**. They never overwrite the set.

```
projection_adjustments
  id
  user_id, league_id, player_id
  -- sparse overlays:
  minutes_pg, games, usg_note, rate_multipliers jsonb
  reason text
  unique (user_id, league_id, player_id)
```

```
effective_row = apply_adjustments(base_row, adjustment | none)
```

Shared analytics pass `adjustments=none`. Private tools pass the user’s overlay. Two managers in one league can disagree about a player’s minutes without fighting over a global parquet file.

v1 can ship the table and a minimal UI (minutes / games). Full assumption-maintenance UI waits for the FCP model. The **concept** must exist so the model does not force a redesign.

---

## 13. Shared vs private analytics

| | Shared (league world) | Private (manager weapons) |
|---|---|---|
| Projection source | League default (redistributable) | User preference |
| Adjustments | None | User overlays |
| Visibility | Public-league anyone / members of private leagues | Only that user |
| Examples | standings, published recap, awards, shared power rankings | draft plans, watchlist, trade sandbox, waiver list |
| API prefix | `/leagues/{slug}/...` | `/leagues/{slug}/me/...` |

Power rankings in the newsroom are **shared** and therefore use the league default. A private “my rankings under my BBM sheet” can exist later under `/me` without contaminating the newsroom.

Draft Room strategy, DND lists, targets, and solver knobs are **private rows**, not env vars, not `localStorage`.

---

## 14. Persistence model

**Postgres is the system of record for everything durable.**

| Data | Store |
|---|---|
| Users, memberships, leagues, teams | Tables |
| Credentials | Encrypted columns, backend-only |
| Current + historical matchups, transactions, rosters | Tables (see §15) |
| Projection sets/rows, preferences, adjustments | Tables |
| Recap facts + editions | Tables (publication model from today, kept) |
| NBA bios/seasons | Tables (already the right grain) |
| Draft sessions | Tables (JSON state for the plan snapshot is OK) |
| Job queue | `jobs` table |
| Provider raw pull | Optional `provider_payloads` jsonb |

Not used as systems of record: parquet, `manifest.json`, `player_rankings/*.xls`, `data/game_logs.db`, container-local disk.

JSONB is allowed **inside** a real entity (scoring settings, draft plan snapshot, recap structured content). It is not allowed as a substitute for having a `matchups` table.

---

## 15. Historical-data model and freshness

The missing concept in the current app is **period finality**.

```
matchup_periods
  league_id, season, period_index
  starts_on, ends_on
  status  -- upcoming | live | final
  unique (league_id, season, period_index)

matchups
  id, league_id, period_id
  home_team_id, away_team_id
  category_scores jsonb   -- 9 cats for each side
  winner_team_id null     -- includes provider tiebreak
  unique (league_id, period_id, home_team_id)

transactions
  id, league_id, occurred_at, period_id
  type, team_id, player_id, counterparty_team_id null
  payload jsonb           -- extras, not a substitute for the typed columns

roster_observations
  id, league_id, team_id, captured_on, player_id, slot
  -- daily during live season; ESPN will not reconstruct yesterday
```

**Freshness class is on the data:**

| Class | What | How the UI knows |
|---|---|---|
| **Live** | Current period scoreboard, current roster, in-progress draft | `freshness=live`, short `as_of` |
| **Periodic** | Standings (if derived from mixed live+final), power rankings, accuracy | `freshness=periodic`, worker `as_of` |
| **Final** | Completed periods’ matchups, transactions, published recap facts, NBA seasons | `freshness=final`, never silently replaced |

When a period flips to `final`, the worker stops refetching it except for an explicit admin repair. “What did this league look like after week 7?” is `WHERE period_index <= 7 AND status = 'final'` plus standings derived from those matchups — the same function used for current standings, with a different input set.

Daily `roster_observations` are a **durability job**, not a user-facing feature. Constitution §10 cannot be satisfied from ESPN after the fact.

This replaces the three overlapping snapshot blob tables (`league_state_snapshots`, `league_week_scoreboards`, `league_week_transactions`) with typed history. Recap **editorial** snapshots remain a separate versioned artifact (facts chosen for a publish), not the league’s operational history.

---

## 16. Jobs / background processing

One worker process. Same Docker image as the API. Postgres is the queue.

```
jobs
  id, type, league_id null, payload jsonb
  run_after, status, attempts, locked_at, last_error
```

Worker loop: `SELECT … FOR UPDATE SKIP LOCKED`, run, retry with backoff, dead-letter after N.

| Job | Cadence | Isolation |
|---|---|---|
| `refresh_league` | ~15 min in NBA windows, slower otherwise | **One league per job** |
| `capture_rosters` | Daily post-waiver, in-season only | Per league |
| `ingest_nba` | Nightly | Global |
| `generate_recap` | On admin action (optional async) | Per league-week |
| `run_fcp_model` | Later | Global |

**Forbidden:** one HTTP handler that loops every league until a 900s timeout.

Admin UI shows per-league `last_ok_at` / `last_error` (constitution-adjacent to N-5). Expired ESPN cookies are a reconnect flow, not silent staleness.

LLM and solver work may stay synchronous in v1 if they finish in seconds; if they do not, they become jobs. The **interface** is an app service, so moving them off the request path is not a redesign.

---

## 17. Authentication and authorization

Assumptions the architecture **refuses** (constitution §17): one trusted user, one trusted league, unlimited LLM, unlimited ESPN.

**Authentication:** session or JWT, verified in FastAPI on every non-public route.

**Authorization, structurally unbypassable:**

```python
# Every league route
user = require_user()                  # 401
league = load_league(slug)             # 404
ctx = authorize_league(user, league, need: 'read_shared' | 'member' | 'admin' | 'private_self')
```

There is no “if no slug, first league in the database.” There is no unauthenticated `/matchup-commentary`. There is no `out_prefix` writing server files.

| Surface | Who |
|---|---|
| Public league shared reads | Anyone (or signed-in, product choice) |
| Private league shared reads | Members |
| `/me/*` | The authenticated member; rows filtered by `user_id` |
| Recap generate/publish | Admin/owner |
| Connect/reconnect ESPN | Admin/owner |
| Worker | `WORKER_SECRET` or internal-only network, not a user JWT |

LLM endpoints: authenticated, rate-limited, attributed to `user_id` for cost.

Uploads: size-capped, parsed in process, never a server path chosen by the client.

---

## 18. Tenant isolation

Tenancy keys:

- **League** owns settings, teams, matchups, transactions, shared recaps, shared default projections.
- **User** owns projection preferences, adjustments, draft sessions, watchlists, private uploads.
- **Membership** is the only bridge.

Query pattern: every table that is not global NBA/player identity has `league_id` and/or `user_id`. Repositories always take those ids from `AuthContext`, never from a client-supplied body alone.

Private league snapshots are **not** world-readable in the database. The API enforces membership; RLS can mirror that as defense in depth. The API is still the boundary (no browser service role, no “RLS is the product”).

Global tables: `players`, `player_external_ids`, `nba_*`. They are not secret; they are also not writable by users.

---

## 19. API design

Versioned, boring HTTP JSON.

```
/v1/health

/v1/me
/v1/me/leagues

/v1/leagues                              POST create
/v1/leagues/preview                      POST provider validate
/v1/leagues/{slug}                       GET shared summary
/v1/leagues/{slug}/periods/{n}/matchups
/v1/leagues/{slug}/standings?as_of_period=
/v1/leagues/{slug}/newsroom/...
/v1/leagues/{slug}/me/draft/...
/v1/leagues/{slug}/me/projections
/v1/leagues/{slug}/me/adjustments

/v1/admin/jobs
/v1/internal/jobs/claim                  # worker, secret
```

Envelope for reads:

```json
{
  "data": {},
  "as_of": "2026-08-21T12:00:00Z",
  "freshness": "periodic",
  "period": { "index": 3, "status": "live" }
}
```

Private resources never appear on shared routes. Shared facts never require a projection preference cookie.

---

## 20. Caching

| Layer | Use |
|---|---|
| Postgres | The cache for periodic league analytics. Worker writes, API reads. |
| React Query | UI freshness (60s is fine). |
| In-job memory | Reuse one ESPN `League` construction inside a single `refresh_league` run. |
| CDN | Static SPA + published recap HTML if prerendered. |

No process-global `MyLeague` TTL that makes a second container wrong. No “request cache middleware” as a substitute for not hitting ESPN on GET.

---

## 21. Deployment

Keep the shape that already works operationally:

- VPS (or any single VM)
- Docker Compose: `api`, `worker`, `caddy`
- Hosted Postgres
- GitHub Actions: test → migrate → build SPA → deploy

Secrets in the environment, never in `docs/`. Frontend env is only `VITE_API_BASE` + auth public keys. **No baked league slug as identity.**

Two processes, one image. Worker does not take public HTTP.

This is enough for thousands of users. When it is not, the first knob is “more worker replicas claiming jobs,” not a rewrite.

---

## 22. Observability

Constitution §20 omitted this. It belongs next to testability: **you can tell when it is broken.**

- Structured logs: `request_id`, `user_id`, `league_id`, `job_id`, `phase`, `duration_ms`.
- Per-league: last refresh success/error, ESPN auth health.
- Per-ingest: unmatched player count (never silent drop).
- LLM: tokens, cost, user_id, latency, schema-validation failures.
- Error tracking (Sentry or equivalent) on API + worker.
- A `/v1/admin/health/leagues` that a human can read.

Silent 500s on `/matchup-confidence` and 140s ESPN constructions discovered only in log archaeology are architecture failures, not ops accidents.

---

## 23. Testing strategy

| Kind | What |
|---|---|
| Domain unit | All-play, category direction, standings-from-matchups, awards, adjustment composition, draft engine health/relax — **committed synthetic fixtures**, no gitignored xls |
| Adapter contract | Recorded ESPN/NBA payloads → `NormalizedLeaguePull` / projection rows |
| App service | Refresh upsert + finality; recap publish uniqueness; projection ingest unmatched report |
| Authz | Private `/me` rows invisible to another member; private league 404/403 to strangers; LLM 401 |
| API | Freshness envelope; no ESPN mock invoked on final-period GET |
| Frontend | Route trees, auth gates, no Load button on reads |
| Job | Isolation: league A failure does not skip league B |

Live ESPN is not CI. Recorded fixtures are.

The current optimizer’s CI skip-on-missing-xls is unacceptable to port. **Port the algorithm only after a synthetic pool fixture is committed.**

---

## 24. Repository / file structure

```
frontend/                     # React SPA
backend/
  domain/
    player.py
    league.py
    matchup.py
    scoring.py                # 9-cat, TO direction
    allplay.py                # today’s WeeklyScoreboard, renamed/cleaned
    projections.py            # PlayerProjection + apply_adjustments
    value.py                  # Forge-style VORP
    draft/                    # engine, strategies, targets_mc, optimizer
    recap_facts.py
    awards.py
  app/                        # use-cases
  adapters/espn/ nba/ llm/ projections_io/ persistence/
  api/routers/
  jobs/
docs/
  PRODUCT_CONSTITUTION.md
tests/                        # mirrors domain/app/adapters
```

An engineer or agent answering constitution §21 should open `backend/domain/` and `backend/adapters/` and be done. Not `data_feed.py`.

---

## 25. Important data flows

### League refresh (periodic)

```
job refresh_league(league_id)
  → decrypt creds
  → ESPN adapter.pull
  → optionally store provider_payload
  → upsert settings, teams, live matchups, live rosters, transactions
  → if period should finalize: set status=final, freeze scores
  → recompute derived shared analytics (all-play, power rankings, standings)
     using league default ProjectionView only where projections are required
  → write as_of
```

User GETs **do not** call ESPN.

### Private projected matchup

```
GET /leagues/{slug}/me/matchups/current/projection
  → auth member
  → facts from live matchup + remaining schedule
  → ProjectionView(user preference, user adjustments, rest_of_week)
  → domain.project_matchup(facts, view)
```

### Recap

```
facts = AssembleWeekFacts(league, period)     # deterministic
edition = LLM(facts, league.recap_voice)      # prose only
publish_recap_edition()                       # one published row
```

LLM never writes standings or awards.

### Draft

```
session (user, league) holds pool + picks + knobs
view = preseason ProjectionView(user)
plans = domain.draft.generate_portfolio(settings, view, prefs)
# engine.py health/recompute stays a pure function
```

---

## 26. Proposed tables (checklist)

**Identity & tenancy:** `users/profiles`, `leagues`, `league_credentials`, `fantasy_teams`, `memberships`, `league_invites`

**Players:** `players`, `player_external_ids`, `player_aliases`

**League history:** `matchup_periods`, `matchups`, `transactions`, `roster_observations`

**Derived shared (materialized, recomputable):** `period_allplay`, `power_ranking_snapshots` (optional; can compute on read at this scale)

**Projections:** `projection_sets`, `projection_rows`, `projection_preferences`, `projection_adjustments`

**Newsroom:** `recap_fact_snapshots`, `recap_editions`, `power_ranking_editions` (LLM blurb cache — keep the idea)

**Private tools:** `draft_sessions`, later `watchlist_items`, `saved_trades`

**NBA:** `nba_player_bio`, `nba_player_seasons` (keep grain)

**Ops:** `jobs`, `provider_payloads` (optional)

---

# Comparison to the current repository

Classification key:

- **KEEP** — use as-is (or with trivial wrapping)
- **KEEP BUT CLEAN UP** — same idea/algorithm; move, rename, fixture, stop the surrounding mess
- **REFACTOR** — same subsystem, reshape in place would be enough *if we were keeping the app*
- **REPLACE** — concept stays; implementation/API/schema around it should not
- **DELETE** — do not take forward

Preserve means one of: **concept**, **algorithm**, **data model**, **implementation**. They are not the same.

| Subsystem | Verdict | Preserve | Do not preserve |
|---|---|---|---|
| 9-cat + TO lower-is-better | **KEEP** | concept + algorithm | — |
| `WeeklyScoreboard` all-play | **KEEP BUT CLEAN UP** | algorithm (already ESPN-free) | `MyLeague` subclassing ESPN to feed it |
| Historical standings from week scoreboards | **KEEP BUT CLEAN UP** | algorithm | three blob tables + try/except reconciliation |
| Recap fact assembly | **KEEP BUT CLEAN UP** | algorithm + “facts ≠ prose” concept | import of FastAPI routers; live ESPN generate path confusion |
| Recap editions + `publish_recap_edition` | **KEEP** | data model + implementation idea (versioned facts, one published row, security-definer publish) | coupling to `RecapStore` as god client |
| Deterministic awards | **KEEP** | algorithm | — |
| Power-ranking composite weights | **KEEP BUT CLEAN UP** | algorithm (0.35/0.35/0.20/0.10) | computing it only as a JSON blob in a rolling snapshot |
| Canonical `PlayerProjection` fields | **KEEP BUT CLEAN UP** | schema concept (per-game + makes/attempts) | `player_key` as name; parquet store; global active map |
| Projection adapters (BBM/Hashtag/ESPN) | **KEEP BUT CLEAN UP** | parse logic | upload API that only accepts BBM; silent unmatched drops |
| Projection accuracy + backtest harness | **KEEP BUT CLEAN UP** | concept + tests/harness | wiring to ephemeral disk sets |
| `nba_player_*` grain | **KEEP** | data model | ingest importing ESPN `normalize_name` as identity |
| Draft `engine.py` (pure health/recompute) | **KEEP** | algorithm + implementation | stateless “client holds everything” as the privacy story |
| Draft strategies / MC targets / Forge Value / cvxpy optimizer | **KEEP BUT CLEAN UP** | algorithms **after** a committed synthetic fixture proves them in CI | unauthenticated global routes; env-var DND; `localStorage` as store; `/optimizer/*` duplicate API |
| ESPN gateway timeouts + typed errors | **KEEP** | implementation idea | patching library internals if a thin client can wrap calls instead |
| `mTransactions2` adapter | **KEEP BUT CLEAN UP** | mapping logic | living inside `data_feed.py` |
| Create-league preview (don’t validate the seeded league) | **KEEP BUT CLEAN UP** | concept | — |
| League-scoped React IA, AuthProvider, newsroom UI, League Home | **KEEP BUT CLEAN UP** | concept + a lot of UI | dual Card; Season “Load” button; newsroom admin toggle; baked `VITE_RECAP_LEAGUE_SLUG` identity |
| Memberships + invites + team claim + RLS tests | **KEEP BUT CLEAN UP** | data model | browser writing business tables; team identity as a bare name with no `fantasy_teams` row |
| pgcrypto credential encryption | **KEEP** | concept | decrypt RPC usable as a confused-deputy if ever granted beyond backend |
| Job *idea* (pull ESPN off the GET path) | **KEEP BUT CLEAN UP** | concept | `refresh-all` as one HTTP request; cron comments still saying Render |
| `data_feed.py` as a module | **DELETE** | extract the few algorithms above | the module |
| `MyLeague(League)` / `ScoreboardLeague` as domain | **REPLACE** | none of the inheritance | ESPN-is-the-domain |
| `RecapStore` god client | **REPLACE** | PostgREST-or-SQL access per aggregate | one class for leagues + recaps + NBA + snapshots |
| Flat `/draft`, `/optimizer`, `/projections`, `/commentary` | **REPLACE** | none | global first-league fallback |
| Legacy commentary endpoints (ungated LLM) | **DELETE** or fold into authenticated recap/matchup services | prompt fragments if they are good | public cost surface |
| Process-global `DO_NOT_DRAFT`, matchup calendars in two languages | **REPLACE** | user/league preferences; period dates from provider settings | env and hardcoded weeks |
| Parquet projection store + Docker disk | **DELETE** | — | — |
| `data/game_logs.db` confidence path | **REPLACE** | later, derived from NBA game logs in Postgres if we still want tiers | a SQLite file that is not in the image |
| Three snapshot blob tables as operational history | **REPLACE** | the *need* for history | rolling+weekly+editorial as three competing truths |
| `render.yaml` as production | **DELETE** | — | leftover |
| Secrets in `DEPLOY.md` | **DELETE** | runbook structure without values | committed credentials |
| Streamlit | already gone | — | — |
| Playoff Monte Carlo (`season_simulation.py`) | **DELETE** until product asks | nothing in this repo | do not resurrect from archive unless constitution grows a “playoff odds” clause |
| Streaming advisor / trade analyzer product | **ABSENT — do not build in the rebuild vertical slice** | natural home in `domain/` + `/me` | duplicating projections/identity per spec |

---

# Recommendation

**Option 4 — Preserve domain logic but rebuild the application around it.**

Not 1 (as-is): the constitution is violated on identity, tenancy, provider boundary, private data, freshness, and authz. Continuing as-is ships three products that share a name-join and an ESPN socket.

Not 2 (refactor selected areas): the domain model *is* `espn_api.League`. Player identity *is* a string. Private strategy *does not exist* as data. Those are not local cleanups. In-place refactor would spend the same tokens fighting types that should not exist.

Not 3 (rebuild major subsystems): too vague, and it would invite rewriting the newsroom *or* the optimizer as a trophy while leaving ESPN in the domain.

Not 5 (full greenfield restart): that would discard the parts that already satisfy the constitution — recap publication, all-play math, category rules, projection row shape, accuracy/backtest sequencing, draft engine purity, ESPN transport policy, a large amount of the React IA. Constitution §18 forbids rebuilding those for cleanliness.

**Option 4 means:**

1. New package layout and a **new schema** shaped like §26 (not another migration that adds a fourth snapshot table).
2. Port, with tests, the algorithms in the KEEP rows.
3. Rebuild API, authz, worker, persistence, and provider boundary.
4. Rewire the SPA to one API and to `/me` vs shared routes; do not rewrite every pixel.
5. **Migrate data that cannot be recomputed:** auth users, memberships, published recap editions (and their fact snapshots). ESPN state is refetchable. NBA tables are re-backfillable. Parquet/disk projections are not precious.
6. Do not port the optimizer until a committed fixture makes CI execute it.

This produces the best FCP under a zero-sunk-cost rule because the product quality lives in **(a)** a real private/shared split, **(b)** a reusable intelligence layer, and **(c)** durable history — none of which the current application types can express — while the basketball IP that is already good does not need to be re-derived.

### First vertical slice (so the rebuild does not boil the ocean)

Still architecture, not a schedule:

1. Authz + membership + `fantasy_teams` + no global league fallback  
2. Provider adapter + `refresh_league` **job** + `matchup_periods` finality  
3. Shared reads: standings, matchups, newsroom publish loop (ported facts + editions)  
4. Player ids + projection sets in Postgres + per-user preference  
5. Draft Room on `/me`, authenticated, session persisted, fixture-backed optimizer  

Streaming, trades, FCP model, Yahoo, billing: **not** in the first slice. The architecture leaves a door; it does not walk through it.

---

## Constitution §21 — how the target answers the test

| Question | Answer in the target system |
|---|---|
| Where does external data enter? | `backend/adapters/*` only |
| Canonical player? | `players.id` |
| Canonical league? | `leagues.id` (FCP), not ESPN |
| Canonical fantasy team? | `fantasy_teams.id` |
| Canonical roster? | `roster_observations` / live roster rows for `status=live` |
| Canonical matchup? | `matchups` row |
| Canonical projection? | `projection_rows` + `apply_adjustments` → `ProjectionView` |
| Basketball logic? | `backend/domain/` |
| User-specific logic? | `backend/app` + `/me` + tables keyed by `user_id` |
| Persisted vs calculated? | History and projections persisted; all-play/value calculated from those inputs |
| Current vs historical? | `matchup_periods.status` |
| Belongs to a user vs league? | Table keys; `/me` vs shared routes |
| Access/mutate? | `authorize_league(...)` on every route |
| New feature? | Domain function + app service + shared or `/me` route |

If those answers require archaeology, this design has failed the same test the current repo fails.

---

*End of architecture phase. No code was modified except the addition of this document.*
