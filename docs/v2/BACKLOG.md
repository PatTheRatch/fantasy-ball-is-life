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

- [ ] **S1-07 · ESPN adapter + DTOs** — **NEXT** — depends on S1-02, S1-06
  `fetch_settings`, `fetch_teams`, `fetch_periods` returning FCP DTOs.
  Provider objects must not escape the package, and **no subclassing of
  `espn_api.League`** — that is the §7 violation V1 built its domain on.
  *Schema: [`schema/04-provider-ingestion.md`](schema/04-provider-ingestion.md).*

- [ ] **S1-08 · Ingestion pipeline** — depends on S1-07
  `ingestion_runs`, `raw_payloads` with `content_hash` dedupe, normalizer
  versioning, lineage columns on canonical rows, `partial` as a real run
  outcome. Persist before interpret, so replay works.
  *Charter: D16, D17, D28.*

- [ ] **S1-09 · Player identity crosswalk** — depends on S1-08
  `players`, `player_external_ids`, `identity_links`,
  `identity_review_queue`. The one resolution ladder from
  `schema/04`, wired to `domain/names.py`. An unmatched name is queued and
  counted, never dropped.
  *Charter: D18, D19; non-negotiable "no fuzzy-name identity".*

- [ ] **S1-10 · Matchups + standings read path** — depends on S1-06, S1-09
  Sync one league's completed periods, fold standings from final periods, and
  serve `GET /api/v1/leagues/{id}/standings` with freshness metadata on the
  response.
  *Charter: D10, D11, D20.*

- [ ] **S1-11 · One shared league page**
  React + Vite + TS scaffold, generated API client, the league page rendering
  standings and periods with honest empty and stale states. Closes the slice.

---

## Slice 2 and beyond — not yet cut

Deliberately unscoped. Cutting bites for work that far out invents detail we
do not have, and charter §22 warns against building for architectural
completeness.

Known to come, roughly in order:

- Historical event capture — **starts early**; daily roster snapshots cannot be
  backfilled, so every day not captured is gone (charter D10, §11.7).
- Projections: sources, immutable sets, adjustments, freezes (D22, D24).
- The gated port: optimizer, plan diversity, MC targets, Forge Value —
  **only behind a committed synthetic fixture and characterization tests**
  (classification §6).
- Newsroom: story facts, editions, publishing (D13).
- FCP projection model (D6).

---

## Open questions that block future bites

| # | Question | Blocks |
|---|---|---|
| 1 | Does `matchupPeriods` cover playoff/championship periods, and how does the All-Star break appear? — resolved S1-03 | S1-06 |
| 2 | Roster fetch cost — one request per team per day, or one league-wide call? | Historical capture |
| 3 | Story vocabulary: newsroom / recap / story / timeline. Pick one for tables, API and UI. | Newsroom slice |
| 4 | Self-delivering recaps — absent from the charter by omission, not decision. Product call needed. | Newsroom slice |
| 5 | Adjustment composition: does raising projected minutes scale dependent rate stats? | Projections slice |

---

*Claude updates this on approval. Last change: S1-06 merged.*
