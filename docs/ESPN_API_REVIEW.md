# ESPN API Integration Review

**Date:** 2026-07-12  
**League sampled:** Patriot Games, ESPN fantasy basketball season 2026  
**Scope:** backend data access, FastAPI routes, Draft Room, In-Season, Season,
weekly recap assembly, Streamlit, frontend consumption, and test coverage  
**Method:** read-only code tracing plus sanitized live ESPN sampling

## Executive verdict

The integration gets the core ESPN data, and completed-week scoreboard requests
do honor the requested matchup period. The main problem is not ESPN coverage;
it is that the application repeatedly rebuilds the same large `League` object
and mixes raw ESPN values, presentation encodings, and fantasy scoring rules.

Four correctness issues should be fixed before trusting the affected features:

1. The current transaction route is nonfunctional.
2. Weekly recap turnover winners are reversed.
3. All-play and power-ranking calculations add zero-stat teams during later
   playoff weeks.
4. `GET /rosters/current` returns zero games remaining for every player when
   its optional date parameters are omitted.

The largest measured hotspot is recap assembly: one readiness/generation pass
made 22 ESPN requests, transferred 12.75 MB, and took 10.69 seconds before any
LLM call. A single reused league context would reduce that pass to roughly six
requests without changing product behavior. A narrower gateway that requests
only the views recap needs can reduce it further to roughly three requests.

No runtime code was changed during this review.

## Scope and evidence rules

- Live probes called ESPN read endpoints only.
- Cookies, Supabase keys, authorization headers, owner identities, player
  names, and team names were not recorded in this report.
- Payload sizes are compressed HTTP response-body sizes observed by
  `requests`.
- Latencies are single-run wall-clock measurements from the local development
  environment. They establish order of magnitude, not a service-level
  benchmark.
- Findings marked **confirmed** were reproduced against live Patriot Games
  data. Findings marked **inferred** are deterministic call-count conclusions
  from the traced code paths.

## Raw ESPN contract

### `espn-api` league construction

Constructing either `espn_api.basketball.League` or `MyLeague` eagerly made four
HTTP requests:

- `mTeam,mRoster,mMatchup,mSettings,mStandings`: 1,722,007 bytes
- `mDraftDetail`: 56,699 bytes
- `players_wl`: 271,929 bytes
- `proTeamSchedules_wl`: 432,111 bytes

Total: 4 requests and 2,482,746 bytes for every constructor.

Observed constructor wall time ranged from 0.88 to 1.95 seconds. `MyLeague`
performed no additional HTTP calls after construction; its schedule and
all-play work is CPU-side over the eagerly loaded payload.

This confirms that even settings-only handlers currently pay for rosters,
draft details, the player universe, and the NBA schedule.

### Additional ESPN methods and views

- `league.box_scores(matchup_period=week)` made one request using
  `mMatchupScore,mScoreboard`. The sampled week-21 response was 333,423 bytes.
- `league.recent_activity(size=500)` requested the
  `kona_league_communication` communication endpoint and returned HTTP 404.
- `mTransactions2` returned transaction data when both `scoringPeriodId` and a
  valid `x-fantasy-filter` were supplied.
- Neither `espn-api`'s `league_get()` nor `get()` supplies a request timeout.
  The application fallback in `safe_recent_activity()` also has no timeout.

### Derived application contracts

Live shapes observed after application transformation:

- League meta: 10 fields covering league identity, season, teams, scoring,
  acquisition settings, trade deadline, and regular-season/playoff settings.
- Teams: 14 rows and 12 fields, including `owners`.
- Standings: 14 rows and 13 fields.
- Matchups for week 21: 7 rows with matchup identity, category totals, shooting
  makes/attempts, and matchup records.
- Current rosters: 181 rows.
- Season all-play stats: 14 rows and 36 fields.
- Composite power rankings: 14 rows.
- Raw current scoreboard: 13 statistical rows per active matchup. The API
  deliberately filters this to the nine league scoring categories.

The public teams and standings responses include `owners`, but no React
consumer uses that field. It should not be exposed by default.

## Live performance baseline

### Single FastAPI handlers

- `GET /league/settings`: 4 ESPN requests, 2.48 MB, 0.92 seconds.
- `GET /league/standings`: 4 requests, 2.48 MB, 0.88 seconds.
- `GET /scoreboard/current?scoring_period=21`: 5 requests, 2.82 MB,
  1.13 seconds.
