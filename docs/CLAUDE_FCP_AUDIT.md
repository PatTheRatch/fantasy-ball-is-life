# Claude FCP Forensic Architecture and Product Audit

**Review date:** 2026-08-21
**Review type:** Read-only architecture and product investigation
**Repository:** `fantasy-ball-is-life` / Full Court Press (FCP)
**Reviewed at commit:** `dd25197` (main)
**Method:** Direct source reading and code-path tracing, git history analysis, migration review, and live execution of both test suites. The knowledge graph was deliberately not used as the primary lens — every structural claim below was traced to source and is cited as `path:line`.

> Companion audits: [`GPT_FCP_AUDIT.md`](GPT_FCP_AUDIT.md), [`CUSOR_FCP_AUDIT.md`](CUSOR_FCP_AUDIT.md).
> A designed, browsable version of this audit exists as a Claude artifact:
> <https://claude.ai/code/artifact/d66c7d19-0537-4e36-b642-37f0b63435b6>

---

## Executive summary

FCP is a web app for serious 9-category head-to-head fantasy basketball managers. The dossier's thesis still holds: *"a GM's cockpit for 9-cat H2H — it closes the loop from data to decision to story."*

The single most useful framing I arrived at: **FCP is three products sharing one process.**

1. **A draft optimizer** — preseason, single-user, compute-heavy, `localStorage` state.
2. **A league newsroom** — in-season, multi-user, publication workflow, Postgres state.
3. **A projections research platform** — offline, global data, benchmark-driven.

They share a player-name join key and an ESPN connection, and almost nothing else. Most of the coupling documented below comes from forcing all three through one FastAPI app, one `config.py`, and one data-access class.

Git history shows five distinct scope expansions in six weeks, each executed as a lettered PR series. **Each stopped at roughly 60%**, and that is the defining structural pattern of the codebase: the multi-league migration converted half the API, the snapshot-worker migration converted half the read paths, the design-system consolidation converted half the components, and the auth rollout covered a quarter of the routes.

Overall shape: **the domain modelling is better than the infrastructure, and the infrastructure is better than the boundaries between subsystems.** There is no framework problem and no fundamental modelling problem. There is a persistence-and-tenancy problem, plus a set of half-completed migrations.

This audit treats the current implementation as evidence of what was built, not as a constraint on what should be built. It proposes no replacement architecture and recommends no rewrite.

### Three findings that matter today

| # | Finding | Severity |
|---|---|---|
| 1 | All on-disk state (projections + M-2 benchmark history) is destroyed on every deploy | Critical — silent data loss |
| 2 | 53 of 71 API routes have no authentication, incl. arbitrary file read/write and unmetered LLM spend | Critical — security |
| 3 | `/confidence` and `/matchup-confidence` return 500 in production; the SQLite file they need cannot exist | Critical — broken headline feature |

---

## 1. Reconstructed product

**Full Court Press (FCP).** The repo name (`fantasy-ball-is-life`) and the seeded league (`patriot-games`) are origin artifacts; the product name in the UI, the Caddyfile, and the FastAPI app title is Full Court Press.

The core loop, per `docs/PROJECT_DOSSIER.md` §02, with current build state:

| Step | Description | State |
|---|---|---|
| **Connect** | Link an ESPN league once; rosters/matchups/transactions pull automatically | Built |
| **Decide** | Auction draft optimizer, category win-probability, projection comparison | Built (win-probability broken in prod — see §13) |
| **Recap** | LLM writes the weekly recap in the league's voice from a server-assembled fact snapshot | Built, complete |
| **Deliver** | Recap posts itself to the group chat on schedule | **Never built** |

Step 4 is described in the dossier as *"the demo that sells this, and the itch that started the whole project."* It is the one part of the loop still fully manual — week-one shipped as a public archive with WhatsApp copy tools, and bot delivery was deferred indefinitely.

### The scope expansion, in order

Reconstructed from 241 commits between 2026-07-08 and 2026-08-21:

| Dates | Series | What it added | Scope shift |
|---|---|---|---|
| Jul 8–12 | D / cleanup | Draft Room: cvxpy auction optimizer, plan portfolio, MC targets, Forge Value | A private tool for one manager |
| Jul 12–16 | F2 / E | Recap newsroom, Supabase persistence, ESPN caching + hardening | League-facing publication |
| Jul 14–15 | P (projections) | Projection-source framework: adapters, on-disk store, badge, picker | Pluggable data sources |
| Jul 16–19 | P (platform) | Auth, IA re-root, slug-scoped routes, per-league credentials, self-hosted deploy | Multi-league SaaS shape |
| Jul 19–26 | N | Landing, invites, self-join, create-league wizard, per-week correctness fixes | Public signup funnel |
| Aug 6–21 | M / W | NBA historical ingest, accuracy scoreboard, backtest harness, playoff planner | Building its own projection model |

The current active workstream is **FCP Projections** (M-series, `docs/specs/FCP_PROJECTIONS.md`). Its spec calls it *"the largest item on the roadmap by an order of magnitude,"* with a hard deadline of usable-for-a-real-draft by ~October, aiming to replace a paid Basketball Monster subscription with an in-house, backtested model.

M-series state: **M-1** (nba_api ingest) landed but the API is IP-blocked; **M-1b** (Kaggle CSV backfill) is the working path — 8,341 season rows, 1,915 bios; **M-2** (accuracy scoreboard) landed; **M-3a** (reader + backtest + naive baseline) landed. **M-3 (the model itself) has not been started.** M-4 through M-7 are spec-only.

### Documentation drift

`README.md` and `docs/PROJECT_DOSSIER.md` both state that `backend/projections/` is *"Reserved for the projection-source framework… empty for now."* That directory now holds eight modules and the entire M-series. The dossier's status section stops at 2026-07-12 — five PR series ago.

---

## 2. Major user workflows

Six workflows are inferable from routes, components, and endpoint wiring.

### A. Draft Room (preseason, single-user)
`/leagues/:slug/draft`. The user configures a pool (budget, roster size, games-per-week, exclusions, favorite team, target players) and receives a portfolio of diverse auction plans. As real picks happen they are recorded; the engine health-checks every plan and selectively re-solves only broken ones. `/draft/triage` and `/draft/relax` handle infeasibility. All draft state — picks, custom plans, presets — lives in `localStorage` under a schema version (`frontend/src/draft/storage.ts`); the backend is deliberately stateless per spec decision D12.

### B. In-season matchup
`/leagues/:slug/matchups/:week`. Current scoreboard from a stored per-week snapshot, plus a live projected scoreboard with a source picker (ESPN Last-15/30, BBM upload, Hashtag paste). A win-probability strip averages per-category confidence. Category margin charts and per-player tables beneath.

