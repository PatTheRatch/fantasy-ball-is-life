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

## First-run blockers — found running it for real

Confirmed against the code, not reported second-hand.

- [ ] **D-05 · Nothing seeds `nba_seasons`**
  `league_bootstrap.py:197` raises `BootstrapError("no nba_seasons row for
  season_year …")` and **no migration ever creates one** — `0004` seeds
  categories, nothing seeds seasons. So the CLI fails on its first real run.
  This is a missing producer of exactly the shape D-02 fixed for finality, and
  it is a gap in D-01's scope (mine, not Aisha's). Charter D14 says FCP owns
  canonical NBA seasons; decide whether they are seeded by migration, derived
  from the provider's pro schedule, or created by the bootstrap itself.
  **Blocks the demo.**

- [ ] **D-06 · There is no login flow, and tokens expire**
  S1-11a deferred "the full Supabase auth flow" to a later bite and that bite
  was never cut. Signing in currently means: curl Supabase Auth, copy the
  access token, `localStorage.setItem("fcp.devToken", …)`, refresh. The token
  is ES256-signed with ~1h expiry, so **this is not one-time setup — it recurs
  every hour**. Fine for a scripted test, not fine for the product owner
  looking at his own league. Minimum viable: a token-mint helper. Proper: the
  real sign-in flow.
  *Not a bug — the auth gate works. A missing feature on the critical path.*

- [ ] **D-07 · ESPN scoreboard mapping** — *Aisha's finding, unverified here*
  Flagged during the first real run; needs her description before scoping.

---

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

- [ ] **H-05b · Cross-league composite keys** — depends on H-05a
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

