# Full Court Press — Architecture & Product Audit

**Date:** 2026-08-21  
**Author:** Cursor (forensic investigation)  
**Scope:** Read-only reconstruction of product, architecture, data model, and workflows. No replacement architecture. No code changes in the investigation itself.  
**HEAD at review:** `dd25197` (`M-1: unblock the historical backfill — CSV dataset adapter + nba_api hardening (#88)`)  
**Repo:** `fantasy-ball-is-life` · **Product name in UI/API:** Full Court Press (FCP)  
**Production:** `https://fcp.patrickmcdowell.dev`

This document treats the existing implementation as **evidence of what has been built**, not as a constraint on what should be built. Specs and docs are **intent**; code, migrations, tests, and git history are **evidence**.

The knowledge-graph MCP configured in `.mcp.json` was not connected during this session. The reconstruction was done by tracing routers, domain modules, migrations, frontend routes, deploy config, and git history.

---

## How to read this document

1. **Product reconstruction** — what FCP currently is (including identity split).
2. **Architecture map** — how the running system is shaped.
3. **The 20 investigation areas** requested for this phase.
4. **Strengths, weaknesses, deeper investigation, unanswered product questions.**

Replacement design is explicitly out of scope.

---

## Reconstructed product

**FCP is a web app for ESPN 9-category head-to-head fantasy basketball.**

There is a **product-identity split** in the evidence:

| Source | What FCP claims to be |
|---|---|
| `docs/PROJECT_DOSSIER.md` (2026-07-08–12) | A **GM’s cockpit**: connect league → decide (start/add/target/draft) → recap → auto-deliver to group chat |
| Landing page (`frontend/src/pages/Landing.tsx`) | An **AI newsroom**: weekly recaps, power rankings, matchups, season stats, in a sportswriter’s voice |
| What is actually built | Both, incompletely: a public league newsroom plus a private GM toolbox, plus scaffolding for an in-house projection model |

The original loop was built for **one league (Patriot Games, ESPN ID `3853870`)**. Scope then expanded, roughly:

1. Analytics engine + Streamlit/Flask tools (archived; Streamlit retired P-1).
2. React Draft Room (auction optimizer).
3. Weekly recap **newsroom** (structured LLM + publish workflow).
4. Platform overhaul (snapshots, auth, league-scoped URLs, design system).
5. Onboarding/growth (landing, join, create-a-league).
6. In-house **FCP projections** (NBA ingest + accuracy harness; model itself not built).
7. Specs for streaming advisor, trade analyzer, daily roster capture (mostly unimplemented).

The landing page no longer mentions draft, streaming, or “who to start.” Those surfaces still exist under **More**. The product that strangers see is the newsroom. The product originally locked in the dossier is the cockpit.

---

## Architecture map

```
Browser (React 19 + Vite SPA)
  ├─ Supabase JS (auth, memberships, invites, RLS reads)
  └─ Axios → Caddy /api/* → FastAPI (uvicorn)

FastAPI  (backend/api/main.py — title "Full Court Press API")
  ├─ LeagueSlugMiddleware  → ContextVar LeagueContext (decrypted ESPN cookies)
  ├─ ESPNRequestCacheMiddleware (one League() per request)
  ├─ Routers: league, recaps, draft, optimizer, projections,
  │           commentary, admin, create, create_league, legacy_redirects
  ├─ RecapStore = PostgREST client with service-role key
  └─ Domain: league/, draft/, recaps/, projections/, commentary/,
             worker/, nbadata/, analytics/

Postgres (hosted Supabase)
  ├─ Identity: profiles, leagues, memberships, invites
  ├─ League blobs: state snapshots, week scoreboards, week transactions,
  │                editorial week snapshots, recap editions, PR blurbs
  └─ Global NBA: nba_player_bio, nba_player_seasons

Also not in Postgres
  ├─ data/projections/*.parquet + manifest.json  (active projection sets)
  ├─ player_rankings/*.xls                       (legacy BBM drop zone)
  └─ data/game_logs.db                           (consistency / confidence)

External
  ESPN (espn-api + mTransactions2) · Anthropic · DeepSeek · nba_api / stats.nba.com

Cron (systemd on VPS, every 15 min)
  curl POST /api/admin/refresh-all  (X-Worker-Secret)
    → pull ESPN → compute → upsert snapshots
```

**Read model is split-brain** (partial P-3 migration):

| Snapshot-backed (Postgres) | Still live ESPN on the request |
|---|---|
| standings, settings, season_stats, power_rankings, current scoreboard, week transactions | `/meta`, `/teams`, `/matchups`, `/rosters/*`, `/projected-scoreboard`, `/matchup-confidence`, `/schedule`, draft optimizer, playoff-schedule’s pro-games call, create-league preview |