### C. Weekly recap newsroom
The publication loop, and the most complete workflow in the app:

1. Admin requests **readiness** — the server assembles a fact snapshot and reports data-quality warnings.
2. Admin **generates** a draft — snapshot persisted (versioned), LLM produces structured JSON, validated against exact-cardinality rules, retried with corrective feedback on failure, stored as a `recap_edition`.
3. Admin **previews** any historical edition, then **publishes** one. A partial unique index guarantees exactly one published edition per week.
4. **Rollback** supersedes it. The public archive renders published editions with no auth.

### D. Onboarding and growth
Landing → signup → the `/` resolver routes by membership count (zero → lobby, one → that league, many → picker). Joining happens two ways: an admin-created single-use invite token redeemed through a security-definer RPC (`redeem_league_invite`), or self-join into any public league. Members then claim their fantasy team name in Settings; a partial unique index enforces one claim per team per league.

### E. Create a league
Two-step wizard. `POST /leagues/preview` validates ESPN credentials read-only and echoes back league name and teams for confirmation. `POST /leagues` then encrypts the cookies, writes the league row, creates an owner membership, and schedules a background refresh.

### F. Internal / research
`/leagues/:slug/accuracy` renders the M-2 projection accuracy scoreboard — projected vs actual team totals per source, per category, per week. The M-3a backtest is CLI-only (`python -m backend.projections.backtest --season 2024`) and prints the naive last-season-repeated baseline the model must beat.

---

## 3. Current architecture map

One VPS, one Supabase project, one static bundle. Everything runs on `fcp.patrickmcdowell.dev` behind Caddy.

```
CLIENT      React 19 SPA (Vite · Tailwind 4 · react-query · react-router 7)
            localStorage — all draft state
                    │
EDGE        Caddy — TLS, /api strip_prefix, static dist from bind mount
                    │
API         FastAPI monolith — 10 routers, 71 routes
            LeagueSlugMiddleware (slug → LeagueContext, ContextVar)
            ESPNRequestCacheMiddleware (per-request ContextVar)
                    │
DOMAIN      league/       data_feed.py (2699L) · MyLeague · scoreboard · cache
            draft/        cvxpy optimizer · engine · strategies · targets_mc · values
            recaps/       assemble · service · store · awards · playoffs
            projections/  adapter · registry · store · accuracy · backtest
            nbadata/      ingest · csv_backfill · reader
            commentary/   prompts · generate (Claude / DeepSeek)
                    │
STORES      Supabase Postgres — 12 tables, RLS, PostgREST         [durable]
            data/projections/*.parquet + manifest.json             [EPHEMERAL]
            data/game_logs.db (SQLite)                             [ABSENT IN PROD]
                    │
EXTERNAL    ESPN Fantasy (espn-api, subclassed)
            Anthropic Claude / DeepSeek
            nba_api (blocked) + Kaggle CSV
            Supabase Auth (GoTrue, JWT)
```

Two things matter more than the boxes:

1. **The browser talks to two backends.** FastAPI for league data; Supabase directly for auth, memberships, invites, and RPCs (`frontend/src/lib/memberships.ts`, `components/InviteAdmin.tsx`, `pages/JoinPage.tsx`).
2. **FastAPI holds the Supabase service-role key**, so every backend read bypasses RLS entirely (`backend/recaps/store.py:48-53`). RLS only governs the direct browser path. There are two authorization systems for one dataset.

---

## 4. Repository structure

293 tracked files.

| Path | Files | Contents |
|---|---|---|
| `frontend/` | 123 | React 19 SPA, ~11.7k lines TS/TSX |
| `backend/` | 65 | FastAPI + domain, ~17.9k lines Python |
| `tests/` | 50 | ~11.4k lines pytest |
| `docs/` | 22 | Dossier, operating manual, 13 feature specs, ESPN audits |
| `supabase/` | 13 | 10 migrations + CLI config |
| root / infra | 20 | Dockerfile, compose, Caddyfile, render.yaml, CI, systemd units |

Backend package grouping (per `docs/specs/BACKEND_RESTRUCTURE.md`, two PRs, July 2026) largely holds. Largest modules:

```
2699  backend/league/data_feed.py        ← god module (§15)
 881  backend/recaps/assemble.py
 798  backend/draft/optimizer.py
 703  backend/api/routers/draft.py       ← business logic in router (§15)
 664  backend/recaps/store.py            ← universal repository (§15)
 653  backend/nbadata/ingest.py
1090  frontend/src/api.ts                ← monolithic API client (§5)
```

---

## 5. Frontend architecture

React 19 + Vite 8 + Tailwind 4 + TypeScript, react-router 7 in data-router mode, TanStack Query for server state. 84 `.tsx` files. The P-series review concluded *"no frontend-framework problem — the problems are shape, not stack,"* and that still reads true.

### Well organised

- **Server state is consistently react-query.** 21 modules use `useQuery`; exactly one page (`Recap.tsx`) still does manual `useEffect` fetching.
- **Route-level code splitting** for the four heavy surfaces via `lazyPages.tsx`.
- **Navigation is data, not markup.** `lib/navigation.ts` builds tabs from the active slug, shared by `TopNav` and `BottomTabBar`, with unit tests.
- **The draft feature is properly decomposed** — board, rail, controls, editors, shared inputs, formatters, storage, types as separate modules.

### Not

- **`api.ts` is a 1,090-line monolith** holding every endpoint function and every response type. The frontend's widest coupling point.
- **Two design systems coexist.** `components/Card.tsx` (used by all of `draft/`) and `ui/Card.tsx` (newer surfaces) are different components with different radii and variants. Same for `ui/Skeleton` vs `season/Skeleton`.
- **Two axios clients** — `client` and `directClient` — exist solely to route recap generation around the Vite dev proxy, which could not hold a ~50s request open. A dev-environment workaround baked into the production client (`api.ts:27-50`).
- **League identity is baked at build time.** `VITE_RECAP_LEAGUE_SLUG=patriot-games` is set in `.github/workflows/deploy.yml` and used as the fallback slug throughout (`lib/supabase.ts:17`). A second league requires a rebuild, not a config change.
- ESLint carries a standing per-file ignore for `AiCommentaryCard.tsx` ("legacy react-hooks debt", `.github/workflows/ci.yml`).
- Two one-line re-export shims left from the P-7 decomposition: `pages/InSeason.tsx`, `pages/Season.tsx`.

---

## 6. Backend architecture

A single FastAPI app (`backend/api/main.py`) with an app-factory-shaped module that is actually a module-level singleton. Ten routers, 71 route declarations.