- [x] **H-11 · Wire Supabase auth end-to-end** — `e8e734f` — found by D-04
  create_app() loads the JWKS from SUPABASE_JWKS_URL and builds the session
  from DATABASE_URL by default (runbook's uvicorn --factory command unchanged);
  load_from_env=False keeps the matrix test network-free; missing config or a
  failed fetch fails fast at construction (typed JwksFetchError, 5s timeout).
  The verifier accepts ES256 (P-256) + RS256, dispatching on the JWK's kty; the
  algorithm comes from the trusted keyset, never the token header (HS256/none
  rejected; confusion test included). RUNBOOK §6 is now working instructions.
  JWKS rotation stays out of scope (follow-up: bounded refetch on UnknownKey).

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

## Gated port — projections, optimizer, and draft engine

Classification [`V1_CLASSIFICATION.md`](V1_CLASSIFICATION.md) §6: the draft
optimizer, plan diversity, MC targets, and Forge Value are EXTRACT-marked but
had zero CI coverage — twenty tests skipped on a gitignored `.xls` file
nothing could commit. This section is that gate, opened one bite at a time.

**Standing note — orphaned-branch sweep.** `scripts/orphan_sweep.sh` runs
weekly (cron) hunting for work nobody owns. Disposition rule: carry the
*idea* forward into a new bite here, never reland an orphaned commit
directly — its target paths are frequently V1-era and no longer exist on
`v2`. Verify a path exists on `v2` before citing an orphaned commit as a
reference.

- [x] **D-08 · Synthetic projection fixture** — `7847ba2`
  ~200-player deterministic generator
  (`tests/fixtures/projections/build_synthetic.py`, seed 20260) producing
  `synthetic_projections.csv` (200 rows, digest `a75f7b12d06c1280`), plus
  `v1_adapter.py` (canonical -> V1 columns) and 28 tests in
  `test_synthetic_fixture.py`. Un-skips the twenty CI-skipped tests
  classification §6 flagged. Also fixed a `.gitignore` defect: the bare
  `*.csv` rule was silently excluding the fixture, breaking CI on the first
  push — negated with `!tests/fixtures/projections/*.csv`.
  Review went CHANGES_REQUESTED -> APPROVED_WITH_FINDINGS; the MED finding
  changed the deliverable from a written file to **injection**
  (`to_v1_columns()` -> a DataFrame), because `BBM_PROJECTIONS_PATH` is a
  hardcoded, non-overridable constant and V1's fallback is `pd.read_excel`.
  V2 depends on neither `pandas` nor `openpyxl`.
  Gate on merged `v2`: 266 passed, 61 skipped, ruff clean, mypy clean
  (60 files).
  *Classification: §6 item 1.*

- [x] **D-09 · Characterization oracle + solver-cap semantics** — `2cb1eb0`, `dc64104` — depends on D-08
  Delivered more than scoped: the recon half falsified part of D-08's own
  claim before any golden could be captured. D-08's 30 tests check the
  fixture's *structure*, not whether it can actually drive V1 — and it
  couldn't, for three reasons invisible to those tests: no players priced at
  exactly $1 (the LP's `minimum_value_players` constraint is an equality,
  and the ladder decayed to $1.67 and never hit floor); guards labelled
  `'G'` against V1's `str.contains` vocabulary of `(C, PG, SG, SF, PF)`,
  leaving PG with zero eligible players; and V1 matching positions in two
  places with different rules (`_validate_pool_feasibility` uses
  `str.contains` for all five including C, the LP constraint uses
  `Pos == 'C'` capped at 3 plus `str.contains` for the rest — they agree for
  this vocabulary but would diverge for a label like `"C PF"`). All three
  fixed in the fixture. Also discovered: `OptimizeLineup` takes two
  injection args and `projections_rows` (a list) takes *precedence* over
  `projections_df` — `projections_rows` is the V2 consumer shape and is what
  D-12 must feed; and construction additionally requires a `league` object
  reading `self.league.draft`, sourced from a live 4-request ESPN fetch, so
  any oracle harness must stub the network.
  Capture half: `tests/oracle/d09_goldens.json` is the committed record — 7
  of 9 categories solve (PTS 744.275/cost 199.58, REB 381.78, AST 180.25,
  STL 50.715, BLK 55.23, 3PM 102.48, TO -39.795); FG%/FT% raise `KeyError`
  on a missing `'{cat} PW'` column (V1 can constrain a percentage but never
  maximize one, and nothing in its own tests/CLI/API ever asks it to) —
  recorded as UNDECIDED, not reproduced as a requirement; that call is
  pushed to D-12. `tests/oracle/capture_goldens.py` is the harness that
  produced the record, committed and opt-in via a `capture` pytest marker
  gated on `D09_V1_ROOT` — its presence is load-bearing, since without it
  the goldens would be unfalsifiable magic numbers. `test_goldens_record.py`
  (12 tests, no V1 import) runs in normal CI; `test_solver_cap_contract.py`
  (6 tests, capture-marked) characterizes all four `SOLVER_TIME_LIMIT_SECONDS=8`
  branches (user-limit-no-incumbent, any non-accepted status, user-limit
  with a wrong-length incumbent, user-limit with a correct-length incumbent)
  as deterministic branch behaviour rather than a numeric golden, since which
  incumbent HiGHS holds at a wall clock depends on CPU/solver/BLAS.
  `pyproject.toml`: `addopts = "-q -m 'not capture'"`.
  Gate on merged `v2`: 280 passed, 61 skipped, 6 deselected, ruff clean,
  mypy clean.
  *Classification: §6 items 2–3.*

- [ ] **D-10 · Forge Value port** (`backend/draft/values.py`) — **NEXT** — depends on D-09
  Least-trusted of the four gated items: Forge Value has **no V1 test file
  at all**, so D-09's golden is its only coverage.
  *Classification: §6 item 4, §7.*

- [ ] **D-11 · MC category targets port** (`targets_mc.py`) — depends on D-09

- [ ] **D-12 · Optimizer / solver port** (`optimizer.py` + `engine.py` solver glue) — depends on D-10, D-11
  Must assert the solver-cap feasibility contract D-09 pinned — a timeout
  and an infeasible solve are not the same outcome.
  **FG%/FT% call (D-09 left this open, deciding it is now in scope):**
  percentages are out of scope for this port; note the `KeyError` gap as
  inherited from V1, not a regression to fix or a behaviour to reproduce —
  V1 itself never maximizes a percentage category anywhere in its own
  tests, CLI, or API.
  **Bundle requirements, from D-09's review:**
  - All 9 categories in the golden comparison, not a sample — different
    categories bind different constraints, so a subset can pass while a
    real regression hides in the categories left out.
  - The constants D-09 pinned as data, not tuning knobs: `roster_size` 13,
    `initial_budget` 200, `minimum_value_players` 3,
    `minimum_game_threshold` 20, `value_col` `'$'`,
    `SOLVER_TIME_LIMIT_SECONDS` 8.
  - Capture via the `projections_rows` path explicitly — it takes
    precedence over `projections_df`, and `projections_rows` is the shape
    V2 actually produces.
  - The frozen league/draft state D-09 stubbed (`draft=[]`, `teams=[]`) is
    part of the contract, not an incidental test detail.
  - A float tolerance policy: `rel=1e-6` on the objective value, exact
    equality on roster membership.
  - The dependency version manifest D-09 captured (`cvxpy 1.9.2` etc.) so a
    future mismatch triages as version drift, not a port bug.
  - **Open question for D-12 to resolve:** roster uniqueness under
    degeneracy. The optimal *value* is well-defined but the optimal
    *roster* need not be — a different HiGHS/BLAS build could return a
    different, equally-optimal 13-man set with the same objective, which
    would break exact membership equality. Decide whether
    objective-equality is the actual contract and membership stays
    informational-only.
  - The oracle's objective *magnitudes* are pinned only for PTS/REB (a weak
    "> budget" floor, not an exact-value assertion) — a hand-edit of, say,
    AST 180.25 → 175.0 would survive the record suite as written. The
    magnitudes are trustworthy because they were captured against real V1,
    not because the suite verifies them independently. Do not ask D-12 to
    close this by recomputing the weighting inside the test — that
    duplicates V1's own logic and is exactly the drift the oracle exists to
    avoid.
  - Capture tests never run in default CI and will rot silently if V1 or
    the fixture moves. Standing reminder: re-run
    `D09_V1_ROOT=... pytest -m capture` whenever either changes. The
    mechanical guard against a different failure mode is already in place —
    `test_oracle_modules_are_dependency_light` — because pytest imports a
    module to collect it even when every test inside is deselected, so a
    module-scope import of a heavy dependency breaks default CI collection
    regardless of markers.

