# Feature Spec: Draft Room — redesigned optimizer + draft-day resilience

**Status:** Reviewed by Aisha (lead systems engineer) 2026-07-09 —
[`DRAFT_ROOM_REVIEW.md`](DRAFT_ROOM_REVIEW.md). Approved to implement with six
required amendments; those amendments are applied in this revision (see §4/§5).
Gate 2 (constraint relaxation) now uses iterative relaxation on the current solver
stack. Cleared for implementation pending Aisha's quick re-check of the Gate 2
wording. Product decisions in §0 remain final (architecture sign-off per
[`docs/AISHA_OPERATING_MANUAL.md`](../AISHA_OPERATING_MANUAL.md)).
**Author:** Claude Code (implementation engineer)
**Date:** 2026-07-09
**Decision basis:** Product design review with Patrick, 2026-07-09. Replaces the
26-line `frontend/src/pages/DraftPage.tsx` stub. Builds on the merged solver-
feasibility fix (`optimize_lineup._validate_pool_feasibility`, PR #1).
**Visual reference:** interactive desktop mockup —
https://claude.ai/code/artifact/35f8e1a0-0210-4e47-9610-69a6f7536f88
(mockup only; sample data, not wired to the optimizer).

---

## 0. Locked design decisions

Captured from the 2026-07-09 review so implementation doesn't relitigate them:

| # | Decision | Choice |
|---|---|---|
| D1 | When it's used | Both draft **prep** and **live** draft, one adaptive screen |
| D2 | Screen hero | The **target roster plan** (optimal 13-man build) |
| D3 | Look & feel | **Data-dense terminal**, dark-first, cool near-black neutrals, a single **amber accent** (auction/value), monospace numerals. Category strength uses a separate teal↔rose semantic scale |
| D4 | Devices | Desktop = full dense board; **phone = live companion** (triage + next target + gaps) |
| D5 | Per-player data | Projected $ value · your max bid · value-over-replacement/rank · all 9 category contributions |
| D6 | Pick logging | **Manual-first** (source of truth). Team **dropdown** (all league teams). **Undo** — global "last pick" and per-pick |
| D7 | On-the-block player | **User sets it manually**; no dependency on a live ESPN feed. Tool triages relevant / safe-to-pass + shows your max |
| D8 | Plan portfolio | **Auto-generate, then hand-tune**, up to **10** plans (target 10 — validate against solve time in testing; may reduce). Strategy shapes are **user-selectable**: balanced, punt one/more cats, spread value, stars & scrubs. All are the same engine mechanic — constrain a set of categories, maximize one — just parameterized differently |
| D9 | When a plan breaks | **Auto-advance** to the next live plan (instant). Re-solve with relaxation only if *all* break |
| D10 | Relaxation control | **Auto-propose, one-tap confirm** before it becomes active |
| D11 | Live ESPN sync | **Optional future accelerator only** — never a dependency (see §6) |
| D12 | Draft persistence | **v1: same-device autosave** — survives an accidental refresh or crash (browser local storage). **Resume-anywhere** (server-side, cross-device) is a known future upgrade, not v1 |

**Deferred to a later spec (explicitly out of scope here):** the "League
landscape" panel — most-similar build, your kryptonite, league-wide budget/
inflation. Shown as a `Planned` placeholder in the mockup; no implementation now.

**Future idea, not yet scoped (Patrick, 2026-07-09):** a player lookup that
does more than resolve a name — pull recent headlines/news for context at
draft time (traded to a new team, out until midseason, role change). Framed
explicitly as future state; the "how" (news source, matching, what counts as
draft-relevant) isn't decided. Needs its own design pass before it becomes a
spec item.

---

## 1. User story

> As a 9-cat H2H manager drafting in a live auction, I want one screen that shows
> my optimal roster plan and — the moment a player is nominated — tells me whether
> I care and what my max bid is, so I make fast, confident bids. And when my plan
> gets sniped, I want the next move already on screen, so I never freeze on an
> "infeasible" dead end.

Secondary (prep): as the same manager, before the draft I want to set my
category/budget targets and save a handful of diverse fallback plans, so draft
day is execution, not improvisation.

## 2. Acceptance criteria

1. **Manual-first end to end.** A full draft can be run with manual input only —
   no ESPN integration active — and produce a completed, valid roster. Every
   feature (triage, pivots, re-optimize) is fed by the user's clicks.
2. **The recommendation surface is never empty.** At all times during a live
   draft the app shows at least one actionable next pick. "Infeasible" is never a
   terminal state shown to the user (criterion 6 defines the fallback ladder).
3. **On-the-block triage.** The user sets the nominated player (search). Within
   ~1s the app classifies it **Relevant** (in ≥1 live plan → shows your max bid)
   or **Safe to pass** (in no live plan and not a value target), reading off the
   already-computed plan portfolio — no fresh solve.
4. **Plan portfolio with live health.** In prep, the app auto-generates a diverse
   set of plans (up to 10); the user keeps/tunes/saves them. During the draft
   each saved plan shows health: **Alive**, **At risk** (feasible but hinges on a
   scarce player), or **Broken** (infeasible). Health recomputes as picks land.
5. **Auto-advance on a miss.** When the active plan's target is taken by a rival,
   the app switches to the highest-ranked still-**Alive** plan with **zero** solve
   latency (the switch is precomputed), and surfaces the new next move.
6. **Graceful relaxation when all plans break.** If every saved plan is Broken,
   the app does **not** show a bare error. It (a) names *why* it's infeasible
   (budget exhausted / position exhausted / a category target unreachable), (b)
   proposes the single lowest-cost constraint relaxation with its tradeoff
   (e.g. "punt BLK, −0.4σ"), and (c) requires **one tap to confirm** before that
   becomes the active plan. While any solve runs, the **best-available-by-value**
   pick is shown as an immediate fallback (computable from projections without an
   optimize).
7. **Pick logging + undo.** Logging a pick captures player, price, and the team
   (dropdown of all league teams; the user's own team charges their budget). The
   user can **undo the last pick** and **undo any specific pick**, and state
   (budget, rosters, plan health) recomputes correctly after an undo.
8. **Dense but legible.** Each roster row shows the D5 data including a 9-cell
   category heat strip. The board is fully usable on desktop; on phone it
   collapses to the live-companion layout (D4) with no horizontal page scroll.
9. **Source of numbers is honest.** Projections feeding the optimizer come
   through the projection-source framework
   ([`PROJECTION_SOURCE_FRAMEWORK.md`](PROJECTION_SOURCE_FRAMEWORK.md)); the
   active source/date is visible on the Draft page.

## 3. Data model impact

No database (consistent with the rest of the app). Three new structures. **In v1
the draft state is client-authoritative and persisted to browser local storage**
(D12), so an accidental refresh or crash mid-draft loses nothing on the same
device. The backend stays **stateless per request** and only *computes* plans on
demand (cvxpy is Python-only — see §4). A durable **server-side** `DraftSession`
arrives later with the resume-anywhere upgrade; the shape below is the same either
way.

**`DraftSession`** — one active draft.

| Field | Notes |
|---|---|
| `session_id` | opaque id |
| `schema_version` | bumps the localStorage format so old drafts migrate cleanly across deploys (D12) |
| `picks_version` | monotonic counter incremented on every pick/undo; echoed on mutating calls to discard stale/out-of-order responses (concurrency) |
| `league_id`, `season` | from config |
| `budget`, `roster_size`, `games_per_week` | auction/league params |
| `teams` | list of `{team_id, name, is_user}` — powers the pick dropdown (D6) |
| `picks` | ordered list of `PickLogEntry` (the source of truth) |
| `plans` | list of `SavedPlan` (the portfolio) |
| `active_plan_id` | which plan drives "next move" |
| `projection_set_id` | which `ProjectionSet` (§9) is in use |

**`SavedPlan`** — one strategy in the portfolio.

| Field | Notes |
|---|---|
| `plan_id`, `name` | e.g. "Balanced", "Punt BLK" (auto-labelled, user-editable) |
| `constraints` | snapshot: `categories`, `percentile`, `minimum_value_players`, any per-cat targets |
| `roster` | current computed roster given `picks` (list of `PlanSlot`) |
| `health` | `alive` \| `at_risk` \| `broken` |
| `health_reason` | for at_risk/broken: the binding/violated constraint(s) |
| `next_target` | the recommended nomination + max bid under this plan |

**`PickLogEntry`** — one auction result.

| Field | Notes |
|---|---|
| `player_key` | normalized name (existing `normalize_name`) |
| `price` | winning bid |
| `team_id` | who won them; `is_user` derived |
| `ts` | for undo ordering |

**Derived, not stored:** budget remaining, per-team rosters, category coverage
vs league, best-available value board — all computed from `picks` + the active
`ProjectionSet` so an undo simply recomputes them.

**Persistence format (D12):** the whole `DraftSession` (including the last
warm-cache snapshot, §4) is JSON-serialized to a versioned localStorage key. On
load, a `schema_version` mismatch triggers a migration (or a clean reset with a
warning) rather than a crash. Player names in `PickLogEntry` resolve to
`player_key` through the existing `normalize_name` + fuzzy-match pipeline
([`PROJECTION_SOURCE_FRAMEWORK.md`](PROJECTION_SOURCE_FRAMEWORK.md)); pick logging
reuses that resolver so a typed "Giannis" maps to the projection row.

## 4. API / UI impact

**Optimizer / backend.** Extends the existing `POST /optimizer/optimize` and the
already-present `generate_multiple_plans` in `optimize_lineup.py`. New/changed:

- `POST /draft/session` — create/reset a draft session (params from §3). Returns
  `session_id`.
- `POST /draft/{id}/plans` — generate the diverse portfolio for prep (up to 10
  plans via `generate_multiple_plans`, one per strategy shape), returns
  `SavedPlan[]` with strategy labels. `PUT /draft/{id}/plans/{plan_id}` to
  hand-tune and save (D8).
- `POST /draft/{id}/pick` — log a pick (`PickLogEntry`). Side effect: recompute
  every plan's `health` + `next_target`, and **warm the pivot cache** (§ below).
  `DELETE /draft/{id}/pick/{ts}` — undo (D6/criterion 7).
- `GET /draft/{id}/state` — the full derived view the UI renders (active plan,
  plan healths, coverage, value board, budget).
- `POST /draft/{id}/triage` — `{player_key}` → `{relevant: bool, in_plans:[...],
  max_bid}` (D7). Cheap: reads the warmed portfolio, no solve.
- `POST /draft/{id}/relax` — when all plans broken: returns the ranked relaxation
  proposal(s) with tradeoff; caller confirms via `PUT .../active` (D9/D10).

**The optimizer must return infeasibility *diagnostics*, not opaque errors.**
Builds directly on the merged `_validate_pool_feasibility`. On an infeasible
solve the backend classifies the cause — budget exhausted / position exhausted /
category target unreachable / too few value players — from cheap pre-checks (no
solve) so the UI can name *why* it broke.

**Constraint relaxation is iterative, not dual-value-based.** Aisha's benchmark
(review, Gate 2) established that the current stack — cvxpy → HiGHS for the
boolean MILP — exposes *neither* reliable dual values (shadow prices) *nor* an
irreducible infeasible subset, so the earlier "rank relaxations by shadow price /
IIS" plan is not implementable here. v1 relaxes **iteratively** instead: for each
of the 9 category requirements, re-solve the active plan with that one category
dropped from `set_requirements`; keep the feasible results and propose the
**lowest-cost** one (least category-strength / objective lost) with its tradeoff
(e.g. "punt BLK, −0.4σ"). Cost ≈ 9 × ~4s ≈ **36s worst case** — acceptable because
this path runs **only when every saved plan is Broken** (rare), and the result is
**cached** so re-viewing it is instant. Throughout that sweep the always-available
value board (below) is the shown pick, so the user is never blocked (§2 crit. 6).

*Future performance upgrade (not v1):* solve the LP relaxation (drop
`boolean=True`) with CLARABEL, which does expose duals, rank constraints by shadow
price, and re-solve only the top candidate (~4s for one LP solve). Deferred
pending validation that LP-relaxation duals reliably match the MILP binding order.

**Per-pick execution model** (the "never freeze" mechanism; benchmarked in the
review). On each `POST /draft/{id}/pick` the backend:
1. runs **synchronous health checks** on all saved plans — each is an O(1) lookup
   ("is the drafted player in this plan's roster?"), <100ms for all 10 together;
2. **re-solves only the plans the pick broke.** Portfolio diversity (strategy map
   below) means a given pick typically breaks **0–2** plans, so this is
   0–2 × ~4s = **0–8s**, returned synchronously — comfortably inside a 30–90s
   between-pick window.

That is the "warmth": the recompute happens **at pick time** (slack — other
managers nominating players the user doesn't want), so "if my target is sniped,
the next move is X" is already computed before the miss. In v1 this needs **no
durable server session** — state is client-held (D12) and each pick POST triggers
a stateless recompute; compute stays on the backend because cvxpy is Python-only.

**Cascade fallback.** In the rare case a pick breaks **>3** plans at once, the
backend returns the health statuses immediately and **streams** the remaining
re-solves via **SSE**; affected plans render a "recomputing" state (`stale: true`,
below) until their result arrives.

**No solver warm-start.** cvxpy builds fresh `cp.Variable`/`cp.Problem` objects
each call, and a drafted player shrinks the variable dimension, so warm-starting
is structurally impossible regardless of backend. It doesn't matter — a single
solve is **~3.77s** (benchmark: 564-player pool, 13 spots), and cold 10-plan
generation is **~42s**, a one-time prep/reset cost, not the per-pick workload.

**Amendment (2026-07-10) — solver timeout + retuned percentiles.** The ~3.77s
benchmark above, like every solve this spec was tested against, ran with
category constraints bypassed (`set_requirements` mocked out) — necessary at
the time because the only target method needed live ESPN history, which wasn't
reachable where this was built. Once Monte Carlo targets landed
([`MC_DRAFT_TARGETS.md`](MC_DRAFT_TARGETS.md), history-independent, so
`set_requirements` is testable without ESPN for the first time) and were run
for real, a full constrained solve took 8–24s+ for several category/percentile
combinations in `draft_strategies.STRATEGY_PERCENTILE_BANDS`' original range —
and `cp.Problem.solve()` had **no time limit at all**, so some of that was
genuinely unbounded. Two fixes landed together:
- `optimize_lineup.optimize_roster` now solves with
  `config.SOLVER_TIME_LIMIT_SECONDS` (default 8s). A time-limited solve is
  validated (selected-player count must still equal the roster need) before
  being trusted — HiGHS can return a `user_limit` status with a degenerate
  incumbent, which surfaced as a real bug during the fix (silently returning a
  0-player "feasible" roster) before the count check was added.
- `STRATEGY_PERCENTILE_BANDS` shifted down ~0.35 (e.g. Balanced 0.70 → 0.35
  midpoint) to the range empirically sampled as reliably fast to solve.
  Relative spacing between shapes is unchanged.
- **Honest result, not a full guarantee:** with the retuned bands, the default
  10-plan portfolio solves end-to-end in ~31s total against real MC targets —
  but **2 of the 10 default plans still hit the full 8s cap** on today's pool
  (still succeed; just not fast). Solve difficulty near a MILP's feasibility
  boundary isn't a smooth function of percentile, so lower isn't strictly
  better everywhere — this wasn't chased further. The real guarantee this
  amendment adds is that a solve **always terminates** and **never returns a
  corrupted result**; it does not guarantee every pick recompute finishes
  comfortably under 8s. `tests/test_plan_diversity_integration.py::test_default_recipe_solves_for_real_with_mc_targets_and_stays_bounded`
  is the regression guard — the first test in this suite to exercise a real,
  unmocked `set_requirements` solve, which is how this went undetected until now.

**Concurrency.** Every mutating call carries a monotonic `picks_version`
(§3). The client echoes the version it acted on; a response for a superseded
version is discarded, so rapid pick entry can't apply out of order.

**Warm-cache structure & location.** The cache is a plain snapshot returned in the
`POST /draft/{id}/pick` response (also `/plans` and `GET /state`) and stored
**client-side** in the localStorage `DraftSession` (D12) — the server keeps none
of it. Shape:

    {
      picks_version: int,
      active_plan_id: str,
      value_board: [ {player_key, value, max_bid}, … ],   # solver-free floor
      plans: {
        <plan_id>: {
          health: "alive" | "at_risk" | "broken",
          health_reason: str | null,
          roster: [PlanSlot, …],
          next_target: {player_key, max_bid, fills: [cat, …]} | null,
          stale: bool                 # true while a cascade re-solve is pending
        }, …
      },
      fallback_next: {plan_id, player_key, max_bid}        # top still-alive plan's move
    }

The client renders entirely from this snapshot; triage (`/triage`) and
auto-advance read it with **no** network round-trip (a miss just promotes
`fallback_next`).

**Plan strategy → solver parameters.** Portfolio diversity comes from distinct
strategy parameterizations, not just percentile cycling + top-price banning (which
the review found yields plans sharing 8–10 of 13 players). Each D8 shape maps to
concrete knobs on `OptimizeLineup` / `generate_multiple_plans`:

| Strategy | Categories in `set_requirements` | `percentiles_cycle` | Other knobs |
|---|---|---|---|
| Balanced | all 9 | ~0.65–0.75 | default `minimum_value_players`; rotate `stat_to_maximize` |
| Punt one | 8 (drop the punted cat) | ~0.72–0.80 (higher — freed spend) | maximize a cat you're strong in |
| Punt multiple | 6–7 (drop 2–3, e.g. FG%+TO or AST+3PM) | ~0.75–0.82 | — |
| Stars & scrubs | all 9 at a low floor | ~0.55–0.65 | concentrate budget — **more** required $1 fills (many scrubs behind a few stars) |
| Spread value | all 9 | ~0.68 | **fewer** $1 fills (more mid-tier players); lift the top-price ban |

`minimum_value_players` is the optimizer's count of required **$1 roster slots**
(players whose `Value == 1`): *more* $1 slots ⇒ top-heavy stars & scrubs, *fewer*
⇒ a flatter spread build. (Correction found in implementation: an earlier draft of
this table had the stars & scrubs / spread-value direction reversed.) A "punt" is
literally dropping that category from `set_requirements`. Exact bands and counts
are tuned in implementation and pinned by the diversity test (§5); the map fixes
*which* knob each shape turns.

**Empirical check (implemented — `draft_strategies.py`).** The strategy map and a
dependency-injected diversity loop (`generate_portfolio`) are built and unit-tested
offline; a gated integration test runs them through the **real** `OptimizeLineup`
on the **real BBM pool** (`tests/test_plan_diversity_integration.py`). Findings on
the live 564-player pool: all 10 configs solve feasibly; the objective + multi-punt
variation alone already yields diverse rosters (avg overlap 4.2/13, many pairs at
0 shared). **Single-category punts are no-ops unless category targets are active** —
with targets bypassed, `Punt FT%` and `Punt TO` collapsed onto `Balanced` (13/13
shared). Two consequences, now load-bearing in the design: (1) portfolio generation
**must** set category requirements (whose targets come from `get_universe_wins`),
and (2) the `generate_portfolio` **≤8/13 dedup** is what guarantees the final saved
set is distinct even when raw configs collapse. Note: the full target-setting path
needs live ESPN access, which the web sandbox's network policy blocks — that leg
runs in an ESPN-allowlisted environment (per Aisha's benchmark setup).

**Health classification (`SavedPlan.health`).**
- **Broken** — infeasible given `picks` (a `_validate_pool_feasibility` cause
  fires, or the re-solve returns no roster).
- **At risk** — feasible, but the roster is **fragile**: it depends on a *scarce*
  rostered target, defined concretely as a player that is both (a) **load-bearing**
  — removing them from the pool makes the plan Broken — and (b) **hard to replace**
  — after removing them, **≤2** still-available players can fill their slot within
  the plan's remaining budget and position need, *or* they sit at ≥**90th
  percentile** projected value with no near-substitute at that position.
  `health_reason` names the player.
- **Alive** — feasible and not fragile by the above test.

The `≤2`-replacement count and 90th-percentile cutoff are tunable constants pinned
by the health tests (§5).

**UI (React) — the `DraftPage` rebuild** (per mockup; components):
`OnTheBlockBar` (manual player set + triage + max + Sold-to actions) ·
`AddCorrectPick` (search + price + team dropdown + undo) · `NextMoveCard`
(primary target + precomputed fallback line) · `PivotPlansStrip` (portfolio +
health + active switch + "warm" indicator) · `RosterPlanTable` (D5 rows + 9-cat
heat) · rail: `BudgetMeter`, `CategoryCoverage`, `BestValueBoard`, `RecentPicks`,
and a `Planned` `LeagueLandscape` placeholder (not implemented). Dark-first
token theme; responsive collapse to the phone live-companion (D4).

## 5. Test plan

- **Optimizer diagnostics (unit).** For each infeasibility cause (budget gone,
  position exhausted, category target unreachable, too few value players): assert
  a typed diagnosis + a ranked relaxation candidate, not a raw exception.
- **Iterative relaxation.** With every saved plan Broken, the relaxation sweep
  re-solves dropping each of the 9 categories, returns the lowest-cost *feasible*
  relaxation with a confirmable pick, and caches it; assert a result comes back and
  the value-board floor was shown throughout.
- **Portfolio & diversity.** Each D8 strategy shape produces the expected solver
  parameterization (punt = category absent from `set_requirements`, etc.); the
  resulting plans are *distinct* (assert roster overlap below a threshold, e.g.
  ≤8/13 shared), individually feasible, up to 10. *(Implemented —
  `tests/test_draft_strategies.py` unit + `tests/test_plan_diversity_integration.py`
  real-pool integration; both green.)*
- **Health classification.** Construct pool states that exercise Alive / At-risk
  (load-bearing + hard-to-replace player) / Broken; assert the right label and that
  `health_reason` names the scarce player.
- **Auto-advance (integration).** Scripted pick sequence that snipes plan A's
  target → app switches to the top still-Alive plan **without** a fresh solve;
  assert the served `next_target` came from cache.
- **Never-empty (integration).** Pick sequence that breaks *all* saved plans →
  `/relax` returns a confirmable pick, and a value-board fallback is present
  throughout. No state returns an empty recommendation.
- **Triage.** Relevant vs safe-to-pass correctness; `max_bid` respects remaining
  budget and roster feasibility.
- **Manual-first e2e.** Simulate a full 13-round auction via `POST .../pick`
  only, no ESPN feed → completed valid roster.
- **Undo.** Undo last and undo-specific restore budget/rosters/plan-health to the
  pre-pick state (property: log then undo == identity).
- **Frontend.** `npm run lint` + `npm run build`; desktop and phone layout
  snapshots; light and dark themes both legible; no horizontal body scroll.
- **Benchmark regression (CI).** Assert single solve < 5s and 10-plan generation
  < 60s against a fixture projection set, so solver regressions fail the build.
- **Persistence round-trip.** Serialize a `DraftSession` to localStorage, reload,
  deserialize → identity; a `schema_version` bump migrates (or resets) cleanly.
- **Concurrency / rapid picks.** Fire 3 `pick` POSTs in rapid succession; assert
  all are applied, final state is correct, and stale-`picks_version` responses are
  discarded (no out-of-order application).

## 6. Rollback / failure considerations

- **Blast radius is contained.** This replaces the Draft page stub; In-Season,
  Recap, and Season pages are untouched. Ship behind a route/flag so the old stub
  can be restored instantly.
- **Resilience engine is additive.** If background warming misbehaves, the app
  degrades to on-demand single-plan solving (today's behavior) — slower pivots,
  but correct. The optimizer path itself is unchanged for the single-plan case.
- **The never-empty guarantee has a floor.** The best-available-by-value board is
  computable directly from the active `ProjectionSet` with **no optimize call**,
  so even a total solver failure still yields a pick.
- **Manual-first removes the biggest external dependency.** No live ESPN auction
  feed is required (§0 D7/D11); ESPN's live auction state is not reliably exposed
  by the unofficial APIs, so we do not build on it. If a future sync is added, it
  only pre-fills `PickLogEntry`s and may fail silently without affecting the loop.
- **Failure modes to design for:** solve exceeds the between-pick window (always
  fall back to cache/value board; never block the UI); duplicate/typo player
  entry (validate against the projection set, offer close matches); undo of a
  non-last pick (recompute from the full `picks` log, not incremental patching —
  this triggers a full portfolio re-solve, ~42s, so the UI shows a spinner and
  keeps the value board live meanwhile); stale portfolio after a hand-tune
  (invalidate + rewarm on plan edit).

---

## Open questions for Aisha (technical review)

Resolved with Patrick 2026-07-09 (recorded here so they're not re-litigated):
- **State & persistence** — v1 is client-authoritative state + local autosave
  (D12); backend stays stateless and recomputes per pick. Durable server session
  is deferred to the resume-anywhere upgrade. *Aisha still owns the recompute
  execution model (sync vs async/stream) — see §4.*
- **Plan diversity** — user-selectable strategy shapes (balanced, punt one/more,
  spread value, stars & scrubs), all expressed as "constrain categories, maximize
  one" (D8). Target 10 plans, validated against solve time.

Resolved by Aisha's technical review 2026-07-09
([`DRAFT_ROOM_REVIEW.md`](DRAFT_ROOM_REVIEW.md)):

1. **Solver performance & warm cache** — benchmarked: ~3.77s/solve, ~42s for a
   cold 10-plan generation (prep only). Per-pick workload is health checks (<100ms)
   + 0–2 re-solves (0–8s), synchronous in the common case, SSE for a >3-plan
   cascade. cvxpy does not warm-start (structurally blocked; irrelevant at ~3.77s).
   Documented in §4. Target of 10 plans holds, guarded by the CI benchmark test.
2. **Shadow prices / IIS** — the cvxpy → HiGHS MILP stack exposes neither, so v1
   uses **iterative** relaxation (§4/§5); LP-relaxation duals (CLARABEL) are a
   documented future upgrade.