Recap **assembly** normally reads snapshots. `generate_draft()` calls `assemble_weekly_snapshot(force_fresh=False)` — the live ESPN admin path exists in `assemble.py` but is not what the generate endpoint uses.

---

## 1. What product is currently being built

A **multi-league-capable ESPN 9-cat platform** whose shipped consumer surface is the **weekly newsroom**, whose flagship GM tool is the **Draft Room**, and whose next large bet (October draft deadline in `FCP_PROJECTIONS.md`) is an **in-house projection model**. In-season advising (streaming, trades) is specified, not built.

Naming drift: repo `fantasy-ball-is-life`, comments still say PatriotGames, UI/API/deploy say Full Court Press.

---

## 2. Major user workflows

**Implemented**

1. **Arrive / account.** Logged-out `/` → landing. Sign up / login / password reset via Supabase. Invite redeem at `/join`. Zero-membership lobby. One membership → League Home; many → picker.
2. **Browse a public league.** Anyone with the link can view Patriot Games. League Home: claimed-team matchup, standings card, movers, latest recap, transaction ticker.
3. **Read the week.** Matchups by week. Standings + season stats. Newsroom: published recap, awards, power rankings, transactions. Season tools including playoff-week NBA schedule.
4. **Admin recap loop.** Sign in as admin → readiness → generate structured draft (Anthropic/DeepSeek) → review → publish / rollback. WhatsApp copy tools exist; **bot delivery does not**.
5. **Join.** Public league: claim an unclaimed ESPN team name. Private: invite token via `redeem_league_invite`.
6. **Create a league.** `/leagues/new`: ESPN ID + season → live preview → cookies only if private → encrypted store → owner/admin + team claim → cap of 2 leagues → initial snapshot refresh. This **contradicts** the P-series spec, which deferred self-serve ESPN connect.
7. **Draft Room.** Upload/select season projections → diverse auction plans (cvxpy MILP) → per-pick recompute, triage, relax, custom plans, Forge Value vs BBM $, Monte Carlo category targets, auction price sim. Plans live in React state + `localStorage`, not Postgres.
8. **In-season tools (live ESPN).** Current/projected scoreboards, roster projections, matchup confidence, on-demand AI matchup/season commentary.
9. **Projection sources.** Upload BBM / (Hashtag adapter exists but upload API only accepts `source=bbm`), activate ESPN-live virtual set, week- vs season-scoped.
10. **Internal accuracy page.** `/leagues/:slug/accuracy` scores stored week projections vs stored week actuals. **Not linked in nav.**

**Specified, not built**

- Streaming / add-drop advisor (`STREAMING_ADVISOR.md`)
- Trade analyzer (`TRADE_ANALYZER.md`)
- Daily roster snapshots (`DAILY_SNAPSHOTS.md`) — ESPN will not reconstruct yesterday’s roster
- FCP projection **model** (M-3+): rates, age curve, assumptions UI, rookies, week horizon
- Credential-health reconnect banner (N-5)
- Transactional email so open signup actually works (N-2c)
- Yahoo/Sleeper, payments, mobile wrapper, recap bots
- v1 playoff Monte Carlo (`season_simulation.py`) — marked Keep in the dossier, **never copied into this repo**

**Stale UI vs shipped behavior:** zero-membership lobby still says “Self-join is coming soon” even though N-2b self-join shipped.

---

## 3. Current system architecture

Two API surfaces, not one:

- **FastAPI** for league analytics, recaps, draft, projections, worker.
- **Supabase JS + RLS** for auth, memberships, invites, team claim.

Worker is **not a separate service**. Production systemd timer HTTP-POSTs the web process (`POST /api/admin/refresh-all`). `render.yaml` still describes a Render cron; that is leftover.

Caching layers:

1. Per-request ESPN `League` cache (`ESPNRequestCacheMiddleware`).
2. ~90s process-global TTL for `MyLeague` / `WeeklyScoreboard`.
3. Postgres snapshots (primary read path for flipped endpoints).
4. Per-week immutable scoreboard/transaction rows.
5. `power_ranking_editions` LLM blurb cache.
6. On-disk projection manifest.

---

## 4. Frontend architecture

**Stack:** React 19, Vite 8, Tailwind 4, React Router 7, TanStack Query 5, Axios, Supabase JS, Recharts, lucide.

**IA (P-6, landed on `main` despite the spec’s `platform/p-series` plan):**