- [ ] **D-13 · Plan diversity + apply-pick engine** (`strategies.py` + `engine.py`) — depends on D-12
  Carries the seven §7 draft invariants — "never freeze on bad input."
  Acceptance criterion (applies across this series wherever the draft path
  touches a projection set): when no active projection set exists, the
  draft path returns a clean 422, not a 500. Reproduce the small idea in
  V1 commit `2267043`'s `backend/projections/errors.py` rather than
  reinventing it.

- [ ] **D-14 · Auction simulation** (`auction_sim.py`) — DEFERRED, not cut
  Explicitly **not** one of Patrick's four named subsystems (optimizer,
  plan diversity, MC targets, Forge Value). Revisit after D-13 lands.

- [ ] **D-15 · V2's first projection migration** (the SQL behind schema §05)
  Reference SQL: `supabase/migrations/20260905120000_projection_sets.sql` on
  the orphaned branch — an independent implementer reached the same
  normative rule §05 states (makes *and* attempts, never a bare
  percentage), which is evidence §05 is right. Do not reland the migration
  file directly; verify it still applies cleanly to `v2`'s current schema
  before adapting it.

- [ ] **D-16 · Projection upload UI** — depends on D-15
  "Upload a BBM season set from inside the Draft Room," downstream of the
  projection storage tables existing. 201 lines of `ProjectionUpload.tsx`
  already exist on the orphaned branch (`f41364d`) as a design reference —
  not a port candidate as-is.

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
- The gated port: optimizer, plan diversity, MC targets, Forge Value — **now
  underway**, see "Gated port — projections, optimizer, and draft engine"
  below (classification §6).
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

*Claude updates this on approval. Last change: D-09 merged — characterization
oracle + solver-cap contract, plus a recon half that found and fixed three
defects blocking D-08's fixture from driving V1 at all; D-10 (Forge Value
port) next.*