- `GET /rosters/current` for week 21 with Last-15 projections: 4 requests,
  2.48 MB, 1.18 seconds.
- `GET /season-stats` for weeks 1-21: 4 requests, 2.48 MB, 2.05 seconds.
- `GET /power-rankings` for weeks 1-21: 4 requests, 2.48 MB, 3.57 seconds.
- `GET /projected-scoreboard` for week 21 with Last-15 projections:
  5 requests, 2.82 MB, 1.47 seconds.

Power rankings and season stats do not make week-by-week ESPN calls. Their
extra time is local pandas work over one eager league payload.

### Weekly recap

One `assemble_weekly_snapshot()` call for week 21 made:

- 5 complete league constructions: 20 requests
- 1 box-score request
- 1 failing communication/transaction request

Total: 22 requests, 12,747,408 bytes, and 10.69 seconds.

The admin workflow currently runs readiness first and generation later. Both
assemble the same week independently. A normal “check, then generate” workflow
therefore costs about 44 ESPN calls, 25.5 MB, and 21 seconds before the LLM
request, unless frontend cache state or user behavior avoids one pass.

### In-Season page

Loading the projected matchup surface with a built-in Last-15/Last-30 source
does the following:

- two separate `GET /rosters/current` requests for total-week and
  remaining-week windows: 8 ESPN requests;
- one `GET /matchup-confidence`, which builds a league once and computes both
  projected scoreboard and roster context: 5 ESPN requests.

That view is therefore 13 ESPN requests and about 7.8 MB before current
scoreboard or power rankings are loaded. Loading projected, current, and power
surfaces for the same week totals about 22 requests and 12.7 MB. React Query
caches loaded In-Season queries in the browser, but the backend does not reuse
data between the first requests or between users.

### Draft Room

`OptimizeLineup.__init__()` constructs `MyLeague`. `_build_pool_context()`
constructs one template optimizer and then constructs another optimizer for
every solve.

For the default ten-plan portfolio, the initial plan request therefore has an
inferred lower bound of:

- 11 `MyLeague` constructions: one template plus ten solves
- 44 ESPN requests
- about 27.3 MB transferred

The Draft Room also loads league teams and settings through two independent
handlers, adding 8 requests and about 5.0 MB on a cold page load. The modern
Draft Room caps `n_plans` at 10, but the older
`POST /optimizer/multiple-plans` body remains unbounded.

## Correctness findings

### P0 — Transactions are broken

**Confirmed.** `transactions_df()` first calls
`league.recent_activity(size=500)`. ESPN returned 404 for the communication
endpoint. Its fallback then accesses `h.league.espn_s2` and
`h.league.swid`; those attributes are not present on the installed
`espn-api` `League` object. The live route failed with:

`AttributeError: 'League' object has no attribute 'espn_s2'`

The fallback URL is also not the `mTransactions2` contract and would not
produce the `Activity` objects that `transactions_df()` expects.

#### Working transaction source

`mTransactions2` worked with one request per scoring period:

- query: `view=mTransactions2&scoringPeriodId={week}`
- header: `x-fantasy-filter`
- filter types must use ESPN's exact transaction vocabulary.

A weeks 1-21 backfill using the useful transaction types returned 1,799 unique
records. The contract includes:

- transaction fields: ID, type, status, execution type, pending state, team,
  member, bid, proposed/process dates, scoring period, related transaction,
  and items;
- item fields: type, player ID, source/destination team, source/destination
  lineup slot, keeper status, and draft pick.

The season sample showed why filtering and normalization are mandatory:

- 872 `FUTURE_ROSTER` records containing 2,429 lineup-only items;
- 552 waiver records, of which 150 were executed;
- 402 failed or canceled waiver attempts;
- 8 executed roster drops and 1 executed free-agent addition;
- 182 draft records;
- trade activity split across 83 proposal, 10 accept, 14 uphold, 76 decline,
  and 1 veto records.

Exactly 159 records were simple executed player movements with an `ADD` or
`DROP` item. That count intentionally excludes trades: ESPN represents a trade
as a related transaction chain, so proposal/accept/uphold records must be
joined by `relatedTransactionId` before players and counterparties are
attributed.

For recap awards, ingest only executed acquisitions/drops plus reconstructed
completed trades. Exclude draft, lineup-only, pending, failed, canceled,
declined, and vetoed records.

### P0 — Recap turnover winners are reversed

**Confirmed against a live completed matchup.**

ESPN returned positive turnover totals: home 57, away 89. The expected category
winner is home because fewer turnovers is better.