### Request lifecycle

Middleware registers LIFO, so effective order is CORS → ESPN request cache → slug resolution → handler. `LeagueSlugMiddleware` regex-matches `/leagues/{slug}/…`, resolves the league row from Postgres, decrypts the ESPN cookies via a pgcrypto RPC, and pushes a frozen `LeagueContext` onto a ContextVar, resetting it in a `finally`.

Raw ASGI middleware was chosen specifically because `BaseHTTPMiddleware` spawns a child task that breaks ContextVar propagation. The docstring explains this and it is correct (`backend/api/middleware_slug.py:1-20`).

### The API is split down the middle

This is the defining structural fact of the backend.

| Router | Routes | League-scoped? | Auth |
|---|---|---|---|
| `league` | 21 | Yes — `/leagues/{slug}` | **None** |
| `recaps` | 11 | Yes — `/leagues/{slug}/recaps` | JWT + per-league admin |
| `legacy_redirects` | 17 | 307 → default slug | **None** |
| `draft` | 7 | **No** — flat, global | **None** |
| `projections` | 6 | **No** — flat, global | **None** |
| `commentary` | 3 | **No** — flat, global | **None** |
| `optimizer` | 2 | **No** — flat, global | **None** |
| `admin` | 2 | Slug param | Shared secret header |
| `create` + `create_league` | 2 | N/A | JWT (any signed-in user) |

The multi-league migration (P-4/P-4b) converted the *league data* half and stopped. Draft, optimizer, projections, and commentary — 18 routes — never moved. They fall back to `_resolve_ctx()` (`backend/api/deps.py:29-45`), which resolves *"the first league row in the database"* when no slug is present. With more than one league in the table, those endpoints silently operate on an arbitrary one.

### Caching is layered four deep

All process-local, all invisible to a second container:

- Per-request `ESPNRequestCache` (ContextVar) — dedupes `League` construction within one request.
- Cross-request 90s TTL cache for `MyLeague`, with a per-key `threading.Lock` for single-flight.
- Cross-request 90s TTL cache for `WeeklyScoreboard` (narrow one-call fetch).
- A 60s LRU snapshot cache inside recap assembly, plus `lru_cache` on league-UUID resolution (`deps.py:130`).

These exist because production measured `MyLeague` construction at **140–171 seconds** (`backend/league/cache.py:20-33`). The caches are well-written and correctly reasoned; they are also compensating for an architecture that does third-party fetch plus heavy compute inside a page load. `docs/specs/PRODUCT_PLATFORM_OVERHAUL.md` §0 says exactly that: *"a consumer product cannot do third-party fetch + heavy compute inside a page load."* The snapshot worker was the fix, and it is only half-applied.

---

## 7. Database and data model

Supabase Postgres, 10 migrations, 12 tables, RLS on all of them. Access is PostgREST-only — there is no direct Postgres connection anywhere in the codebase.

| Table | Grain | Purpose |
|---|---|---|
| `profiles` | user | Display name, auto-created by trigger on `auth.users` |
| `leagues` | league | Identity, branding, visibility, recap voice, encrypted ESPN creds |
| `league_memberships` | league × user | Role (owner/admin/member) + claimed `team_name` |
| `league_invites` | token | Single-use join tokens with optional expiry |
| `league_week_snapshots` | league × season × week × **version** | Recap fact snapshot — 7 typed jsonb columns |
| `recap_editions` | league × season × week × **version** | Generated recap; draft / published / superseded |
| `power_ranking_editions` | league × season × week | Cached LLM blurbs, deliberately unversioned |
| `league_state_snapshots` | league × season × **phase** | Rolling *latest* state — upserted by the worker |
| `league_week_scoreboards` | league × season × week | Immutable per-week matchup results |
| `league_week_transactions` | league × season × week | Immutable per-week adds/drops/trades |
| `nba_player_bio` | person | Global — DOB, measurements, draft info (1,915 rows) |
| `nba_player_seasons` | person × season | Global — 8,341 rows, per-game averages + attempts |

### Three snapshot systems, built in three phases

The clearest structural scar in the schema. `league_state_snapshots` was designed as rolling-latest, one row per phase. That worked for "show me now" and broke every historical view: a past week's matchup page rendered the current scoreboard, and season-cumulative transaction counts only ever saw one week — the migration comment says trades *"were effectively invisible all season."*

The fix was two new tables with an **identical** shape (`league_id, season, week, payload_json, fetched_at`) and byte-identical RLS. Meanwhile `league_week_snapshots`, from the earlier recap phase, stores the same underlying facts again in typed columns with versioning.

The recap assembly path now reconciles all three at read time with layered try/except degradation — prefer the immutable per-week scoreboard, fall back to rolling-latest, recompute standings from week scoreboards if available, fall back to stored standings otherwise (`backend/recaps/assemble.py:418-500`). It works. It is compensation, not design.

### Not in Postgres

- **Projections** — parquet files plus a `manifest.json` in `data/projections/`, with a single **global** `active` map of horizon → set_id. Not league-scoped (a `league_slug` field exists on the set as metadata only).
- **Player consistency tiers** — a SQLite file at `data/game_logs.db`.

### Schema details worth noting

- `leagues.espn_league_id` is `text`; the backend casts with `int()`. A migration comment explicitly documents this and says do not change it.
- The Patriot Games league row is `INSERT`ed by the first migration with a hardcoded UUID and real ESPN league id.
- The team-claim privilege model is genuinely elegant: RLS scopes the *row* to your own membership, and a column-level grant (`grant update (team_name)`) scopes the *column* — so a member cannot self-promote their role through the update policy. The migration states it crisply: *"RLS scopes rows, grants scope columns."*
- `leagues.timezone` is stored, loaded into `LeagueContext`, and **never read**. Date arithmetic uses a module constant `LONDON_TZ = pytz.timezone("Europe/London")` (`data_feed.py:80,176`).
- `league_state_snapshots` RLS covers public leagues only — no member path. A private league's snapshots appear unreadable to its own members through the direct Supabase path.

---

## 8. Fantasy basketball domain logic

Expressed in four places, at four levels of quality.