- `/` → HomeResolver (landing / lobby / single-league redirect / picker)
- `/login` `/signup` `/reset-password` `/update-password` `/join`
- `/leagues/:slug` Home
- `/leagues/:slug/matchups/:week` matchup detail
- `/leagues/:slug/newsroom/:season/:week` newsroom
- `/leagues/:slug/standings`
- `/leagues/:slug/draft` `/season` `/accuracy`
- `/leagues/new` create wizard (auth required)
- `/settings` (auth required)
- Legacy `/draft` `/in-season` `/recap` redirect into league-scoped routes

Nav: **Home · Matchup · Newsroom · Standings · More** (Draft, Season). Default is no longer Draft. Spec’s preseason “Draft swaps into the bar” is **not implemented**.

**Auth:** `AuthProvider` around the router. Most of the app is **public** (demo league browsing). `RequireAuth` only on create-league and settings.

**Newsroom “admin mode”** is a **client toggle** in `NewsroomLayout` — not gated on `is_league_admin`. Generate/publish still need a JWT and backend admin checks. UX theater, not authorization.

**Data fetching:** React Query auto-load on snapshot surfaces (D-P6). **Season tools still has “Load Season Stats.”** Matchup **Tools** tab still hits live ESPN.

**Design system:** `frontend/src/ui/` primitives exist. Only Standings/PowerRankings (and Accuracy) consistently use `StateBlock`. `fetched_at` is unwrapped in the API client but **no StaleBadge is shown**. Dual `Card` components (`ui/Card.tsx` vs `components/Card.tsx`). League Home movers are badges, not the planned Recharts sparklines.

**Large files:** `api.ts` ~1090, `SeasonPage.tsx` ~615, `draft/Board.tsx` ~564, `ScoreboardTools.tsx` ~499, `LeagueHome.tsx` ~443. `InSeason.tsx` is a 1-line re-export stub. Streamlit has **zero** frontend remnants.

---

## 5. Backend architecture

FastAPI app factory: `backend/api/main.py`. No lifespan/startup hooks. CORS: localhost + `PUBLIC_APP_URL`.

**API surface (≈60+ routes vs dossier’s stale “27”)**

- **League** `GET /leagues/{slug}/…` — meta, schedule, matchups, power-rankings, confidence, teams, standings, settings, season-stats, playoff-schedule, projection-accuracy, rosters, transactions, scoreboard, projected-scoreboard
- **Recaps** `/leagues/{slug}/recaps/…` — current, archive, snapshot, readiness, generate, draft, editions, history, publish, rollback
- **Draft** `/draft/plans`, `/pick`, `/triage`, `/relax`, `/players`, `/auction-sim` — **not slug-prefixed**; ContextVar / first-league fallback
- **Legacy optimizer** `/optimizer/optimize`, `/optimizer/multiple-plans`
- **Projections** upload / list / activate / clear — **global, not per-league**
- **Commentary** `/matchup-commentary`, `/league-recap`, `/season-commentary` — request-time LLM, **no auth**
- **Admin** `POST /admin/refresh-all`, `/admin/refresh/{slug}` — `WORKER_SECRET`
- **Create** `POST /leagues/preview`, `POST /leagues` — JWT required
- **Legacy redirects** old flat `/league/*` → 307 into slug routes

`RecapStore` is a historical name: it is the generic PostgREST client for snapshots, credentials, NBA tables, and recaps.

`backend/league/data_feed.py` is **~2,699 lines** — ESPN I/O + domain + CLI + leftover prompt builders. Gravitational center of the backend.

Other large modules: `recaps/assemble.py` ~881, `draft/optimizer.py` ~798, `api/routers/draft.py` ~703, `recaps/store.py` ~664, `nbadata/ingest.py` ~653.

---

## 6. Database and data model

Ten migrations, which is also the expansion history:

| Migration | What it added |
|---|---|
| `20260712150000_recap_phase1.sql` | `profiles`, `leagues`, `league_memberships`, versioned `league_week_snapshots`, `recap_editions`, seed Patriot Games |
| `20260714140000_power_ranking_editions.sql` | Persist LLM ranking blurbs |
| `20260717220000_league_state_snapshots.sql` | Rolling current state, unique `(league_id, season, phase)` |
| `20260717230000_league_credentials.sql` | Encrypted `espn_swid`/`espn_s2`, timezone, pgcrypto RPCs (service-role only) |
| `20260718070000_membership_team_name.sql` | Claim “my team”; column-level grant so members cannot self-promote `role` |
| `20260719200000_n2_invites_self_join.sql` | Invites, self-join, team-claim unique index, redeem RPC |
| `20260723120000_league_week_scoreboards.sql` | Immutable **per week** (rolling scoreboard only held *current* week) |
| `20260724120000_league_week_transactions.sql` | Same bug for Moves/Trades season totals |
| `20260724130000_nba_player_bio.sql` | Global player identity |
| `20260724130001_nba_player_seasons.sql` | Global historical per-game stats (makes **and** attempts) |