`get_current_scoreboard()` converts those values to -57 and -89 so existing
frontend comparison code can treat “higher is better.” `canonical_matchups()`
then applies a second lower-is-better rule for `TO`, causing -89 to beat -57.
The recap snapshot therefore marked away as the winner.

This is a boundary bug: the feed is returning a presentation-encoded value,
while recap assembly assumes a natural basketball value. Canonical facts
should store positive turnover counts with category metadata declaring
`lower_is_better`. Presentation layers can derive arrows and win/loss labels
without changing the fact value.

### P0 — Playoff all-play rankings include ghost teams

**Confirmed.** `MyLeague.get_wins()` reindexes each weekly matchup table to all
14 league teams and fills missing teams with zeros.

- Week 1: 14 source team rows and 14 result rows.
- Week 20: 14 source team rows and 14 result rows.
- Week 21: 12 source rows, 11 unique active teams, but 14 result rows.
- Week 22: 10 source rows, but 14 result rows.

In the week-21 sample, three synthesized teams each received 11 all-play wins,
88 losses, and 18 ties despite having no matchup facts. All 11 wins came from
the turnover category because zero beats each active team's negated turnover
total.

This distorts playoff-week season stats, composite power rankings, rank
movement, and recap narratives. A weekly all-play calculation must compare
only teams with a valid matchup/category record for that week. Bye handling
must be explicit rather than inferred from zero-filled rows.

### P0 — Default roster date window is inverted

**Confirmed.** With no date parameters:

- 181 roster rows
- 0 players with a positive `num_games_left`
- 0 total games remaining

With the actual week-21 range:

- 181 roster rows
- 181 players with a positive `num_games_left`
- 649 total scheduled games across roster-player entries

The default start date is after the default end date. The API should derive the
window from the requested/current matchup period and reject an invalid range.

### P1 — Scoring periods are honored, but period semantics are fragmented

**Confirmed.** Requested weeks 1, 20, 21, and 22 returned different, nonzero
box-score datasets. Completed and playoff scoring periods are therefore
available through `box_scores(matchup_period=week)`.

However, the application uses several independent notions of “current”:

- ESPN `scoringPeriodId`
- ESPN `currentMatchupPeriod`
- schedule length
- hardcoded `MATCHUP_WEEKS_2025_26`
- frontend `MATCHUP_WEEKS_2025_26`
- configured ESPN season and a separate draft league year

The sampled league reported `currentMatchupPeriod=22` while the regular season
ended at week 19. Future work should model NBA scoring day, fantasy matchup
period, regular season, and playoff round as separate fields.

### P1 — Shooting percentage aggregation needs an explicit contract

Weekly all-play comparison uses ESPN's weekly FG% and FT% category values,
which is appropriate. Multiweek output then averages those weekly percentages.
That is not the same as `sum(makes) / sum(attempts)`.

The current power-ranking category ranks therefore mean “average weekly
percentage,” not “season aggregate percentage.” This may be a valid editorial
choice, but it must be named and tested. If the product intends season shooting
percentage, aggregate makes and attempts instead.

## Reliability and efficiency findings

### P1 — No backend reuse or cache

Every handler calls `_handles()` or `_my_league()` and reconstructs the same
league. Even calls inside one user workflow do not share an object. The
frontend's one-minute global cache and In-Season's per-session infinite cache
reduce repeated browser calls, but cannot protect ESPN from cold loads,
multiple users, server retries, recap double assembly, or Draft Room solves.

### P1 — No timeout on any `espn-api` read

The installed library calls `requests.get()` without `timeout` in both
`league_get()` and `get()`. A stalled ESPN connection can therefore occupy an
API worker indefinitely. The fallback transaction request has the same issue.

A gateway should own explicit connect/read timeouts, bounded retries with
jitter for safe reads, and typed upstream errors.

### P1 — Error behavior can turn outages into valid-looking empty data

- `matchups_df()` uses a bare `except` and returns an empty set.
- Several simple league routes let upstream exceptions become framework 500s.
- Other routes wrap every exception as status 500 with inconsistent messages.
- Recap assembly captures section errors and permits “generate anyway,” which
  is useful only if data absence can be distinguished from an ESPN outage.

The gateway should produce typed `not_available`, `unauthorized`,
`rate_limited`, `timeout`, and `contract_changed` errors. Data-quality reports
should preserve those reasons.

### P1 — API reads write debug files