### 1. Category semantics — good
The nine categories are a tuple in `ProjectionConfig`; the inverted category is a single set, `LOWER_IS_BETTER_STATS = {"TO"}`; and one function, `category_result()`, decides W/L/T for any category. The convention is documented and consistently applied: turnovers are stored as natural positive counts everywhere and direction is applied only at comparison time. This was a bug once (reversed recap turnover winners, PR #25) and the fix was to centralise it. Correct shape. (`data_feed.py:128-152`)

### 2. All-play / universe wins — good
`WeeklyScoreboard` owns a vectorized every-team-vs-every-team computation. `MyLeague.get_universe_wins()` is a thin wrapper. Bye and eliminated teams are excluded rather than zero-filled — a real playoff bug (14 rankings for 11 active teams, each ghost getting 11 turnover wins) found live and fixed properly, with a dedicated test file. (`backend/league/scoreboard.py`, `tests/test_allplay_playoff_participants.py`)

### 3. The canonical projection schema — good
`PlayerProjection` is the framework's best idea. One dataclass; every source becomes rows of it; every consumer reads only its fields. Crucially it stores **makes and attempts**, not just percentages, so FG%/FT% can be derived with correct attempt weighting. The FCP model plugs in as "just another adapter" with zero consumer changes — the spec calls this *"the architectural cheat code,"* and the design genuinely delivers it. (`backend/projections/adapter.py:23-64`)

### 4. Player identity — the weak point

Everything joins on a normalized player name. There is no stable player id shared across ESPN, BBM, Hashtag, and nba_api. And the normalization is not single-sourced.

**Four fuzzy-match paths, four thresholds, two normalizers.** `normalize_name()` at module scope strips accents, lowercases, and removes periods and apostrophes. A *second* `normalize_name()` is defined inside `add_bbm_projections()` and shadows it — it strips every non-alphabetic character, so it also removes hyphens and digits. Two functions with the same name produce different keys for names like `Shai Gilgeous-Alexander` or `Jaren Jackson Jr.`

On top of that, four separate attachment functions each pick their own fuzzy cutoff:

| Function | Cutoff | Line |
|---|---|---|
| `add_bbm_projections` | 80 | `data_feed.py:385` |
| `add_projections` | 75 | `data_feed.py:833` |
| `attach_projections` | 85 | `data_feed.py:980` |
| `fuzzy_map_names` (default) | 90 | `data_feed.py:194` |

Player identity is the join key for the entire domain — projections, rosters, transactions, the optimizer pool, and the NBA historical tables all hinge on it. **A mismatch does not error; it silently drops a player** from a projection set or an optimizer pool.

`nbadata/ingest.py` and `nbadata/csv_backfill.py` both import the module-level `normalize_name` from `data_feed`, which means the NBA-global data layer takes a dependency on the ESPN league data layer purely to get a string function.

---

## 9. How projections, rankings, player data, league data, and calculated data flow

Four distinct pipelines, with different freshness models and different storage.

| Flow | Path | Storage | Freshness |
|---|---|---|---|
| League state | systemd timer → `/admin/refresh-all` → `refresh_league` → ESPN → `_upsert_phase` | Postgres | 15 min |
| League reads | SPA → FastAPI → `_snapshot_read(phase)` → Postgres | — | Snapshot age |
| Live reads | SPA → FastAPI → `_handles()` → espn-api → ESPN | Caches only | Real-time, slow |
| Projections | Upload or ESPN adapter → `ProjectionStore.save_set` → parquet | Container disk | Manual / weekly |
| NBA history | `nbadata/ingest` or `csv_backfill` → `upsert_nba_player_*` | Postgres | One-time backfill |
| Recap | `assemble_weekly_snapshot` → snapshot row → LLM → edition row → publish | Postgres | On demand |

**The read path is not consistent.** Within the same router, `/power-rankings`, `/standings`, and `/season-stats` read stored snapshots, while `/meta`, `/schedule`, `/matchups/current-week`, `/playoff-schedule`, and both confidence endpoints construct a live ESPN connection inside the request. A caller cannot tell from the URL which kind they are getting, and the slow ones are the ones that can take minutes.

**The worker bypasses its own read layer to avoid a cycle.** A comment in `refresh.py:330-336` explains it directly: the `league_api` functions were *"flipped in P-3b to read from stored snapshots,"* so the worker that *populates* those snapshots must call `data_feed` directly *"to avoid a circular read-from-empty cycle."* A real design smell, honestly documented.

### Projection precedence

- **Week horizon:** explicit per-request override → active store set (honored only if its `week` matches the caller's current matchup week) → live ESPN via a virtual sentinel set id. Stale sets from prior weeks fall through automatically. This week-scoping rule is genuinely good design.
- **Season horizon:** active store set → legacy on-disk `BBM_Projections.xls` → empty. The legacy file fallback is not.

(`backend/projections/registry.py`)

---

## 10. Authentication and account architecture

Supabase Auth (GoTrue) with email/password. The SPA holds the session via `AuthProvider` and `onAuthStateChange`. The backend verifies a bearer token by calling `GET /auth/v1/user` on Supabase (`backend/recaps/auth.py:30-45`) — a network round trip per protected request, rather than local JWT signature verification.

Authorization exists in two disconnected systems:

- **Postgres RLS** governs the browser's direct Supabase calls — memberships, invites, profiles, published editions. The policies are careful and there is a dedicated 16-test RLS boundary suite run against an ephemeral local Supabase in CI.
- **Application code** governs FastAPI. But FastAPI uses the service-role key, so RLS never applies. Only `backend/recaps/service.py` implements a real check — `require_admin()` → `is_league_admin()` → 403.

### CRITICAL: 53 of 71 API routes have no authentication at all

Only the 11 recap admin routes (JWT + per-league admin), 2 league-creation routes (JWT, any signed-in user), and 2 admin refresh routes (shared secret) are protected. Every league data route, every draft route, the optimizer, projections, and commentary are open to anonymous callers.

**There is no membership check anywhere on the read path** — knowing a slug is sufficient to read a private league's standings, rosters, and transactions.

### CRITICAL: three unauthenticated endpoints with real blast radius

1. **`POST /projections`** accepts a `path` form field and calls `pd.read_excel(path)` on it — an arbitrary server-side file read, no auth. (`projections.py:62-64`)
2. **`PUT`/`DELETE /projections/active`** let any anonymous caller change the platform-wide active projection set, which the draft optimizer and every projected scoreboard then consume.
3. **`POST /optimizer/multiple-plans`** takes a caller-controlled `out_prefix` that flows unsanitized into `f"{out_prefix}{label}.csv"` and `to_csv()` — an arbitrary file write. `docs/ESPN_INTEGRATION_AUDIT.md` flagged this in July as *"Deferred; revisit before any multi-user or external exposure."* Multi-user exposure has since shipped. (`optimizer.py:144,170` → `optimizer.py:723,748`)
4. **The three commentary endpoints** invoke Claude with request-body content and no auth or rate limit — unbounded spend on the owner's API key. (`commentary.py:66-84`)

### Credential decryption sends the key to Postgres on every resolution

ESPN cookies are encrypted at rest with pgcrypto. To decrypt, the backend POSTs to an RPC with `{"data": …, "pwd": CRED_ENCRYPTION_KEY}`. The migration comment claims this happens *"without the key ever touching the database in plaintext… passed as a parameter"* — which contradicts itself. Passing it as a parameter *is* sending it, over the wire, into a place where it can surface in query logs. It also costs two extra HTTP round trips per league resolution, on every slug-scoped request. (`20260717230000_league_credentials.sql`, `credentials.py:78-96`)

---

## 11. External data sources and integrations

| Source | Access | Status |
|---|---|---|
| ESPN Fantasy | `espn-api` library, two `League` subclasses, cookie auth (SWID + espn_s2) | Primary; hardened with a timeout gateway |
| Basketball Monster | Paid `.xls` export, manual upload | Current projection benchmark |
| Hashtag Basketball | File upload or paste-in | Adapter shipped |
| ESPN rolling averages | Last-15 / Last-30 splits via `EspnAdapter` | Week horizon only, by design |
| nba_api | Unofficial NBA.com client | **IP-blocked** — hardened with browser headers + 90s timeout |
| Kaggle CSV dataset | `csv_backfill.py` | The working path — 8,341 seasons, 1,915 bios |
| Anthropic Claude | `claude-sonnet-5`, effort-bounded to `low` | Default recap provider |
| DeepSeek | OpenAI-compatible, `json_object` mode | Cheaper alternative; downgraded from default |

### The ESPN coupling is structural, not incidental

`MyLeague` (`backend/league/fantasy.py:14`) and `ScoreboardLeague` (`backend/league/scoreboard_fetch.py:30`) both **subclass** `espn_api.basketball.League` and override its private loaders — `_fetch_players`, `_fetch_draft`, `_get_all_pro_schedule`, and in one case call `_fetch_league` / `_fetch_teams` by hand.

The optimisation is smart (one ESPN request instead of four, saving ~740 KB) and the reasoning is documented. But it means **the domain model *is* the ESPN client**, and the app depends on the internal implementation of a third-party library that could change in any release. Adding Yahoo or Sleeper — on the dossier's "Bench" list — is not an adapter change; it is a rewrite of the domain layer.

### The gateway is a highlight

`backend/league/gateway.py` patches espn-api's timeout-less `requests.get` by rebinding the `requests` *name inside espn-api's own module namespace* rather than mutating the shared module — so the Supabase auth call, which has its own timeout and error handling, is unaffected. Transport failures become typed exceptions mapped to 504/502/500. Careful, well-documented, tested.

---

## 12. Background jobs and ingestion

One job, one schedule. A systemd timer (`OnCalendar=*:0/15`, `Persistent=true`) runs curl against `POST /api/admin/refresh-all` with the worker secret. **No queue, no scheduler library, no retry beyond the timer's next tick.**

`refresh_all_leagues()` loops every league slug sequentially; `refresh_league()` runs nine phases sequentially, each wrapped in its own try/except returning `"ok"` or `"error: …"`. **The failure isolation is genuinely good** — one phase failing never blocks the rest, one league failing never blocks the others, and the response is a readable per-phase map.

Three structural limits:

- **It is one synchronous HTTP request.** The cron entrypoint uses a 900-second timeout. Refresh time scales linearly with league count against an ESPN connection observed taking 140s+ per league construction. This does not survive double-digit leagues.
- **The `PHASES` constant is stale.** It lists six phases (`refresh.py:24`); the function actually runs nine (adding `projection_snapshot` and two backfills). Nothing reads the constant.
- **The `projection_snapshot` phase writes to ephemeral disk** — see §13.

The NBA ingest is a separate, manually-run backfill. Both `ingest.py` and `csv_backfill.py` are idempotent upserts with unmatched-name reporting rather than silent drops, per the spec's requirement.

---

## 13. Deployment and infrastructure

Production is a single VPS running Docker Compose: one `backend` container (uvicorn, non-root, healthchecked, multi-stage build) and one `caddy` container terminating TLS, reverse-proxying `/api/*` with `strip_prefix`, and serving the static SPA from a bind mount. Supabase is a hosted cloud project (`wuzoengojiqotusulwhj`).

CI/CD is two GitHub workflows. `deploy.yml` is the more complete one: RLS tests against an ephemeral local Supabase → backend tests → **migrations pushed to the production database** → frontend build with baked env → sanity-grep the bundle for the right API base → scp the dist → ssh, `git reset --hard`, `docker compose up -d --build --force-recreate`. Gating the deploy on migrations succeeding is a good call.

### CRITICAL: all on-disk state is destroyed on every deploy

The Dockerfile copies only `backend/` (`Dockerfile:20`). `docker-compose.yml` declares volumes for Caddy but **none for the backend container**. Deploy runs `--force-recreate`.

So `data/projections/` — every uploaded BBM and Hashtag set, every weekly ESPN benchmark snapshot the worker writes, and the `manifest.json` recording which set is active — lives in the container's writable layer and is wiped on every push to main.

**This directly defeats M-2.** The accuracy scoreboard's stated purpose is a benchmark you *"build early and keep forever,"* and it reads its history from that store. The weekly ESPN snapshots exist precisely because *"nothing records what ESPN projected at the time, so past weeks can never be scored"* (`refresh.py:247-256`) — and then they are deleted at the next deploy.

### CRITICAL: two endpoints depend on a SQLite file that cannot exist in production

`/confidence` and `/matchup-confidence` call `get_confidence(db_path="data/game_logs.db")` (`league.py:104,205`). That file is gitignored, absent from the repo, absent from the Docker image, and **nothing anywhere in the repository creates it** — `consistency.py` has a CLI that reads from it and writes derived tables, but no ingest populates it.

I confirmed the failure mode directly: with the file missing, `get_confidence` raises `no such table: game_logs`. Both endpoints wrap everything in `except Exception → HTTPException(500)`, so they return 500 rather than degrading. The frontend calls both and renders `confidence_pct` in `WinProbabilityStrip` — the "live category win-probability" feature that is slot #4 of the dossier's Starting Five.

### `render.yaml` is a dead deployment target still shaping live code

The repo carries a full Render blueprint — web service, cron, static site — from before the July 19 move to self-hosting. It still lists `ESPN_LEAGUE_ID`/`ESPN_SWID`/`ESPN_S2` env vars that `config.py` explicitly says no longer exist. More importantly, `backend/worker/cron_entrypoint.py:14` — the code path the blueprint invokes — still reads `RENDER_EXTERNAL_URL`, while production actually calls the endpoint from a systemd unit.

### Scaling note

Process-local caches plus on-disk projection state mean the backend **cannot be scaled past one container** without behaviour changes. Also, both CI workflows run the full pytest suite, so every PR runs the backend tests twice.

---

## 14. Testing strategy

50 backend test files (~11.4k lines) and 15 frontend test files (62 tests). Both suites were executed for this audit.

| Suite | Result | Notes |
|---|---|---|
| Backend (pytest) | 553 pass · 36 skip · **2 fail** | Both failures pre-existing |
| Frontend (vitest) | 62 pass | Navigation, routing, auth surfaces, a few pages |
| RLS boundary | 16 skip locally | Run only in `deploy.yml` against ephemeral Supabase |

### What is strong

`tests/conftest.py` is the best piece of test infrastructure here. An autouse fixture **scrubs deployment secrets from the environment before every test** — so a local run matches a clean CI environment and "passes locally, fails in CI" from a leaked env var is structurally impossible. A second autouse fixture pushes a stub `LeagueContext` so nothing touches Supabase. Both are well-reasoned and documented.

Bugs found in production have consistently come back with named regression tests — `test_scoreboard_turnovers`, `test_allplay_playoff_participants`, `test_roster_week_window`, `test_espn_gateway`. A healthy habit.

### The flagship feature is effectively untested in CI

**Twenty tests skip with *"projections file not present"*** — all 11 draft API integration tests, 3 plan-diversity tests, 2 pool-feasibility tests, and 4 value-source tests. They need `player_rankings/BBM_Projections.xls`, which is gitignored and cannot be committed. So the cvxpy optimizer, the plan portfolio engine, and the auction value model — the most complex and highest-value code in the repo — are never exercised by CI.

The CI comment frames this as expected: *"Seeing skips here is expected, not a gap in the gate."* That framing is doing a lot of work. A synthetic fixture projection set would close it.

### Two tests failing on main

- `test_nbadata_ingest.py::TestRateLimiting::test_sleep_called_between_api_calls` — fails outright; confirmed to fail independently of any working-tree change.
- `test_recaps.py::test_generate_endpoint_rejects_anonymous_before_store_or_anthropic` — fails in a full-suite run but **passes in isolation**, making it a test-ordering leak around `CRED_ENCRYPTION_KEY` rather than a product bug.

Notably, `ci.yml` would fail on the first of these — **the gate is currently red on main.**

Frontend coverage is thin relative to surface area: 15 test files against 84 components, concentrated on routing and auth rather than the data-heavy tabs.

### Separately: a blocking bug found and fixed during this session

`backend/projections/backtest.py` placed `if __name__ == "__main__": main()` *above* the `# ── helpers` section, so `main()` executed at import time before `_safe_pct` and `_weighted_mae` were bound. The documented M-3a command (`python -m backend.projections.backtest --season 2024`) raised `NameError` and could never have worked as committed. Fixed by moving the entrypoint to the end of the file (4-line move, no logic change). No test covered the module's CLI entrypoint.

---

## 15. Where responsibilities are cleanly separated

These boundaries are real and would survive a rebuild.

- **The projection adapter boundary.** `PlayerProjection` + the `ProjectionAdapter` protocol + the registry's precedence function. Four sources plug in; consumers never see source-specific columns. The cleanest abstraction in the codebase.
- **The ESPN gateway.** Transport policy — timeouts, typed errors, status mapping — fully isolated from callers, with a scoped monkeypatch that does not leak to other libraries.
- **`WeeklyScoreboard`.** All-play math extracted into a pure, vectorized class with injectable data. `MyLeague` is a thin wrapper. Tests inject tables directly.
- **The draft engine.** `engine.py` is explicitly pure — no cvxpy, no pandas, no ESPN. The solver is injected as `solve_fn`, so the health-check and selective-resolve logic is unit-testable offline.
- **Recap service vs store vs router.** `recaps/` is the one subsystem with a proper three-layer split: router does HTTP and validation, service does authorization and orchestration, store does persistence. It is also the only subsystem with real authorization.
- **Publish atomicity in the database.** `publish_recap_edition` is a security-definer function doing `SELECT … FOR UPDATE`, admin check, supersede, publish — backed by a partial unique index. Correctness enforced where it cannot be bypassed.
- **Frontend navigation and state utilities.** `navigation.ts`, `useLeagueSlug`, `stateUtils`, `seasonUtils` — small, pure, tested.
- **The playoff schedule planner.** Pure functions in `league/playoff_schedule.py`, wiring in the router, honest empty-state reasons instead of errors.

---

## 16. Where responsibilities are coupled or unclear

### `data_feed.py` is a 2,699-line god module

It contains, in one file: the ESPN client wrapper, name normalization and fuzzy matching, four projection-attachment functions, transaction parsing and trade reconstruction, scoreboard building, projected-scoreboard math, storyline metrics, **LLM prompt construction** (`make_prompt`, ~120 lines), Excel readers, a hardcoded season calendar, and a CLI `run()` that writes fifteen CSV files to the working directory.

Nearly everything imports it. `nbadata` imports it for a string function. `fantasy.py`, `cache.py`, `scoreboard_fetch.py`, and every router depend on it. It is the reason the layering cannot be cleanly stated.

### `RecapStore` is the universal repository, misnamed

32 methods spanning six unrelated aggregates: leagues, admin checks, recap snapshots and editions, power-ranking blurbs, per-week scoreboards, per-week transactions, and the global NBA tables. `credentials.py` imports it to read leagues; `nbadata/reader.py` imports it to read player seasons. Its name describes maybe a third of what it does.

It also builds every request with bare `requests.request(...)` rather than a `Session`, so **there is no connection pooling** — every database read pays a fresh TCP and TLS handshake.

### Business logic living in routers

`/matchup-confidence` is ~120 lines of domain math inline in the router — roster filtering, per-team game-count aggregation, scaling team totals to per-player-game, percentage special-casing (`league.py:110-230`). `draft.py` is 703 lines and holds `_build_pool_context`, the real `solve_fn`, target resolution, and the value board (`draft.py:185-330`). The pure engine was carefully extracted; the impure orchestration that feeds it stayed in the HTTP layer.

### Single-tenant judgment calls as process-global config

`config.py:71-99` holds one league owner's personal decisions as module-level globals:

- `DO_NOT_DRAFT` — a named list: `"kyrie irving,deandre ayton,kristaps porzingis,jimmy butler,jason tatum"` (which also contains a misspelling of Jayson Tatum)
- `POSITION_OVERRIDES = {"Anthony Davis": "C"}`
- `GAMES_PER_WEEK`, `MIN_SEASON_GAMES_FILTER`, `DRAFT_LEAGUE_YEAR_DEFAULT = 2025`

The comment above them says these *"are league-owner judgment calls, not engine logic, so they live in config: a different league… should be able to change them without touching engine code."* But an env var is process-wide, so every league on the deployment shares one owner's do-not-draft list. **The intent is right; the mechanism does not deliver it.**

### Two write paths, two authorization models, one dataset

Memberships and invites are written by the browser directly to Supabase under RLS. Leagues and memberships are also written by FastAPI under the service-role key with application-level checks. **There is no single place that answers "may this user do this to this league."**

---

## 17. Where duplication exists

### The season week calendar is hand-maintained in two languages

`_MATCHUP_WEEK_CALENDARS[2026]` in `data_feed.py:89-120` and `MATCHUP_WEEKS_2025_26` in `frontend/src/lib/matchupWeeks.ts` are the same 22 hand-typed start/end date pairs, including the same extended All-Star break week. The TS file's own comment admits it: *"Mirrors `data_feed.MATCHUP_WEEKS_2025_26`."*

The dossier's Cut List says explicitly: do not carry forward *"hardcoded season logic (hand-typed week calendar and current-week number — derive from ESPN)."* It was carried forward, then duplicated. The backend version at least got season keying (P-10); the frontend version did not, and `/matchup-confidence` still reads the deprecated unkeyed alias (`league.py:135`), so it uses the 2026 calendar regardless of which season the league is in.

### Three near-identical per-week snapshot tables

`league_week_scoreboards` and `league_week_transactions` have identical columns and byte-identical RLS policies, differing only in name. `league_state_snapshots` has the same shape with `phase` instead of `week`. A single `league_snapshots(league_id, season, week, kind, payload_json)` would cover all three.

### Projection attachment implemented four times

`add_bbm_projections`, `add_projections`, `attach_projections`, and `attach_projections_to_movesets` all do "normalize names, exact merge, fuzzy the remainder, merge again" with different thresholds and column conventions. And `EspnAdapter`'s docstring states its math *"is a straight port of the existing implementation at `data_feed.py:get_current_rosters()`"* — a fifth copy, acknowledged in writing.

### Smaller duplications

- Two `Card` components and two `Skeleton` components in the frontend.
- Two `League` subclasses overriding overlapping private loaders.
- Two routers with the same `/leagues` prefix (`create.py`, `create_league.py`) split only because they were separate PRs (N-4a, N-4b).
- Both CI workflows running the full pytest suite.
- Two one-line re-export shims left from the P-7 decomposition.

---

## 18. Where technical debt has accumulated

Ranked by what would actually hurt.

1. **Ephemeral projection storage.** Silently destroys the M-2 benchmark history and every upload on each deploy. Highest severity because it invalidates the current workstream's evidence base without any error surfacing.
2. **The unauthenticated API surface.** 53 open routes including arbitrary file read, arbitrary file write, unbounded LLM spend, and global projection-state mutation — on a product that has shipped public signup and self-join.
3. **Player identity fragmentation.** Two normalizers, four thresholds, no stable id. Failures are silent drops, not errors.
4. **`data_feed.py` and `RecapStore` as god modules.** Every change touches them; every layering statement has an exception because of them.
5. **The half-migrated multi-league boundary.** 18 routes still resolve "the first league in the table."
6. **Dead confidence feature.** Two endpoints guaranteed to 500 in production, feeding a headline feature.
7. **Hardcoded season calendars**, duplicated, flagged as a cut-list item at project start.
8. **Optimizer untested in CI** — 20 skipped tests on the most complex code.
9. **Stale documentation.** README says `backend/projections/` is "empty for now"; it holds eight modules and the entire M-series. The dossier's status stops five PR series ago.
10. **Small residue** — a red test on main, `render.yaml`, the stale `PHASES` constant, an unused `timezone` column against a hardcoded London timezone, an ESLint per-file ignore, and (until this session) a broken entrypoint ordering in `backtest.py` that made the documented M-3a command unrunnable.

---

## 19. Decisions that are historical artifacts of expanding scope

| Artifact | Made sense when | Now |
|---|---|---|
| Domain model subclasses the ESPN client | One league, one platform, ship fast | Blocks Yahoo/Sleeper entirely; couples to a library's privates |
| Projections on local disk with a global active pointer | Single user uploading their own BBM file | Not league-scoped, not durable, not multi-container |
| Rolling-latest snapshot table | "Show me the current week fast" | Two extra tables and layered read-time fallbacks to fix history |
| Flat, unscoped draft/optimizer/projections routes | Before slugs existed | Half the API is multi-tenant, half is not |
| Auth only on recap admin | Only publishing needed protection | Public signup shipped; read paths never caught up |
| Hand-typed week calendar | One season, one league | Duplicated in TS; on the cut list and still growing |
| Personal draft config as env globals | Owner's private optimizer | One owner's do-not-draft list applies platform-wide |
| Draft state in `localStorage` | Stateless-backend decision D12 | Device-bound; no recovery mid-draft |
| `RecapStore` as the DB client | Recaps were the only persisted thing | Six aggregates, including global NBA data |
| `render.yaml` | Render was the target | Dead, but its env contract still shapes worker code |
| Build-time `VITE_RECAP_LEAGUE_SLUG` | Single-league frontend | A second league needs a rebuild |

### A process artifact worth naming

Development ran as spec-driven, lettered PR series executed largely by AI agents (`aisha-agent` 78 commits, `Claude` 47, humans the rest), governed by `docs/AISHA_OPERATING_MANUAL.md`. It produced unusually good documentation — most non-obvious decisions carry a comment explaining the reasoning, and most bugs have a named regression test.

It also produced two costs:

1. **The series letters collide.** `P-2` and `P-6` mean different things in different files — in `projections/store.py` they refer to the projection framework, in `api.ts` and `memberships.ts` to the Product Platform Overhaul. A reader cannot resolve a P-reference without knowing which July week the file was written in.
2. **Code is organised by the PR that created it** rather than by domain — which is why two routers share a `/leagues` prefix and why comments read as a changelog of superseded decisions.

---

## 20. What is genuinely well designed

- **The canonical projection schema and adapter framework.** One dataclass, a protocol, a precedence function, week-scoped invalidation, and a virtual-set sentinel for live sources. Storing makes and attempts rather than percentages is exactly right and shows real domain understanding. Worth preserving verbatim.
- **The recap publication model.** Immutable versioned fact snapshots, separately versioned editions referencing them, a partial unique index guaranteeing one published edition per week, and an atomic security-definer publish function that checks admin rights inside the transaction. Separating *facts* from *generated prose* means a recap can be regenerated without re-fetching, and the facts are auditable.
- **The ESPN gateway.** Namespace-scoped monkeypatching so the patch cannot leak to other `requests` callers, typed transport errors, clean status mapping. Well-reasoned, documented, tested.
- **Worker failure isolation.** Per-phase and per-league try/except returning a structured results map. The right instinct for a system whose upstream is an unofficial, flaky API.
- **The team-claim privilege model.** RLS scopes the row; a column-level grant scopes the writable column. A member cannot self-promote their role through the update policy.
- **Secret-scrubbing test fixture.** Autouse fixture removing deployment secrets before every test, making local runs structurally identical to clean CI. Genuinely sophisticated test hygiene.
- **The benchmark-first sequencing of the projections model.** Building the accuracy scoreboard (M-2) and the backtest harness with a naive baseline (M-3a) *before* the model (M-3) is the correct order, and rare. The merge gate is stated as measurable: beat last-season-repeated on MAE. This is how you avoid shipping a model that feels better and isn't.
- **Honest empty states.** A recurring, deliberate principle: the playoff planner returns a `reason` instead of an error when the schedule isn't out; the accuracy scoreboard reports `unscoreable` weeks rather than guessing; the reader returns a correctly-shaped empty DataFrame when the table is empty; the draft engine skips an invalid target and reports it rather than crashing the solve ("never freeze on a bad input"). A real product value expressed consistently in code.

---

## Summary: most important strengths

- **The analytics IP is real and hard-won** — auction optimization under category constraints, Monte Carlo targets, all-play math, playoff-aware ranking. Months of basketball logic that would have to be re-derived.
- **The projection abstraction is correct** and already proven across four sources.
- **The recap workflow is complete and correct**, with database-enforced invariants.
- **The stack is current and appropriate.** React 19 / Vite / Tailwind 4 / FastAPI / Postgres needs no replacement.
- **Reasoning is preserved.** Non-obvious decisions carry comments explaining why, making the codebase unusually legible for its age.
- **Failure handling is a genuine cultural strength** — isolation, degradation, honest empty states.
- **Measurement discipline** on the projections work.

## Summary: most important weaknesses

- **Durability of critical state.** Projections and benchmark history live on a disk wiped every deploy. Silent, and it undermines the current workstream.
- **Authorization is absent from most of the API**, on a product that now has public signup.
- **The multi-league migration is half-finished**, leaving an API where scoping depends on which July week the route was written.
- **The domain layer is the ESPN client**, which caps the product at one platform.
- **Player identity has no stable key** and inconsistent matching.
- **Two god modules** absorb changes and defeat the otherwise-decent package structure.
- **The most valuable code has the least CI coverage.**
- **A headline feature is silently broken** in production.

---

## Areas requiring deeper investigation

- **Production reality check.** Does `data/projections/` currently contain anything on the live VPS? How many weekly ESPN benchmark snapshots have ever survived to be scored by M-2? This determines whether the accuracy scoreboard has ever produced a real number.
- **The 140–171s `MyLeague` construction.** Attributed in a comment to "a Render-specific network/throttling issue," but the app has since left Render. Is it still slow on the VPS? Which endpoints still pay it?
- **The optimizer itself.** 798 lines of cvxpy read structurally but not verified numerically — constraint formulation, the `value_source` and Forge Value pricing model, and how the 8-second solver cap interacts with feasibility. It is the flagship and it has no CI coverage.
- **Structured recap reliability.** The generation path does JSON repair plus a corrective-feedback retry rather than using native structured-output or tool-use APIs. What is the actual failure rate, and how often does the repair path alter meaning?
- **Name-match yield.** How many players actually fail to match between ESPN rosters, BBM exports, and the 1,915 NBA bios? The unmatched report exists — its contents are the real measure of the identity problem.
- **Kaggle CSV provenance and licensing.** The backfill's data source, its update cadence, and whether it can be used commercially. The FCP spec flags licensing as an open risk.
- **Whether the app currently works end to end.** The season calendar runs to 2026-03-29; today is August. Several paths depend on `currentMatchupPeriod` and hardcoded windows, so offseason behaviour is unverified.
- **The `league_state_snapshots` RLS gap.** Its read policy covers public leagues only — no member path. A private league's snapshots appear unreadable to its own members through the direct Supabase path.
- **Supabase cost and query shape.** No connection pooling, per-request auth round trips, and full-table paginated reads of 8,341 NBA rows into pandas on each backtest.

---

## Product questions the repository cannot answer

1. **Is this a product or a personal tool?** The dossier says "Patrick's league first; wider launch if it earns it," and the code is split exactly on that ambiguity — public signup and invites shipped, but personal draft preferences are still process-global config. Which one is true now decides most of the architecture.
2. **How many leagues are actually in production today?** Everything from the fallback slug to the single-league `_resolve_ctx()` path to the build-time `VITE_RECAP_LEAGUE_SLUG` behaves differently at one league versus many.
3. **Is the draft optimizer meant to stay a competitive edge, or become a shipped feature?** Decision D says Patrick drafts with it privately first. If it stays private, its untested, unauthenticated, unscoped state is tolerable. If it ships, none of that is.
4. **Does FCP Projections replace Basketball Monster, or compete with it publicly?** The spec leaves "publish publicly or keep as the engine only" explicitly open, and the answer changes the licensing, the data sourcing, and whether the accuracy scoreboard is an internal tool or the marketing artifact.
5. **Is ESPN the only platform, ever?** Yahoo and Sleeper are on the "Bench" list. Because the domain model subclasses the ESPN client, this is not a later-adapter decision — it is a now-or-never modelling decision.
6. **What is the monetization model?** The operating manual says "build the smallest paid-worthy version first" and "avoid cool features unless they support subscription value," but nothing in the repo indicates who pays, for what, or at what price.
7. **Is self-delivering recaps still the vision?** It is called "the demo that sells this, and the itch that started the whole project," yet bot delivery was deferred and the M-series went in an entirely different direction. Six weeks later it remains unbuilt.
8. **How much offseason assumption-maintenance is acceptable?** The projections spec identifies the assumptions layer as "the part BBM actually charges for" and flags the burden as a real risk. That is a labour commitment, not an engineering one.
9. **What is the operational budget?** One VPS, one Supabase project, per-recap LLM spend, and no rate limits on unauthenticated LLM endpoints. Where the ceiling sits determines whether the current infrastructure is adequate or already over-exposed.
10. **Who runs this in-season?** Recap generation, publishing, projection uploads, and league refresh are all admin actions. Whether there is one operator or one per league changes what needs automating.

---

*Read-only forensic investigation. No replacement architecture proposed; no rewrite recommended. Evidence cited as `path:line` against the working tree at commit `dd25197`.*