`supabase/config.toml` references `./seed.sql`; **no `seed.sql` exists**. Seeding is the phase-1 insert + `backend/scripts/seed_league.py`.

**Three snapshot systems**

| Store | Grain | Mutability |
|---|---|---|
| `league_state_snapshots` | `(league, season, phase)` | UPSERT rolling latest |
| `league_week_scoreboards` / `_transactions` | `(league, season, week)` | Immutable per week |
| `league_week_snapshots` + `recap_editions` | `(league, season, week, version)` | Versioned editorial record |

Daily roster/scoreboard tables from `DAILY_SNAPSHOTS.md` are **not migrated**.

**Postgres holds:** identity, ESPN cookies (encrypted), JSON blobs of computed league state, recap editions, NBA history.  
**Postgres does not hold:** projection sets, draft plans, game-log consistency DB, daily roster history.

**RLS gap:** `league_state_snapshots`, `league_week_scoreboards`, and `league_week_transactions` SELECT is **public-leagues only**. Private members cannot read those tables via the Supabase client; FastAPI bypasses RLS with the service role.

Encryption: AES-256 pgcrypto; `CRED_ENCRYPTION_KEY` is passed into the RPC as `pwd` (TLS-protected; key not stored in DB).

---

## 7. How fantasy basketball domain logic is represented

The 9 cats are a first-class constant: `PTS, REB, AST, STL, BLK, 3PM, FG%, FT%, TO` with **TO inverted** (`LOWER_IS_BETTER_STATS`). Direction is applied at comparison time, not by storing negated TO.

| Concept | Where |
|---|---|
| Category W/L/T | `data_feed.category_result` |
| H2H-each-category standings (sum of **category** wins, not matchup wins) | `assemble.standings_from_week_scoreboards` |
| Universe / all-play wins | `MyLeague.get_universe_wins` → `WeeklyScoreboard.all_play` |
| Power rankings | `_live_power_rankings`: **0.35 all-play + 0.35 recent all-play + 0.20 actual H2H + 0.10 category dominance** |
| Canonical matchups + ESPN tiebreak `winner` | `assemble.canonical_matchups` |
| Auction draft MILP | `draft/optimizer.py` (`OptimizeLineup`, cvxpy, 8s cap) |
| Plan diversity / per-pick / triage / relax | `draft/strategies.py`, `engine.py` |
| Monte Carlo category targets | `draft/targets_mc.py` (default `target_method="monte_carlo"`) |
| Forge Value | `draft/values.py` — VORP-style `model_value` scaled to league budget/roster |
| Auction price sim | `draft/auction_sim.py` |
| Playoff week NBA games | `league/playoff_schedule.py` from stored settings + ESPN pro schedule |
| “Win probability” | **Not a model.** Live: category-win share (ties = 0.5). Projected: average confidence % over decisive cats. |
| Confidence tiers | `analytics/consistency.py` vs `data/game_logs.db` |
| Awards | `recaps/awards.py` (deterministic) + LLM explanations |
| Recap facts vs takes | `assemble.py` (facts) → `commentary/` (structured JSON) |

`MyLeague` subclasses `espn_api.basketball.League` and skips the eager pro-schedule fetch during construction.

**Hardcoded domain that should be data:** `_MATCHUP_WEEK_CALENDARS` in `data_feed.py` (2025–26 week windows). Frontend `lib/matchupWeeks.ts` mirrors it. `DO_NOT_DRAFT` and `POSITION_OVERRIDES` (`Anthony Davis` → C) are league-owner taste in `config.py`.

FG%/FT% multi-week aggregation **means weekly percentages** in season stats — documented tension vs aggregating makes/attempts (ESPN API review). Product choice, not fully locked.

---

## 8. Projections, rankings, player data, league data, calculated data

**League data**

```
ESPN ──connect()/MyLeague──► worker.refresh_league
                               ├─ league_state_snapshots (rolling phases)
                               ├─ league_week_scoreboards (immutable per week)
                               ├─ league_week_transactions
                               └─ week-horizon ESPN ProjectionSet (parquet)
User GET /standings etc. ──► _snapshot_read ──► Postgres
User GET /rosters, /projected-scoreboard ──► live ESPN (+ projections registry)
Recap generate ──► assemble_weekly_snapshot (snapshots; force_fresh unused by endpoint)
                ──► LLM structured JSON ──► recap_editions
```