Projected roster/scoreboard paths write CSV files and several feed functions
print debug messages during normal API requests. Read handlers should not have
filesystem side effects. Structured logging should replace prints; explicit
export commands should own CSV creation.

### P1 — Public payloads include unused owner data

`teams_df()` and `standings_df()` include ESPN owner records. The React app does
not consume them. Public league responses should project only the fields the
feature needs, and owner identity should require an explicit product decision.

### P2 — Duplicate and dead calculation paths

`MyLeague.get_power_rankings()` is not called by the current application; the
FastAPI router implements a separate composite ranking calculation. Keeping
both invites semantic drift. The older Streamlit/feed orchestration also
recomputes data that the React/FastAPI path computes differently.

## Data lineage by product surface

### In-Season

1. Frontend selects a week and projection source.
2. Current view calls `/scoreboard/current`.
3. Projected view calls `/rosters/current` twice and
   `/matchup-confidence` once.
4. Power rankings call `/power-rankings`, which builds all-play windows from
   `MyLeague`.
5. Frontend again derives matchup winners, labels, and grouped rows.

Risk: turnover values are encoded as negative in the backend and interpreted
as higher-is-better in the frontend, while recap interprets them differently.

### Season

1. Frontend calls `/league/settings`.
2. User action calls `/season-stats?weeks=...`.
3. `MyLeague.get_universe_wins()` compares every team against every other team
   per category and aggregates the requested weeks.
4. Frontend renders the returned records and can send them to AI commentary.

Risk: later playoff weeks synthesize missing teams; shooting percentages are
weekly means across multiweek windows.

### Weekly recap

1. Admin readiness calls `assemble_weekly_snapshot()`.
2. Assembly independently calls settings, standings, scoreboard, season stats,
   power rankings, and transactions.
3. Canonical matchups and evidence IDs are built.
4. Generation repeats assembly, persists a snapshot, calls the LLM, and
   persists a draft edition.

Risk: duplicate assembly, reversed turnover winners, ghost-team ranking input,
and unavailable transactions.

### Draft Room

1. Frontend separately loads league teams and settings.
2. Every `OptimizeLineup` constructs `MyLeague`.
3. Initial portfolio construction creates a template optimizer and one
   optimizer per strategy solve.
4. Pick, triage, relax, custom plan, and player search rebuild pool context.

Risk: the optimizer uses ESPN as a constructor side effect even when the
operation needs only an already-loaded projection pool or league-size setting.

## Target architecture

### 1. One ESPN gateway

Create an `EspnGateway` as the only module allowed to perform ESPN HTTP calls.
It should:

- accept league ID, season, and credentials explicitly;
- expose narrow methods such as `league_core()`, `box_score(week)`,
  `transactions(week)`, and `player_schedule()`;
- apply timeouts, bounded retries, request metrics, and sanitized logging;
- validate raw contracts into typed internal DTOs;
- map upstream failures into typed application errors.

Do not leak `espn-api` objects beyond the gateway boundary.

### 2. Request-scoped context plus shared cache

Build one `LeagueContext` per FastAPI request/workflow and pass it to services.
Back it with cache entries keyed by league, season, view, and scoring period.

Recommended starting policy:

- settings and league identity: 15 minutes;
- teams, standings, current roster, and current scoreboard: 30-60 seconds;
- current-week transactions: 60 seconds;
- completed-week box scores and normalized transactions: immutable after a
  short finalization delay;
- player/NBA schedule: 6-24 hours.

Use a single-flight lock so concurrent cold requests do not all refresh the
same key.

### 3. Canonical basketball facts

Canonical DTOs should keep natural values:

- turnovers are positive counts;
- FG% and FT% carry makes, attempts, and derived ratio where available;
- every category carries `higher_is_better` or `lower_is_better`;
- missing and zero are distinct;
- byes and inactive playoff teams are explicit states.

Frontend and narrative layers should consume winners computed once from these
facts rather than repeat comparison logic.

### 4. Normalized transaction ingestion

Add a weekly `mTransactions2` adapter that:

- requests only the target scoring period during normal recap generation;
- filters statuses before awards;
- excludes lineup-only and draft records;
- joins trade chains by related transaction ID;
- resolves ESPN player/team IDs through maps loaded once;
- persists normalized records or the final weekly snapshot.

Backfills can fetch scoring periods with bounded concurrency and write
idempotently by ESPN transaction ID.

### 5. Persist completed weekly snapshots

The recap design already has `league_week_snapshots`. Make the snapshot the
boundary between ESPN and publishing:

