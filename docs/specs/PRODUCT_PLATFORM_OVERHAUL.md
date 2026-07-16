# Feature Spec: Product Platform Overhaul — GM's Cockpit Shell

**Status: DRAFT** — pending Patrick (product) + Aisha (architecture) review.
Nothing in the P-series is implementation-authorized until this header says
APPROVED.

**Handoff note for agents (Claude, Codex, Cursor):** this spec is the single
source of truth for the platform overhaul. Before implementing, read this
spec + `docs/PROJECT_DOSSIER.md` + `docs/AISHA_OPERATING_MANUAL.md` +
`CONTRIBUTING.md`. Commit often, write tests, keep PRs small and in the
stated order — later PRs assume earlier ones landed. If you hit an ambiguity
not covered here, flag it — do not guess. Pull `main` before starting.

**Author:** Claude Code (lead engineer), from the full product/UX/architecture
review conducted 2026-07-16 at Patrick's request.
**Decision basis:** Dossier §02 defines the product ("a GM's cockpit for
9-cat H2H — closes the loop from data → decision → story"). Dossier
Decision A locks the audience (Patrick's league first, architecture
multi-league-ready). This spec is the structural work that makes the app
*look and behave like that product* instead of a collection of internal
tools, and removes the two architectural blockers to any wider launch:
request-time ESPN computation and deployment-level league hardcoding.

---

## 0. Why now, concretely

- The review found no frontend-framework problem — React 19 + Vite +
  Tailwind 4 + FastAPI + Supabase is the right stack and stays. The problems
  are shape, not stack:
  1. **Two frontends drift.** `app.py` (1,699-line Streamlit tool) still
     duplicates all four product surfaces and silently rots (its recap tab
     predates the entire newsroom).
  2. **Feature-shaped IA.** Nav is Draft / In-Season / Recap / Season in
     build order; the default route is `/draft` — a preseason tool as the
     front door of an in-season product. No landing page, no login page
     (auth is an inline form inside `WeeklyRecapTab.tsx`), no account
     surface.
  3. **Request-time ESPN computation.** Every analytics read (standings,
     power rankings, season stats) constructs ESPN league objects and runs
     the full math synchronously per HTTP request. Production logs measured
     the recap-assembly Power Rankings phase at **140–171 s**. Caching PRs
     (E1–G) reduced fan-out but cannot fix the model: a consumer product
     cannot do third-party fetch + heavy compute inside a page load.
  4. **Deployment-level league hardcoding.** `ESPN_LEAGUE_ID` / `ESPN_SWID`
     / `ESPN_S2` / `RECAP_LEAGUE_SLUG` are env vars (`backend/config.py`);
     every `/league/*` endpoint uses module-level `config.LEAGUE_ID` — the
     open audit finding. The Supabase schema (`leagues`,
     `league_memberships`) is multi-tenant-ready; the ESPN layer is not.
  5. **No design system.** `DraftPage.tsx` (1,686 lines) and `InSeason.tsx`
     (1,315 lines, excluded from CI lint) are monoliths; empty/loading/error
     states are hand-rolled per page; production users see dev-facing error
     copy ("Start the backend (e.g. uvicorn…)"); there is no charting
     anywhere in a stats product.
- The newsroom (F2 series) is the proof of the right pattern on every axis:
  league-scoped URLs, snapshot-backed reads, editorial design, deterministic
  facts with labeled AI takes. **This spec generalizes the newsroom pattern
  to the whole app.**

---

## 1. User stories

> As a league member opening the app mid-week, I want to land on *my league,
> this week* — my matchup's live category tally, ranking movement, the
> latest recap — without hunting through tool tabs, so checking the app
> takes thirty seconds on my phone.

> As a returning user, I want every page to load in under a second from
> stored data (with a visible "as of" freshness stamp), instead of waiting
> on live ESPN math that sometimes takes minutes or fails.

> As Patrick (commissioner/admin), I want league identity, credentials, and
> season calendar to live in the database per league — not in deployment
> env vars — so adding a second league is a data row, not a redeploy.

> As a future paying user, I want a real front door: a landing page that
> shows what the product is, a sign-up/login flow, and an account surface —
> so trusting the app with an account feels normal, not improvised.

Secondary story (explicitly *not* built now, but never blocked): tiered
subscriptions gating leagues-per-account and tool depth. Every decision in
this spec must leave that a config flip, per Dossier Decision A.

---

## 2. Decisions

### Locked by this spec (Patrick to confirm at review)

- **D-P1. Streamlit retires.** `app.py` is deleted from `main` after a
  `legacy-streamlit` tag. Any ergonomics it uniquely has become migration
  tickets (§9). No further maintenance from the moment this spec is approved.
- **D-P2. No Next.js migration.** SEO-relevant surfaces are exactly two
  (landing page, published recaps); the existing plan for F2-7 (FastAPI
  prerender/OG route) covers them. React + Vite stays.
  *Contested by a second-opinion review (2026-07-16, see Addendum) which
  recommends porting to Next.js for SSR/server sessions/streaming. Decision
  stands: the app's heavy surfaces (Draft Room, In-Season) are
  client-state-dense and would be `"use client"` throughout, negating
  server-component benefits; nested league routes and auth work identically
  in react-router + Supabase; and the port burns 1–2 weeks of the P-series
  on plumbing with no user-visible gain. Revisit trigger: if a public
  multi-league launch makes per-league SEO pages (public team/player pages,
  many-league landing surfaces) a real requirement, reopen this decision
  then — the component layer built in P-2 ports either way.*
- **D-P3. Snapshot-serving becomes the default read model** (§3). Live
  ESPN calls move out of the request path for every league-analytics
  surface. The admin "Generate Draft" flow may still force a fresh pull.
- **D-P4. Payments are out of scope** for the P-series. Auth surfaces ship;
  billing does not. Nobody pays before multi-league works.
- **D-P5. League Home replaces `/draft` as the default route.** Tools keep
  first-class nav but stop being the front door.
- **D-P6. Reads auto-load; only generation is manual.** The current UI is
  click-to-fetch throughout (`InSeason.tsx`: `loadActiveScoreboard`,
  `markLoaded('powerRankings')`, etc.) — an artifact of the era when every
  read was an expensive live ESPN call. Once P-3 makes reads cheap Postgres
  hits, every read surface fetches automatically on mount via React Query
  (with `StateBlock` skeletons). Explicit buttons remain **only** for
  actions that cost real money or mutate state: LLM generation
  (recap draft, AI commentary), publish/rollback, solver runs, admin
  force-refresh. "Load X" buttons are a bug after P-6.

### Open for Aisha (architecture review)

- **Q-A1.** Worker runtime: Render Cron Job invoking a FastAPI admin
  endpoint, vs. a separate worker process, vs. Supabase pg_cron + HTTP
  trigger. Spec assumes **Render Cron → authenticated FastAPI endpoint**
  (fewest moving parts; same codebase, same deploy). Push back if wrong.
- **Q-A2.** Refresh cadence: proposed 15 min during NBA game windows
  (~23:00–06:00 UTC in season), 6 h otherwise, manual force-refresh for
  admins. Tune freely.
- **Q-A3.** Snapshot table design: extend `league_week_snapshots` vs. new
  `league_state_snapshots` table (§3.3 proposes the latter — different
  lifecycle: rolling current-state vs. immutable per-week editorial record).

---

## 3. Architecture keystone: the snapshot worker

### 3.1 Principle

One scheduled job per league does: **pull ESPN → compute → write Postgres.**
Every user-facing GET reads Postgres only. `MyLeague`, `get_universe_wins`,
`standings_df`, the transaction adapter — all keep their exact logic, but
run inside the job, never inside a request. ESPN request volume scales with
`leagues × cadence`, not with users — which is also the rate-limit and
ToS-exposure mitigation.

### 3.2 The job

- `backend/worker/refresh.py`: `refresh_league(league_id)` —
  orchestrates the existing loaders (the same five phases
  `assemble_weekly_snapshot()` times today: standings, power rankings,
  scoreboard, transactions, season stats + settings/playoff context).
- Each phase writes its payload independently with per-phase
  `fetched_at` — one slow/failed phase must not block the others
  (mirror `_capture()`'s isolation in `backend/recaps/assemble.py`).
- Failures: log with the existing phase-timing instrumentation, keep the
  previous snapshot, surface staleness to the UI. ESPN being down means
  *stale*, never *down*.
- Trigger: `POST /admin/refresh/{league_id}` guarded by a worker secret
  (not a user JWT), called by Render Cron per Q-A1; plus an authenticated
  admin force-refresh from the UI.

### 3.3 Data model (Supabase migration)

```sql
create table public.league_state_snapshots (
  id uuid primary key default gen_random_uuid(),
  league_id uuid not null references public.leagues(id),
  season int not null,
  week int not null,               -- ESPN current matchup period at fetch
  phase text not null,             -- 'standings' | 'power_rankings' |
                                   -- 'scoreboard' | 'transactions' |
                                   -- 'season_stats' | 'settings'
  payload_json jsonb not null,
  fetched_at timestamptz not null default now(),
  unique (league_id, season, phase) -- rolling upsert, one live row per phase
);
```

Rolling upserts (current state), unlike `league_week_snapshots` (immutable
weekly editorial record) — the two coexist; recap generation keeps its own
versioned snapshots. RLS: readable per league visibility (same policy shape
as `recap_editions`), writable by service role only.

### 3.4 Read path

- Existing endpoints keep their URLs and response shapes but become
  Postgres reads: `/league/standings`, `/league/power-rankings`,
  `/league/season-stats`, scoreboard and transactions GETs. Each response
  gains `fetched_at`. The frontend renders an "as of" stamp (component in
  P-2) whenever data is older than one cadence interval.
- `assemble_weekly_snapshot()` reads the same stored phases instead of
  calling `league_api.*` live (its 60 s TTL cache then becomes redundant
  and is removed). "Generate Draft" may pass `force_fresh=true` to pull
  live first — the admin is the one user allowed to wait.
- The E-series request-cache (`ESPNRequestCacheMiddleware`) stays — the
  worker benefits from it within a run.

### 3.5 Acceptance criteria

1. Cold page loads of standings / rankings / newsroom tabs complete from
   Postgres in < 1 s p95 (no ESPN call in any request trace).
2. Recap readiness/generate performs zero live ESPN calls unless
   `force_fresh` — measured by the existing phase logs.
3. Killing ESPN access entirely (bad cookie) leaves every read surface
   serving the last snapshot with a visible staleness stamp; no 5xx.
4. Worker run for one league completes in < 5 min and is idempotent.
5. All existing tests pass; new tests cover upsert semantics, staleness
   surfacing, and the worker-secret guard.

---

## 4. Multi-league configuration (closing the audit finding)

- `leagues` table gains: `espn_league_id bigint`, `espn_season int`,
  `espn_swid text`, `espn_s2 text` (encrypted at rest — Supabase Vault or
  pgcrypto; Aisha to pick), `timezone text`.
- The worker iterates `leagues` rows; `connect()` / `get_cached_my_league()`
  take explicit `(league_id, season, credentials)` instead of reading
  module constants. `config.LEAGUE_ID` / `SWID` / `ESPN_S2` become the
  *seed values* for the Patriot Games row (one-time migration script), then
  the constants are deleted.
- League-scoped API routes (`/leagues/{slug}/…`) already resolve the league
  row; the remaining flat `/league/*` endpoints move under the slug (with
  redirects kept one release for the old paths).
- **Non-goal here:** self-serve league connection UI. Rows are inserted by
  admin/script in the P-series; the connect *flow* is a later feature. The
  data model must simply make it possible.

---

## 5. Information architecture and routes

```
/                       logged-out → landing (P-8) · logged-in → /leagues/:slug
/login  /signup         real auth pages (P-5)
/leagues/:slug          League Home — NEW (P-6)
/leagues/:slug/matchups/:week    matchup detail (from InSeason core)
/leagues/:slug/newsroom/:season/:week   existing newsroom (route rename,
                                        redirect from /recaps/… kept)
/leagues/:slug/standings         promoted from newsroom tab (shared component)
/leagues/:slug/draft             Draft Room (seasonal prominence)
/settings                        profile + league connections
```

- Flat `/draft`, `/in-season`, `/season`, `/recap` become redirects into the
  league-scoped equivalents (single-league: redirect resolves via
  `VITE_RECAP_LEAGUE_SLUG` exactly as `Recap.tsx` does today).
- Logged-in `/` resolves by membership count: exactly one league → straight
  to `/leagues/:slug`; more than one → a minimal league-picker list (a
  trivial page once `league_memberships` is read — build it in P-6 rather
  than reserving a separate `/app` route for later).
- Mobile `BottomTabBar` / desktop `TopNav`: **Home · Matchup · Newsroom ·
  Standings · More** ("More" sheet: Draft Room, Season tools, Settings,
  admin). Draft Room swaps into the bar in preseason (settings-driven date
  window, not hardcoded — see Cut List, dossier §03).

---

## 6. Auth surfaces (P-5)

- Extract session handling from `WeeklyRecapTab.tsx` into an app-level
  `AuthProvider` (context + `useSession()`); `TopNav` gains a profile
  menu (avatar initial, sign out, settings).
- Real `/login` page (email/password now, OAuth later — Supabase makes that
  additive). `/signup` ships **invite-gated**: league members only, via
  `league_memberships`. Public self-serve signup waits for the launch
  decision; the page and table are ready either way.
- Password reset via Supabase's built-in flow.
- Admin remains `league_memberships.role = 'admin'` (existing
  `require_admin` in `backend/recaps/service.py` unchanged).

---

## 7. Design system (P-2)

- `frontend/src/ui/` primitives, shadcn-style (copy-in components on
  Tailwind 4, no runtime dep): `Card`, `Table` (editorial + dense variants —
  dense = sticky first columns like `StandingsTab`), `StateBlock`
  (loading/empty/error/stale in one component, used by every page), `Badge`
  (incl. existing `AiTakeBadge`, new `StaleBadge`), `Sheet`/`Dialog`,
  `Skeleton`, `Stat`.
- Tokens: formalize the `pg-*` palette; type scale with a display face for
  editorial headlines; fix the slate-on-slate contrast failures
  (`text-slate-600` on dark backgrounds) as part of the pass. Dark-first
  stays; no light mode in the P-series.
- **Accent + radius consolidation (measured, not hypothetical):** the Draft
  Room leans emerald, In-Season mixes red and emerald, the newsroom is red;
  corner radii span `rounded-md/-lg/-xl/-full` with no rule. Define one
  semantic accent scale (brand accent = the newsroom red; emerald reserved
  for positive deltas/wins, red-negative for losses — never both as page
  themes) and a two-step radius scale. P-2's re-cut tabs adopt it; the
  P-7 decompositions finish the sweep.
- **Recharts** added; first consumers: power-ranking movement sparklines and
  category-margin bars in matchup detail.
- `formatApiError` (`frontend/src/api.ts`) splits user-facing copy from dev
  detail: production users never see "run uvicorn"; dev builds keep the
  helpful version (`import.meta.env.DEV` switch).
- Definition of done for P-2: `StandingsTab` and `PowerRankingsTab` are
  re-cut on the primitives with zero visual regression, proving the kit
  before the monoliths migrate.

---

## 8. Screen deltas (P-6, P-7)

- **League Home (new, P-6):** above the fold — your matchup card (live
  9-cat tally, GP context from the Catalyst work), week context; below —
  top-3 ranking movers (sparklines), latest published recap card,
  transaction ticker (5 most recent). Composition of existing components +
  snapshot reads; the only new data need is "which team is *mine*" —
  `league_memberships` gains nullable `team_name` claimed in Settings.
- **Matchup detail (P-7):** `MatchupsTab`'s expandable card promoted to a
  route; adds win-probability strip and category-margin chart. The
  InSeason page's projection/commentary tools fold in behind tabs.
- **Draft Room decomposition (P-7, mechanical not redesign):** split
  `DraftPage.tsx` into `draft/Board`, `draft/PlanRail`,
  `draft/ControlsSheet`; solver knobs (percentile, time limit, value
  source) move into an "Advanced" sheet. Same for `InSeason.tsx` — and it
  comes *off* the CI lint ignore list as the completion criterion.
- **Newsroom:** untouched except the route rename and shared-component
  extraction for `/standings`.

---

## 9. Streamlit retirement (P-1)

- Tag `legacy-streamlit` at the pre-deletion commit; delete `app.py`;
  remove `streamlit` + Streamlit-only deps from `requirements.txt`; purge
  README/docs references (`BACKEND_RESTRUCTURE.md` mention included);
  update dossier §01 disposition to "Retired (tag `legacy-streamlit`)".
- Pre-deletion audit ticket: diff `app.py` capabilities against the React
  app. Known candidates for porting (verify, don't assume): projections
  upload ergonomics on the In-Season tab; any CSV export conveniences.
  Anything found becomes a backlog item, not a deletion blocker.

---

## 10. PR sequence

| PR | Scope | Depends on | Done when |
|---|---|---|---|
| **P-1** | Streamlit retirement (§9) | — | `app.py` gone; deps pruned; docs updated; audit ticket filed |
| **P-2** | Design system: `ui/` primitives, tokens, StateBlock, error-copy split, Recharts; StandingsTab + PowerRankingsTab re-cut | — | Both tabs on primitives, `npx eslint .` clean, no visual regression |
| **P-3** | Snapshot worker + `league_state_snapshots` + read-path inversion (§3) | — | §3.5 criteria all green in production logs |
| **P-4** | Multi-league config: creds → `leagues` rows, kill module constants, seed script (§4) | P-3 | No `config.LEAGUE_ID` references outside the seed script; worker iterates DB rows |
| **P-5** | Auth surfaces: AuthProvider, /login, /signup (invite-gated), profile menu (§6) | P-2 | Login lives at /login; WeeklyRecapTab consumes context; recap admin flow unchanged |
| **P-6** | IA re-root + League Home + league picker (§5, §8) | P-2, P-3, P-5 | New default route; old routes redirect; Home < 1 s from snapshots; zero manual load buttons on Home (D-P6) |
| **P-7** | Monolith decomposition: DraftPage + InSeason splits, matchup detail route (§8) | P-2, P-6 | `InSeason.tsx` off the CI ignore list; no file in `pages/` > 500 lines; all read surfaces auto-load (D-P6 complete) |
| **P-8** | Landing page + F2-7 OG/prerender (existing plan, unblocked here) | P-6 | Logged-out `/` renders static landing; recap URLs unfurl in WhatsApp |

P-1 and P-2 can run in parallel. P-3 is the critical path. One PR each,
reviewed like the F2 series; addenda to this spec for anything discovered
mid-build.

---

## 11. Test plan expectations

- P-3: worker unit tests (phase isolation, upsert semantics, secret guard),
  endpoint tests asserting zero ESPN calls on the read path (assert the
  gateway is never invoked — patch `espn_get`), staleness surfacing.
- P-4: seed-script idempotency; per-league credential resolution;
  regression on the full recap generation flow for Patriot Games.
- P-5/P-6: route redirects, auth-gated rendering, League Home composition
  with empty snapshots (preseason state).
- Frontend CI gains a bundle-size budget check in P-2 (fail > 1 MB gz) —
  the app currently ships one 795 kB chunk; the split pages in P-7 should
  bring route-level code-splitting.

---

## 12. Risks

- **ESPN ToS/fragility remains risk #1** — unchanged by this spec, but P-3
  reduces blast radius (stale ≠ down) and P-4 contains it per league.
  A commercial-launch decision must revisit this explicitly before charging
  money.
- **P-3 touches every read surface.** Mitigation: endpoints keep URLs and
  shapes, so the frontend diff is additive (`fetched_at` handling only);
  the worker can run in shadow mode (writing snapshots while reads stay
  live) for a week before the read-path flip.
- **Route renames break bookmarks/share links.** Mitigation: redirects kept
  for a full season; published recap URLs (the shareable ones) keep working
  via redirect permanently.
- **Scope creep toward payments/onboarding.** D-P4 exists to prevent it;
  anything subscription-shaped is an addendum after the P-series ships.

---

## 13. Non-goals for the P-series

- Payments, subscription tiers, usage limits (D-P4).
- Self-serve league connection UI (§4 non-goal).
- Yahoo/Sleeper adapters, own projection model (dossier Bench).
- Light mode, native mobile wrapper.
- Public self-serve signup (invite-gated only until launch decision).
- Bot delivery of recaps (existing future phase, unchanged).

---

## Addendum: disposition of the second-opinion review (2026-07-16)

Patrick commissioned an independent AI review of the same scope and asked
for its findings to be folded in by judgment. Its full text lives outside
the repo; the disposition of every substantive point:

**Adopted into this spec:**
- *"Everything requires manual button clicks — it's an API testing tool,
  not a dashboard."* Correct, and previously under-weighted here. Now
  **D-P6** (auto-loading reads), wired into P-6/P-7 completion criteria.
  Root cause is architectural (reads used to be expensive live ESPN calls),
  which is why D-P6 depends on P-3, not on UI willpower.
- *Visual inconsistency across pages.* Directionally correct (its specifics
  were off — the Draft Room's accent is emerald, not amber). Verified
  against the code: emerald vs red page accents, four corner radii in use.
  Now an explicit accent/radius consolidation item in §7.
- *A "my leagues" surface for multi-league accounts.* Adopted as the
  logged-in `/` league-picker in §5 (P-6) rather than a separate `/app`
  route — one page fewer, same capability.

**Considered and rejected:**
- *Port the frontend to Next.js.* Rejected; reasoning and a concrete
  revisit trigger recorded inline at **D-P2**. Its own migration table
  concedes the backend, database, API client, and components all survive
  unchanged — meaning the port buys plumbing, not product, at this stage.
- *Replace top/bottom nav with a sidebar.* Rejected: a five-destination
  consumer app on mobile wants bottom tabs (the native pattern already
  in place); sidebars fit dense multi-section SaaS, which this is not.
- *League-connect UI (ESPN cookie capture) in the first five actions.*
  Stays a §4/§13 non-goal: it's the hardest UX in the product and gates
  nothing in the P-series, since rows are seeded by script until the
  public-launch decision. Building it first would front-load the riskiest
  work for zero current users.

**Already convergent (no change needed):** retire Streamlit; league
dashboard as the hub ("the page users see 90% of the time"); league-scoped
URLs; shadcn-style components + Recharts; preserve the entire backend;
auth before dashboard. Two independent reviews landing on the same
skeleton is decent evidence the skeleton is right.