**Projections**

```
BBM xls / Hashtag paste / ESPN last-15 ──adapters──► PlayerProjection
     ──ProjectionStore (parquet + manifest)──► get_active_projections(horizon)
Consumers: projected scoreboard, draft optimizer (P-8 wired season source),
           accuracy scoreboard vs league_week_scoreboards
```

ESPN week sets can be league-tagged (`ProjectionSet.league_slug`); BBM/Hashtag uploads are **global**. Activating a set is process-wide, not per user or per league.

**NBA / FCP model (partial)**

```
nba_api / CSV backfill ──► nba_player_seasons + nba_player_bio
reader + backtest harness ──► naive last-season baseline (M-3a)
fcp_model.py ── DOES NOT EXIST
nba_rookie_translation / projection_assumptions ── NOT MIGRATED
```

**Rankings / calculated data** are not a separate store. Power rankings and season stats are JSON in snapshot rows, recomputed on each worker run.

---

## 9. Authentication and user/account architecture

Two stacks:

1. **Supabase Auth** (email/password). `profiles` auto-created on signup. Frontend session in `AuthProvider`. Invite-gated signup was removed; **open signup is blocked in practice by N-2c** (built-in SMTP does not deliver). Cosmetic gate: signup form shown only if `?invite=` or `VITE_SIGNUP_OPEN=true`.
2. **FastAPI** verifies JWT by calling `GET /auth/v1/user`. Admin = `league_memberships.role in (owner, admin)` or `leagues.admin_user_id` / `owner_user_id`.

Create-league is authenticated. Recap generate/publish is authenticated + admin. Snapshot refresh is a shared `WORKER_SECRET`. Almost all league GETs, draft, projections, and commentary are **open** if you know the URL.

Team identity is a **string claim** (`league_memberships.team_name`), unique per league, fragile if ESPN renames the team.

---

## 10. External data sources and integrations

| Source | Use |
|---|---|
| ESPN Fantasy (`espn-api`, cookies for private leagues) | League, rosters, box scores, settings, pro schedule |
| ESPN `mTransactions2` | Adds/drops/trades (espn-api `recent_activity` 404s) |
| Basketball Monster Excel | Season/week projections (user upload) |
| Hashtag Basketball | Adapter exists; upload route only accepts BBM |
| ESPN player stats (last 15/30) | Virtual week projection source |
| Anthropic Claude | Structured recaps (**code default**) + legacy commentary |
| DeepSeek | Optional recap provider (`RECAP_LLM_PROVIDER=deepseek`) |
| `nba_api` / stats.nba.com | Historical player seasons + bios |
| Supabase | Auth + Postgres |

README still says recap drafts default to DeepSeek; `config.py` defaults `RECAP_LLM_PROVIDER` to **`anthropic`**.

ESPN ToS / unofficial API is still the production dependency. The snapshot worker exists partly to bound request volume to `leagues × cadence` instead of `users × page loads`.

---

## 11. Background jobs and ingestion

**Snapshot refresh (production):** systemd timer `fcp-snapshot-refresh` → `curl POST /api/admin/refresh-all`.

`refresh_league` phases, each isolated: settings, standings, scoreboard, transactions, power_rankings, season_stats, plus week-scoreboard backfill, week-transaction backfill, week projection snapshot.

**NBA ingest:** CLI (`backend/nbadata/ingest.py`, `csv_backfill.py`). Rate-limited, resumable. Not wired as a production cron the way snapshot refresh is.

**No queue.** Heavy work is HTTP-on-the-web-process (refresh, recap generate, draft solve) or local CLI.

---

## 12. Deployment / infrastructure

**Production:** VPS `/srv/fullcourtpress`, Docker Compose (backend + Caddy), frontend `dist` scp’d from GitHub Actions, Caddy terminates TLS and strips `/api`. Hosted Supabase project `wuzoengojiqotusulwhj`. Domain `fcp.patrickmcdowell.dev`.

**Also present:** `render.yaml` (web + cron + static) — leftover from the Render era.

**CI:** `.github/workflows/ci.yml` (pytest + frontend build/tsc/vitest/eslint) and `deploy.yml` (local Supabase RLS tests, backend tests, `supabase db push` on main, then VPS deploy). Python **3.11** in CI/Docker; `render.yaml` still says 3.12.

Dockerfile copies only `backend/`. Projection parquet files are not in the image; unless they live on the VPS filesystem outside the container, projection state is not durable the way Postgres is.