- readiness refreshes or reads one snapshot;
- generation consumes that snapshot instead of reassembling it;
- published editions point to immutable facts;
- every user sees the same deterministic result;
- completed weeks do not hit ESPN on public reads.

### 6. Inject data into analytics

`OptimizeLineup`, `MyLeague` calculations, and recap services should accept
normalized data/context rather than constructing network clients internally.
This makes ten Draft Room plans share one league payload and makes analytics
unit-testable from fixtures.

## Expected request reduction

### Recap assembly

Current: 22 requests, 12.75 MB.

First target, reusing one existing `League` plus box score and transactions:
about 6 requests and 2.86 MB.

Reduction: about 73% fewer requests and 78% fewer bytes.

Narrow-view target, excluding constructor views recap does not need:
about 3 requests and roughly 2.1 MB.

Reduction: about 86% fewer requests and 83% fewer bytes.

### In-Season loaded week

Current projected + current + power workflow: about 22 requests and 12.7 MB.

One shared league context plus one box-score request: about 5 requests and
2.82 MB.

Reduction: about 77% fewer requests and 78% fewer bytes.

### Draft Room initial ten-plan portfolio

Current inferred plan-generation baseline: 44 requests and 27.3 MB, excluding
page bootstrap.

One injected/reused league context: 4 requests and 2.48 MB.

Reduction: about 91% fewer requests and 91% fewer bytes.

## Test strategy

The current suite isolates live ESPN with fake league classes and mocks. That
is appropriate for optimizer tests, but there are no recorded raw ESPN
contracts protecting the transformation layer.

Add:

1. Sanitized JSON fixtures for league core, completed box score, playoff box
   score, and `mTransactions2`.
2. Contract-adapter tests that fail clearly when required keys or enum values
   change.
3. Invariant tests:
   - nine scored categories per matchup;
   - natural positive turnover values and lower-wins;
   - only active teams participate in weekly all-play;
   - each active team has `(active_teams - 1) * 9` all-play decisions;
   - FG%/FT% definition is explicit;
   - invalid date ranges are rejected;
   - transaction awards include only completed player movement.
4. Request-count tests around recap, In-Season aggregation, and ten-plan draft
   generation.
5. An opt-in live smoke test requiring environment credentials, recording no
   payload content, that checks status, expected top-level keys, and maximum
   call count.

## Prioritized remediation sequence

### PR A — Transaction adapter (P0)

- Add `mTransactions2` gateway method for one scoring period.
- Normalize executed adds/drops and related trade chains.
- Replace `recent_activity`/`safe_recent_activity` in recap-facing data.
- Add sanitized fixtures and transaction-status tests.

### PR B — Canonical category correctness (P0)

- Keep positive turnover facts.
- Centralize category comparison metadata.
- Fix recap winner calculation.
- Add the live-reproduced 57-vs-89 regression test.

### PR C — Playoff participant correctness (P0)

- Remove zero-filled absent teams from weekly all-play comparisons.
- Define bye behavior.
- Add week fixtures with 14, 12, and 10 source rows.
- Revalidate power rankings and recap rank movement.

### PR D — Roster period correctness (P0)

- Derive date windows from matchup-period metadata.
- Reject `start > end`.
- Remove duplicated hardcoded calendar ownership.

### PR E — Gateway reliability and reuse (P1)

- Introduce timeout/error policy and request metrics.
- Add request-scoped reuse and cache.
- Change recap readiness/generation to share persisted snapshots.
- Enforce request-count tests.

### PR F — Draft dependency injection (P1)

- Stop constructing `MyLeague` inside every optimizer.
- Reuse one immutable league/projection context across portfolio solves.
- Bound the legacy multiple-plan endpoint or retire it.

### PR G — Payload and side-effect cleanup (P2)

- Remove public owner fields unless explicitly required.
- Remove debug CSV writes and prints from read paths.
- Consolidate duplicate power-ranking implementations.
- Make frontend responses feature-specific.

## Approval gates

Before implementation, Patrick and Aisha should confirm:

1. Power-ranking shooting percentage means aggregate makes/attempts or average
   weekly percentage.
2. Bye teams are excluded from weekly all-play, rather than scored as ties.
3. Transaction awards count executed waiver/free-agent adds, standalone drops,
   and completed trades only.
4. Completed weekly snapshots become immutable unless an admin explicitly
   refreshes them.

Once those semantics are locked, PRs A-D can proceed independently without
mixing the larger gateway refactor into correctness fixes.
