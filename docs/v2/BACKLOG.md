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

- [ ] **S1-11c · Periods endpoint + selector** — depends on S1-11b
  Backend `GET /api/v1/leagues/{league_season_id}/periods` (`LEAGUE_SCOPED`) +
  a period selector on the page; this is what actually closes the slice.
  Also surface H-01's `complete` / `unknown_category_count` envelope fields —
  H-01 makes the data honest, this is where a reader sees it.

- [ ] **S1-11d · Reach a league (optional)** — depends on S1-11b
  `GET /me/leagues` + a home route to list the user's memberships so a league
  can be reached without an out-of-band ID.

---

## Slice 1 hardening — from the red-team triage

Confirmed implementation gaps against a design that already says the right
thing. Source: [`research/REDTEAM_TRIAGE.md`](research/REDTEAM_TRIAGE.md),
each verified against the code before landing here. Ordered by severity;
H-01 and H-02 are correctness bugs in shipped code.

- [ ] **H-01 · Unknown is not a tie** — **NEXT** — the non-negotiable violation
  `compare()` returns `TIE` when either side is `None`/NaN; that persists as
  `result='tie'` and standings counts it as a real category tie. Charter §10:
  absence of a result must never be indistinguishable from a result. Add an
  explicit unknown to the domain result vocabulary, persist `NULL` (the column
  is *already* nullable), exclude unknown categories from the fold, and mark
  the matchup partial rather than final. Ports the invariant register's
  null-vs-zero lesson to null-vs-tie.
  *Charter: D28, §10. Touches `domain/categories.py`, `services/matchups.py`,
  `services/standings_read.py`.*
  Scoped: [`docs/tickets/H-01-unknown-is-not-a-tie.md`](../tickets/H-01-unknown-is-not-a-tie.md).

- [ ] **H-02 · Conflicting birthdate must not auto-link**
  The ladder falls through from `exact_name_dob` to `exact_name` and auto-links
  at 0.850 even when the candidate's birthdate contradicts the provider's.
  Treat a two-sided birthdate disagreement as a conflict and queue it. Add the
  test that was missing — `tests/services/test_resolution.py` covers matching
  and absent DOB, never contradictory.
  *Charter: D18 (prefer unknown over confidently wrong).*

- [ ] **H-03 · Runs must always reach a terminal state**
  Any exception after `start_run()` leaves the run `running` forever. Wrap
  run-owning services in a lifecycle context manager that guarantees
  `succeeded | partial | failed` on exit. Also stamp `partial` when a payload
  is missing scoring categories (pairs with H-01).
  *Charter: D28 — job outcomes are queryable data, not log lines.*

- [ ] **H-04 · Make tenancy structural, not conventional**
  Two halves, both currently labels rather than gates: `MatchupRepository` and
  `LeagueSeasonRepository` take a bare `Session` while `LeagueScopedRepository`
  sits unused, and `@declare_policy` attaches no dependency while the matrix
  test only asserts the attribute exists. Bind league repos to a scope, and
  make the matrix test inspect each route's dependency graph so a
  `LEAGUE_SCOPED` route without a membership dependency fails CI.
  **No live hole today** — the standings route is guarded — but D26 claims
  structure, and structure is what is missing.
  *Charter: D26, non-negotiable #1.*

- [ ] **H-05 · Constrain what the schema claims**
  Database-level gaps behind stated invariants: matchups can reference a
  period and teams from other leagues (composite keys); nothing ties
  `status='final'` to `finalized_at`; name-only `provider_identities` are not
  unique (partial unique index on `raw_name WHERE provider_entity_id IS NULL`);
  `identity_review_open_idx` is not unique; `identity_links.confidence` has no
  `0..1` bound and `fcp_entity_id` is polymorphic with no FK. Check #12 —
  `fantasy_team_seasons` likely has the same cross-league binding gap.

- [ ] **H-06 · Wire payload dedupe, or delete the claim**
  `find_by_hash` and `latest_for` have zero callers; `record_payload` always
  inserts. Either wire dedupe in — first widening the key, which is
  `(provider_id, endpoint, content_hash)` where endpoint is
  `scoreboard/{espn_period_id}` and therefore collides across leagues — or
  remove the methods and their docstrings. A documented guarantee nothing
  calls is worse than an absent one.

- [ ] **H-07 · Finality needs a producer** — depends on H-01, H-03
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

*Claude updates this on approval. Last change: S1-11b merged.*