**Security finding:** `docs/DEPLOY.md` contains **live production secrets** (service role, encryption key, worker secret, LLM keys, ESPN cookies). Treat as compromised and rotate. Values are not repeated here.

---

## 13. Testing strategy

**Backend:** ~49 pytest modules under `tests/`. Strongest around draft, projection adapters/precedence, recap assembly, ESPN gateway, snapshot worker, slug middleware, N-2 RLS (local Supabase in deploy workflow), N-4 create-league, playoff schedule, NBA ingest/backtest. Live ESPN and gitignored projection files skip in CI by design. `conftest.py` scrubs deployment secrets (#71).

**Frontend:** 15 Vitest files — routing, slug, HomeResolver, join/create, accuracy, nav — not full Draft Room or newsroom editorial flows.

**Gaps:** no load/perf tests for recap/LLM; no authz tests that FastAPI league GETs are public; little coverage that commentary spend is ungated; no recorded raw ESPN JSON contract fixtures (recommended in `ESPN_API_REVIEW.md`).

---

## 14. Repository / file structure

```
backend/     package by concern (post BACKEND_RESTRUCTURE)
  api/       main, deps, middleware, routers
  league/    ESPN + MyLeague + create + playoff_schedule
  draft/     optimizer engine
  recaps/    newsroom persistence + assemble
  projections/ adapters, store, accuracy, backtest
  commentary/ prompts + LLM clients
  worker/    snapshot refresh
  nbadata/   NBA ingest
  analytics/ consistency
frontend/    React SPA
supabase/migrations/
tests/
docs/ + docs/specs/
deploy/      systemd units
```

Stale vs actual: README still describes a single-league app and empty `backend/projections/`. Dossier snapshot (“27 endpoints, 4 pages”) is months behind. ESPN audit still says `config.LEAGUE_ID` is not overridable (P-4 fixed that). Root still has leftover CSVs (`Week 21_scoreboard.csv`, `week_22_roster.csv`).

---

## 15. Where responsibilities are cleanly separated

- **Projection adapters** vs consumers (`PlayerProjection` + `get_active_projections`) — best seam in the repo.
- **Recap facts vs AI takes** (`assemble` / `WeeklyFactSnapshot` vs LLM JSON, with `AiTakeBadge`).
- **Snapshot worker vs request path** for the surfaces that actually flipped.
- **Credential encryption** (pgcrypto RPCs, service-role only, key in env).
- **Create-league validation** (`league/create.py` constructs ESPN `League` without falling through to the seeded league).
- **ESPN gateway** (timeouts scoped to espn-api, not all `requests`).
- **Frontend design-system start** (`ui/`) and league-scoped nav.
- **RLS for invites/self-join/team claim** with security-definer redeem.

---

## 16. Where responsibilities are coupled or unclear

- `data_feed.py` is ESPN I/O + domain + CLI + leftover commentary prompts.
- `RecapStore` is the database layer for the whole product.
- `assemble.py` imports `backend.api.routers.league` for live fallback — domain depends on the HTTP layer.
- Worker power rankings call `_live_power_rankings` inside assemble during a job that is supposed to be the *writer*.
- Auth: FastAPI vs Supabase client vs worker secret vs open GETs.
- Draft/optimizer/projections/commentary not under `/leagues/{slug}`.
- Two recap products: newsroom (persisted, gated) vs `/league-recap` + matchup commentary (live, ungated).
- Two draft APIs: `/draft/*` and `/optimizer/*`.
- Rolling snapshots *and* per-week tables *and* editorial `league_week_snapshots`.
- `LeagueContext` via ASGI middleware because FastAPI sync threadpools drop ContextVars.
- Frontend memberships via Supabase; league analytics via FastAPI.

---

## 17. Where duplication exists

- Legacy commentary recaps vs newsroom recaps
- `/optimizer/*` vs `/draft/*`
- Rolling `league_state_snapshots.scoreboard` vs `league_week_scoreboards` (same for transactions)
- `ui/Card.tsx` vs `components/Card.tsx`
- `render.yaml` cron vs VPS systemd timer vs `cron_entrypoint.py` (`RENDER_EXTERNAL_URL`)
- `ci.yml` and `deploy.yml` both run backend tests
- README / dossier / ESPN audit vs current code
- Lobby copy vs shipped self-join
- Product names: fantasy-ball-is-life, PatriotGames, Full Court Press, FCP, Forge Value
- Matchup week calendar in backend **and** `frontend/src/lib/matchupWeeks.ts`
- Unused client methods: `getLeagueSchedule`, `getCurrentWeekMatchups`, `postOptimizer*`, `postFeedRun`, `getHealth`

---

## 18. Where technical debt has accumulated

1. **`data_feed.py` god module** (~2.7k lines).
2. **Incomplete snapshot inversion** — P-3 goal was “no ESPN in the request path”; rosters, projected scoreboards, draft, and meta never flipped.
3. **File-based projection store** on a Docker host with no volume in compose — fights multi-league and durability.
4. **JSON blob domain model** — every new query (past-week standings, season Moves) required a new table or a re-derive.
5. **Hardcoded matchup calendar** — dossier cut-list item, still present.
6. **Ungated LLM endpoints** — cost and abuse if the app is actually public.
7. **Secrets in git** (`docs/DEPLOY.md`).
8. **N-2c / N-5 unfinished** — growth and credential failure are operational holes.
9. **Daily rosters not captured** while the window to capture them closes.
10. **`optimizer` `out_prefix` path-traversal note** still open in the ESPN audit.
11. **Python / deploy config drift** (3.11 vs 3.12, Render vs VPS).
12. **Personal draft pool knobs** in env defaults.
13. **P-series polish unfinished** — Season manual load, no staleness UI, no Home sparklines, Hashtag upload unwired.

---

## 19. Historical artifacts of expanding scope

These exist because the product kept growing, not because a single architecture was chosen:

| Artifact | Likely origin |
|---|---|
| Dual AI recap systems | Streamlit-era Claude endpoints, then newsroom as the real product |
| Dual optimizer APIs | Flask/Streamlit optimizer, then Draft Room |
| Three snapshot tables | Newsroom editorial → rolling worker → discovered rolling ≠ history |
| `RecapStore` name | Recaps were the first Postgres feature; everything else piled on |
| File projections vs DB league state | Projection framework shipped before multi-tenant persistence |
| `platform/p-series` spec vs merge-to-main | Overhaul was supposed to preview in parallel; it became main |
| Landing = newsroom, More = GM tools | Growth/N-series reframe on top of cockpit |
| `nba_*` tables before `fcp_model.py` | Build ingest + scoreboard first (M-1/M-2) so the model has a boss battle |
| Render yaml + VPS deploy | Hosting move mid-stream |
| ContextVar + ASGI slug middleware | Multi-league bolted onto sync handlers that assumed one global league |
| `InSeason.tsx` re-export | Route rename without deleting the old module name |
| Dossier “Starting Five” vs M/N/W/S/T series | Each later series is a new product bet |
| Create-league wizard | N-4 overrode P-series “no self-serve connect” non-goal |

Git phases on `main` (compressed): core analytics → draft depth → ESPN hardening → projection framework → newsroom → P-series platform → VPS self-host → N-series onboarding → per-week correctness wave → July spec batch (docs ahead of code) → M-series foundation.

---

## 20. Which parts appear genuinely well designed

1. **9-cat / all-play / recap fact assembly** — real fantasy math, tested, with TO direction and ESPN tiebreaks handled explicitly.
2. **Draft Room as an engine** — MILP + diversity + per-pick recompute + MC targets + Forge Value is coherent IP, not a wrapper around ESPN.
3. **Newsroom pattern** — deterministic snapshot, versioned editions, one published row, labeled AI, admin workflow. This is the one place that looks like a product, not a notebook.
4. **Projection adapter contract** — one schema, multiple sources, precedence rules, accuracy harness that can score BBM vs ESPN *before* FCP exists.
5. **Create-league preview** that does not silently validate the seeded league.
6. **Worker phase isolation** — one failed ESPN phase does not wipe the others; stale ≠ down for flipped reads.
7. **Learning from the rolling-snapshot bug** — `league_week_scoreboards` / `_transactions` plus as-of standings from history is the right correction.
8. **ESPN gateway + request cache** — timeouts and “one League() per request” after measuring 4 eager calls / ~2.5 MB.
9. **Spec-and-test cadence** — N/P/M/W series with hermetic tests and ESPN isolation is how this repo actually ships.
10. **Credential encryption + team-claim grants** — small, careful multi-tenant work.

---

## Most important strengths

- There is a working **domain engine** (draft + all-play + 9-cat recap facts) that would be expensive to rediscover.
- The **newsroom + snapshot worker + slug-scoped UI** is a coherent consumer product for one public league, and it is in production.
- The **projection framework + accuracy scoreboard + NBA ingest** is a credible path to an in-house model without rewriting consumers.
- Multi-league is **more real than the README admits**: DB credentials, worker loop, create wizard, join/invite, league-scoped frontend.

## Most important weaknesses

- **Two products in one repo**, with the landing page committed to only one of them.
- **Read path is half-migrated** — “Postgres is the system of record” is true for standings/recaps and false for the decision tools.
- **`data_feed.py` + JSON blobs + file projections** will not scale cleanly to many leagues or a real projection model.
- **Authz does not match a public app** (open analytics/LLM/draft; secrets in a doc).
- **Docs are a lagging indicator** — using README/dossier alone reconstructs a 2026-07-12 product, not today’s.
- **Un-backfillable roster history is still not being captured**, while several specs depend on longitudinal roster state.

---

## Areas that require deeper investigation

These cannot be settled from a static read:

1. **Production data:** how many `leagues` rows exist; whether a second league has actually been refreshed end-to-end; projection parquet contents on the VPS; whether `nba_player_seasons` is backfilled.
2. **Live ESPN remaining latency** on matchup Tools / draft / meta — whether P-3’s “<1s” applies only to Home/Standings/Newsroom.
3. **LLM quality and cost** in production (Anthropic vs DeepSeek, recap vs commentary).
4. **Whether any caller still uses `force_fresh` recap assembly** (the generate endpoint does not).
5. **Projection durability** under Docker (no volume in compose).
6. **Who can hit ungated `/matchup-commentary` and `/draft/plans` on the public host.**
7. **N-2c email** — is signup actually usable for anyone but Patrick?
8. **Playoff simulator archive** — does it still exist outside the repo?
9. **Daily roster gap** — how much 2025–26 roster history is already gone.
10. **Secret rotation** after `DEPLOY.md` exposure.

---

## Product questions the repository cannot answer

1. **What is FCP primarily?** League newsroom (what landing sells), GM cockpit (what the dossier locked), or projection company (what M-series + October draft deadline imply)?
2. **Who is the user in 2026–27?** Patrick only, Patriot Games members, any ESPN commissioner, or paying managers?
3. **Is Draft Room still a private competitive edge**, or a league-facing feature now that it is in the nav?
4. **Are streaming + trades required for v1**, or is newsroom + draft + own projections the actual product?
5. **Must FCP projections beat BBM before next draft**, or is BBM-upload acceptable another year?
6. **Will recaps ever self-deliver** (WhatsApp/Discord), or is the newsroom URL the delivery?
7. **Yahoo/Sleeper** — still a goal, or ESPN-only forever?
8. **Monetization** — still “nobody pays before multi-league works,” and is multi-league now “working”?
9. **Public Patriot Games as the demo** — is leaking recaps/standings/power rankings to the internet acceptable long-term?
10. **Category format lock** — 9-cat H2H only, or other ESPN formats later? (Code assumes these 9 cats everywhere.)
11. **How many real humans have signed up**, and did N-2c ever get solved outside the repo?
12. **Willingness to keep unofficial ESPN + nba_api** as the spine of a product you might charge for.
13. **Power-ranking FG%/FT% semantics** — aggregate makes/attempts vs average weekly % (flagged, not locked).
14. **Win “probability” product definition** — strip is lean/confidence, not calibrated odds.

---

## Spec vs code (summary)

| Feature | Spec status | Code status |
|---------|-------------|-------------|
| Newsroom / recaps | APPROVED | **Built** |
| P-series platform | APPROVED | **Mostly built** on `main` (polish incomplete) |
| Draft Room | Approved | **Built** |
| MC targets | Implemented | **Built** (default) |
| Projection framework | Approved | **Built** (P-1..P-11); Hashtag upload unwired |
| Onboarding N-1..N-4 | Done in spec | **Built** |
| Onboarding N-2c, N-5 | Open | **Not built** |
| Playoff schedule | Shipped #83 | **Built** |
| FCP M-1 ingest | Spec | **Built** |
| FCP M-2 accuracy | Spec | **Built** |
| FCP M-3a backtest | Spec | **Built** (naive baseline only) |
| FCP M-3..M-7 model | Spec | **Not built** |
| Daily snapshots | Spec | **Not built** |
| Streaming advisor | Spec | **Not built** |
| Trade analyzer | Spec | **Not built** |
| Playoff Monte Carlo | Dossier “Keep” | **Never copied into this repo** |

---

## Bottom line

The repo is a **working multi-league ESPN 9-cat platform** centered on an **AI weekly newsroom + draft optimizer + snapshot-backed league analytics**, with **infrastructure for an in-house projection model started but the model itself not shipped**. The largest documented-but-unbuilt product bets are **in-season advising** (streaming, trades) and **longitudinal roster capture**.

The highest-leverage fork for any later architecture work is the **product-identity question** (newsroom vs cockpit vs projection engine), because the architecture already contains three overlapping systems built to serve those three answers.

This phase did **not** design a replacement architecture.
