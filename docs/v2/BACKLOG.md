# V2 Backlog

**The single source of what is next.** Claude maintains this; Aisha reads it
and never edits it. Process: [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Exactly one item carries `**NEXT**`. That is the only thing being worked on.

| Status | Meaning |
|---|---|
| `[x]` | Merged into `v2`, commit noted |
| `[ ]` | Not started |
| **NEXT** | Assigned or ready to assign |
| `BLOCKED` | Cannot proceed; reason stated |

---

## Slice 1 — the vertical slice

Charter §11.6: *user → manager → league → season → ESPN sync → canonical
teams/players/matchup periods → one shared league page*, **with tenancy from
day one** (Decision 26).

Port list source: [`V1_CLASSIFICATION.md`](V1_CLASSIFICATION.md) §9.

**Slice 1 is closed as of S1-11c** (charter work-plan item 6). S1-11d remains
optional and unscoped — the last UX gap (reaching a league without an
out-of-band ID), not required for the slice to stand.

- [x] **S1-01 · Pure domain layer** — `244c750`
  Categories, all-play scoring, standings fold, name normalisation. 53 domain
  tests + 5 architecture tests. Ports classification §9 items 2, 3, 4, 6, 7, 9.

- [x] **S1-02 · ESPN transport gateway** — `db9cdfe`
  Port V1's `backend/league/gateway.py` into `backend/providers/espn/client.py`.
  Explicit connect/read timeouts, typed `ESPNTimeoutError` / `ESPNUnavailableError`,
  504/502/500 mapping, and the namespace-scoped patch that must not mutate the
  shared `requests` module. Carries 12 invariants from the register (§7
  "Transport policy"). No domain dependency, no database — pure transport.
  *Charter: §7 (adapters, not the domain model), D28 (failures are visible).*

- [x] **S1-03 · Live check: `matchupPeriods`** — `df36507`
  The one unresolved unknown in the design. Against a real ESPN basketball
  league, confirm `settings.matchup_periods` is populated, capture its exact
  shape and key types, and check how playoff/championship periods and the
  All-Star break appear. Record the payload as a test fixture.
  **Small, and it gates S1-06.** If periods cannot be derived, the finality
  model has no input and the schema needs revisiting.
  *See [`PROVIDER_INGESTION_DESIGN.md`](PROVIDER_INGESTION_DESIGN.md) headline finding.*

- [x] **S1-04 · Persistence foundation** — `066579c`
  SQLAlchemy 2.0 typed models, Alembic, `backend/platform/db.py`, settings
  loading, test database via a CI service container. No tables yet beyond what
  S1-05 needs. Migrations must apply *and roll back* in CI.
  *Charter: D23, D20 (correctness before performance).*

- [x] **S1-05 · Identity + tenancy** — `30b5778`
  `users`, `managers`, `manager_user_links`. Local JWKS token verification —
  no per-request round trip. `LeagueScope` / `UserScope` that repositories
  **cannot be constructed without**, plus the route-policy matrix test that
  fails CI on any undeclared route.
  **This is the bite that makes charter D26 real.** V1's 53 unauthenticated
  routes were 53 forgettings; structure prevents it, discipline does not.
  *Charter: D2, D9, D12, D13, D26; non-negotiable #1.*
  *Schema: [`schema/01-identity.md`](schema/01-identity.md).*

- [x] **S1-06 · Fantasy core schema** — `cb97031` — depends on S1-03
  `leagues`, `league_seasons`, `categories`,
  `league_season_categories`, `fantasy_teams`, `fantasy_team_seasons`,
  `matchup_periods` with `status` finality. Periods derived from the provider,
  never hand-typed.
  *Charter: D8, D11, D14, D15; non-negotiable "no hardcoded season calendars".*
  *Schema: [`schema/02-fantasy.md`](schema/02-fantasy.md).*

- [x] **S1-07 · ESPN adapter + DTOs** — `5b51c44` — depends on S1-02, S1-06
  `fetch_settings`, `fetch_teams`, `fetch_periods` returning FCP DTOs.
  Provider objects must not escape the package, and **no subclassing of
  `espn_api.League`** — that is the §7 violation V1 built its domain on.
  *Schema: [`schema/04-provider-ingestion.md`](schema/04-provider-ingestion.md).*

- [x] **S1-08 · Ingestion pipeline** — `403cc1a` — depends on S1-07
  `ingestion_runs`, `raw_payloads` with `content_hash` dedupe, normalizer
  versioning, lineage columns on canonical rows, `partial` as a real run
  outcome. Persist before interpret, so replay works.
  *Charter: D16, D17, D28.*

- [x] **S1-09 · Player identity crosswalk** — `d162ad5` — depends on S1-08
  `players`, `provider_identities`, `identity_links`,
  `identity_review_queue`. The one resolution ladder from
  `schema/04`, wired to `domain/names.py`. An unmatched name is queued and
  counted, never dropped.
  *Charter: D18, D19; non-negotiable "no fuzzy-name identity".*

- [x] **S1-10a · Matchups persistence + sync** — `86488de` — depends on S1-06, S1-09
  `matchups` + `matchup_category_results` (`0008`) + `matchup_result` enum;
  `ProviderLineageMixin` (full lineage); `ESPNAdapter.fetch_scoreboard` +
  `ScoreboardDTO` family; `MatchupSyncService.sync_league_final_periods`
  (fetch → normalize → supersede/persist, idempotent). Supersession via a
  partial unique index (`uq_matchups_live_slot WHERE superseded_at IS NULL`);
  `computed_result`/`provider_result` separate with `result_source`.
  *Charter: D10, D11, D20.*

- [x] **S1-10b · Standings read path** — `90cfc0f` — depends on S1-10a
  `StandingsReadService.standings` (fold `final` matchups + category rows, no
  re-tally), freshness envelope `{data, as_of, freshness="final", stale}`,
  `GET /api/v1/leagues/{league_season_id}/standings` (`LEAGUE_SCOPED` +
  membership), read repos (`live_for_season`, `category_results_for`,
  `teams`), `LeagueMembershipRepository.is_member`.
  *Charter: D10, D11, D20.*

- [x] **S1-11a · Frontend foundation** — `0ff1059`
  `frontend/` scaffold (React 19 + Vite + TS + Tailwind + TanStack Query +
  router); generated API client (`openapi-typescript` + `openapi-fetch` from a
  committed `openapi.json` snapshot, CI drift-gated); dev auth token shim; one
  real `/me` vertical slice. npm (not pnpm) + TS ^5.

- [x] **S1-11b · League page (standings)** — `10f1a90` — depends on S1-11a
  `/leagues/:leagueSeasonId` route rendering the standings table (server
  order, no client-side re-sort) with the full state mapping (loading /
  403-404 combined non-leaking copy / generic error / not-synced / empty /
  rows + stale banner), basketball `win_pct` formatting, "Final through
  {as_of}" footer. Frontend only.

- [x] **S1-11c · Periods endpoint + selector** — `46f67c9`
  Backend GET .../periods (LEAGUE_SCOPED) returns every period ordinal-ordered
  (provider_period_id and finalized_at excluded); a selector offers only final
  periods (non-final disabled) + "Full season" default; through_period joins
  the standings query key; H-01's complete/unknown_category_count are now
  rendered. Slice 1 is closed.
  *Charter: §11.6, §10, D26.*

- [ ] **S1-11d · Reach a league (optional)** — depends on S1-11b
  `GET /me/leagues` + a home route to list the user's memberships so a league
  can be reached without an out-of-band ID.

---

## Demo path — getting a real league on screen

**The write path does not exist.** Four GET endpoints, zero writes, and nothing
in `backend/` has ever created a league, team or period — every row so far came
from a test fixture. Slice 1 proved the read path; this section builds the
half that feeds it, so Patrick can look at his own league.

Prioritised over the remaining hardening by Patrick, 23 Aug. H-05b/c, H-06 and
H-09/H-10 are structural with no live holes, so nothing degrades while they
wait.

- [x] **D-01 · League bootstrap service** — `f89fda1`
  The first write path: settings → league + league_season +
  `league_season_categories`, teams → franchises + team-seasons + managers
  (unclaimed — D13; the require_league_member chain now has its middle rows),
  periods → matchup_periods (scheduled-only). Adapter extended for league name
  (lowercase slug), scoring categories (D11 — no NINE_CAT default), and team
  owners (matched by provider owner id, never name). Wrapped in run_scope (H-03),
  idempotent by natural key; an unmapped category finishes the run partial.
  *Charter: D9, D11, D13, D16, D17, D28.*

- [x] **D-02 · Period finality producer** — `087ea08` — depends on D-01 — *was H-07*
  finalize_eligible_periods is the single code path that writes
  matchup_periods.status='final' (48h named grace, league timezone,
  commit-per-period for resumability). Already-final periods are never
  refetched; a break finalizes with zero matchups and is not partial; missing
  categories finalize and mark the run partial. sync_league_final_periods is
  renamed resync_final_periods and is repair-only — it never touches status.
  End-to-end bootstrap → finalize → standings now returns a populated table.
  *Charter: D10, D20, D28.*

- [x] **D-03 · Sync CLI + claim** — `f75797a` — depends on D-01, D-02
  scripts/sync_league.py: bootstrap → finalize → claim → summary. Credentials
  from env only (never argv; --espn-s2 rejected by test); claim finds an
  existing user by --claim-email and never creates one; --claim-team omitted
  or unknown lists teams and exits non-zero. Prints the league_season_id URL
  (S1-11d not built) and reports run statuses honestly. This closes the demo
  path.
  *Charter: D13, D28.*

The demo path is done; remaining hardening is H-05b/c, H-06, H-08, H-09,
H-10, and open question #6 still owes its own S1-03-shaped probe.

- [x] **D-04 · Local runbook — make it actually runnable** — `abb78e8` — depends on D-03
  docs/v2/RUNBOOK.md: clone → running app, written by running it (not reading
  code). Fixed three repo defects — .env.example gained the three SUPABASE_*
  names (no values), CONTRIBUTING.md pinned python3.12 + the correct
  `uvicorn … --factory` command, and a V2 docker-compose.yml runs postgres:16.
  The live ESPN step is Patrick-supplied; the pipeline is verified against a
  fake adapter. Surfaced two auth findings (no JWKS/session wiring; RS256-only
  vs Supabase ES256) — see the new item below.

---

## Slice 1 hardening — from the red-team triage

Confirmed implementation gaps against a design that already says the right
thing. Source: [`research/REDTEAM_TRIAGE.md`](research/REDTEAM_TRIAGE.md),
each verified against the code before landing here. Ordered by severity;
H-01 and H-02 are correctness bugs in shipped code.

- [x] **H-01 · Unknown is not a tie** — `37c4236` — the non-negotiable violation
  Added an explicit UNKNOWN to the domain result vocabulary; compare() returns
  UNKNOWN (not TIE) for None/NaN; tally() returns a 4-tuple; sync persists
  result=NULL (the column was already nullable); the standings fold excludes
  unknown categories from W/L/T and win_pct; the API envelope surfaces
  complete + unknown_category_count. Completeness is derived, not a status.
  *Charter: D28, §10.*

- [x] **H-02 · Conflicting birthdate must not auto-link** — `471c7ff`
  exact is now partitioned into exact_ok (eligible) and exact_conflict (a
  two-sided birthdate disagreement). exact_ok==1 auto-links; exact_ok>1 queues
  ambiguous; an empty exact_ok with a non-empty exact_conflict queues
  dob_conflict carrying the conflicting candidate's entity id as evidence. A
  candidate with birthdate=None is missing evidence, not contradiction, and
  stays eligible. No migration, no confidence changes.
  *Charter: D18 (prefer unknown over confidently wrong).*

- [x] **H-03 · Runs must always reach a terminal state** — `b1c8a87`
  Added IngestionService.run_scope, a lifecycle context manager that commits
  the run 'running' at entry (durable immediately, survives rollback), stamps
  'failed' with a bounded error and re-raises the original exception on
  failure, and commits a terminal status on normal exit (backstopping to
  'succeeded'). MatchupSyncService now drives sync through run_scope and
  stamps 'partial' when any category outcome is NULL (a bye is never
  partial). One run owner today; the next owner inherits the guarantee.
  *Charter: D28 — job outcomes are queryable data, not log lines.*

- [x] **H-04a · Bind league repositories to a scope** — `8127b84`
  Added LeagueSeasonScope + LeagueSeasonScopedRepository; bound both league
  repos to (scope, session) with every read scope-filtered (category_results_for
  joins through matchups rather than trusting ids). get_standings_service now
  depends on require_league_member — the one commented cross-scope exception —
  so the service cannot be wired without passing the membership gate. LeagueScope
  kept for franchise-level fantasy_teams. No API contract change, no migration.
  *Charter: D26, non-negotiable #1.*

- [x] **H-04b · Make route policy executable** — `6db6b7f`
  The matrix test now walks each route's transitive dependency graph and
  fails when a policy's required dependency is absent; the policy→dependency
  map is total over RoutePolicy (MANAGER_PRIVATE → a no-enforcement sentinel,
  so a policy the harness cannot enforce fails CI rather than shipping a
  label). Map lives in the test; policy.py stays a pure declaration module.
  Test-and-docstring only — no route or API change.
  *Charter: D26 — which names a test as the mechanism; non-negotiable #1.*

- [x] **H-05a · Additive schema constraints** — `0f6b918`
  Four additive constraints in one migration: partial unique indexes for
  name-only provider_identities and one-open-review-per-identity,
  0 <= confidence <= 1, and (status='final') = (finalized_at IS NOT NULL)
  as an equivalence. resolve_and_link now inserts inside begin_nested() and
  re-reads the winner on IntegrityError — the indexes don't trade a data bug
  for an availability bug. Migration applies and rolls back; four test seeds
  were fixed (not weakened) to seed finalized_at.

- [ ] **H-05b · Cross-league composite keys** — depends on H-05a — *waits on H-11*
  `matchups` carries four independent FKs with nothing tying the period and
  both team-seasons to the claimed `league_season_id`, so one row can span
  three leagues with every FK valid. `fantasy_team_seasons` has the same gap
  (confirmed): a League-A franchise can bind to a League-B season. Fix with
  composite keys — unique `(id, league_season_id)` on the parents, referenced
  as a pair from the children. Structural: it rewrites existing FKs, which is
  why it is not in H-05a.

- [ ] **H-05c · Polymorphic identity-link target** — depends on H-05b
  `identity_links.fcp_entity_id` has no FK at all: a link can name
  `fcp_entity_kind='player'` and point at any UUID, or at a manager or team.
  **This needs a design decision before it is a bite** — typed link tables per
  entity kind, or a canonical-entity supertable every identity-bearing table
  references. Not a constraint that can simply be added, which is why it is
  carved out of H-05 rather than buried in it.

- [ ] **H-11 · Wire Supabase auth end-to-end** — **NEXT** — found by D-04
  **Decided (Patrick, 23 Aug): V2 reuses V1's existing Supabase project**
  (ref in `docs/DEPLOY.md`), not a new one — so this wires against that
  project, and its signing algorithm is a fact to read off it, not a choice.
  create_app(keyset=…, session_factory=…) takes the JWKS and session as
  injectable test params, but nothing loads the JWKS from SUPABASE_JWKS_URL or
  builds the session from DATABASE_URL — so uvicorn --factory yields
  jwks_keyset=None and every authenticated route 500s. Also: platform/auth.py
  verifies RS256 only, but Supabase signs ES256 (P-256), so a real token 401s
  even once the JWKS is wired. Add a real entry point (load JWKS + build
  session) and ES256 support; no mock verifier / bypass / skip-JWKS-in-dev.
  Two independent defects, both required for one successful request: no
  production entry point, and a verifier that accepts only RS256. **The
  algorithm must come from the trusted keyset, never the token header** —
  taking `alg` from the header is the classic confusion attack. Allowlist is
  RS256 + ES256; never HS256, never `none`. JWKS rotation is deliberately out
  of scope and filed as a follow-up.
  Scoped: [`docs/tickets/H-11-wire-supabase-auth.md`](../tickets/H-11-wire-supabase-auth.md).

- [ ] **H-06 · Wire payload dedupe, or delete the claim**
  `find_by_hash` and `latest_for` have zero callers; `record_payload` always
  inserts. Either wire dedupe in — first widening the key, which is
  `(provider_id, endpoint, content_hash)` where endpoint is
  `scoreboard/{espn_period_id}` and therefore collides across leagues — or
  remove the methods and their docstrings. A documented guarantee nothing
  calls is worse than an absent one.

- [ ] **H-07 · Finality needs a producer** — **moved to the demo path as D-02**
  Nothing in the codebase writes `matchup_periods.status = 'final'`. The
  design makes finality the linchpin of sync cost and standings correctness,
  and it is currently an input nobody produces. Build `finalize_period` as the
  single transactional owner of that transition: last authoritative fetch →
  persist → supersede → set `status`/`finalized_at` together. Then rename
  `sync_league_final_periods`, whose docstring claims to be the sync while
  behaving as a backfill.

- [ ] **H-08 · Test the interleavings, not the sunny path** — depends on H-07
  Postgres tests for: exception after the first supersession flush (one live
  row must survive), two concurrent changed syncs, and run-status on failure.
  Add per-league serialisation (advisory lock or `SELECT ... FOR UPDATE`) when
  the scheduler lands — the race is unreachable today because nothing
  schedules the sync.

- [ ] **H-09 · All-play scoring still conflates unknown with a tie**
  domain/scoring.py all_play_week funnels Result.UNKNOWN into its else -> ties
  branch. No live caller today (test-only domain module), so latent, but it is
  the same null->tie shape H-01 killed in standings. Fix before any all-play
  surface is wired.
  *Charter: §10.*

- [ ] **H-10 · A wrong identity link must be correctable** — depends on H-02
  `IdentityLinkRepository` exposes only `add()` and `find_active()`, and
  `resolve_and_link` returns an active link unchanged without re-evaluating
  evidence — so a wrong link is permanent and authoritative, while the repo
  docstring claims "a wrong link is superseded, never deleted". Add the
  correction path it promises: supersede the active link, record the verifier
  and evidence, create the replacement, and re-resolve the canonical facts
  that depended on it. H-02 stops new wrong links; this repairs the ones
  already written.
  *Charter: D19 — a permanent crosswalk is not the same as an immutable one.*

---

## Slice 2 and beyond — not yet cut

Deliberately unscoped. Cutting bites for work that far out invents detail we
do not have, and charter §22 warns against building for architectural
completeness.

Known to come, roughly in order:

- Historical event capture — **starts early**; daily roster snapshots cannot be
  backfilled, so every day not captured is gone (charter D10, §11.7).
  *Sequencing is contingent on open question 6 — the "cannot be backfilled"
  premise is under challenge and not yet re-verified.*
- Projections: sources, immutable sets, adjustments, freezes (D22, D24, D29).
- The gated port: optimizer, plan diversity, MC targets, Forge Value —
  **only behind a committed synthetic fixture and characterization tests**
  (classification §6).
- Story domain: story facts, editions, timeline, records, rivalries (D13, D30).
  Surfaces to users as the **Newsroom** — see D30 for which word goes where.
- FCP projection model (D6).

---

## Open questions that block future bites

| # | Question | Blocks |
|---|---|---|
| 1 | Does `matchupPeriods` cover playoff/championship periods, and how does the All-Star break appear? — resolved S1-03 | S1-06 |
| 2 | ~~Roster fetch cost — one request per team per day, or one league-wide call?~~ **Resolved: one league-wide call.** `mRoster` returns every team under `teams[].roster.entries[]`; V1 measured the whole 14-team league in a single request. Cost is per-league, not per-team. See [`research/ESPN_ROSTER_API.md`](research/ESPN_ROSTER_API.md). | ~~Historical capture~~ |
| 6 | **Is historical lineup state actually recoverable?** Two candidate paths challenge the design's "a day not captured is gone permanently": (a) `rosterForCurrentScoringPeriod` inside the `mMatchupScore`/`mScoreboard` payload for a past period; (b) `mTransactions2` `FUTURE_ROSTER` records, which carry source/destination lineup slot + process date — V1 backfilled 21 weeks of them. If either works, daily capture is recoverable rather than capture-or-lose-forever, and historical capture does not have to lead Slice 2. **Live check, S1-03-shaped.** Until it answers, the daily-capture design stands unchanged — the asymmetry favours over-capturing. | Historical capture sequencing |
| 3 | ~~Story vocabulary: newsroom / recap / story / timeline. Pick one for tables, API and UI.~~ **Resolved — charter Decision 30**, ratified 22 Aug 2026. They are a hierarchy: Story = domain, Newsroom = surface, Recap = weekly artifact, Timeline = the feature. Never "newsroom" for the domain, never "story" in UI copy. | ~~Newsroom slice~~ |
| 4 | Self-delivering recaps — absent from the charter by omission, not decision. Product call needed. | Newsroom slice |
| 5 | ~~Adjustment composition: does raising projected minutes scale dependent rate stats?~~ **Resolved — charter Decision 29**, ratified 22 Aug 2026. Volume scales, efficiency does not; `games` and `minutes_per_game` compose at different levels; `absolute` is the default mode. Normative rule in [`schema/05-projections.md`](schema/05-projections.md) §Composition rule. | ~~Projections slice~~ |

---

*Claude updates this on approval. Last change: H-11 scoped — the last gap
between the demo path and a logged-in page.*
