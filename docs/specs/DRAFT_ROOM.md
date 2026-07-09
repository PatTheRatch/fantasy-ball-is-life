# Feature Spec: Draft Room — redesigned optimizer + draft-day resilience

**Status:** Design decisions locked by Patrick (product owner) 2026-07-09 —
pending Aisha's technical review before implementation. The resilience engine
(§3–§4) changes how the optimizer is invoked and adds background solving, so it
needs architecture sign-off per [`docs/AISHA_OPERATING_MANUAL.md`](../AISHA_OPERATING_MANUAL.md).
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
| D8 | Plan portfolio | Save **5–10** diverse plans. **Auto-generate the set, then hand-tune.** Each shows live health |
| D9 | When a plan breaks | **Auto-advance** to the next live plan (instant). Re-solve with relaxation only if *all* break |
| D10 | Relaxation control | **Auto-propose, one-tap confirm** before it becomes active |
| D11 | Live ESPN sync | **Optional future accelerator only** — never a dependency (see §6) |

**Deferred to a later spec (explicitly out of scope here):** the "League
landscape" panel — most-similar build, your kryptonite, league-wide budget/
inflation. Shown as a `Planned` placeholder in the mockup; no implementation now.

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
   set of plans (target 5–10); the user keeps/tunes/saves them. During the draft
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

No database (consistent with the rest of the app — on-disk / session state).
Three new structures, held in a **server-side draft session** (see §4 note on why
the portfolio can't live only in the browser):

**`DraftSession`** — one active draft.

| Field | Notes |
|---|---|
| `session_id` | opaque id |
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

## 4. API / UI impact

**Optimizer / backend.** Extends the existing `POST /optimizer/optimize` and the
already-present `generate_multiple_plans` in `optimize_lineup.py`. New/changed:

- `POST /draft/session` — create/reset a draft session (params from §3). Returns
  `session_id`.
- `POST /draft/{id}/plans` — generate the diverse portfolio for prep (target
  5–10 plans via `generate_multiple_plans`), returns `SavedPlan[]` with strategy
  labels. `PUT /draft/{id}/plans/{plan_id}` to hand-tune and save (D8).
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
This builds directly on the merged `_validate_pool_feasibility`. Required:
- classify the infeasibility cause (budget / position / category / value-player);
- expose the LP **dual values (shadow prices)** so relaxations rank by cost
  without iterating over every category (see §5/§7 notes);
- surface an infeasibility certificate / irreducible infeasible subset so we
  relax only the constraints actually at fault.

**Warm pivot cache (the "never freeze" mechanism).** After each `POST .../pick`,
the backend recomputes the plan portfolio in the background so that "if the
current target is sniped, the next move is X" is **precomputed before the miss**.
Between picks there is normally ample wall-clock time (other managers nominating
players the user doesn't want). This is why the portfolio lives server-side — the
browser can't run cvxpy. **Open architecture question for Aisha:** where/how the
background recompute runs (async task in-process vs a small worker), and whether
warm-start between solves is feasible with the current solver.

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
- **Shadow-price ranking.** Given a solved plan, the proposed relaxation is the
  minimum-cost binding constraint (no brute-force over all 9 categories).
- **Portfolio.** `generate_multiple_plans` yields N *distinct*, individually
  feasible plans; diversity assertion (different punts/shapes), 5–10 range.
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
  non-last pick (recompute from the full `picks` log, not incremental patching);
  stale portfolio after a hand-tune (invalidate + rewarm on plan edit).

---

## Open questions for Aisha (technical review)

1. **Where does the warm recompute run?** In-process async vs a worker; is a
   persistent server-side `DraftSession` acceptable, or should state be
   client-held and posted each solve? (§4)
2. **Solver performance.** Is cvxpy fast enough to recompute a 5–10-plan
   portfolio within a typical between-pick gap? Does it warm-start from the prior
   solution when one player is removed? Benchmark needed before committing to the
   "warm cache" promise.
3. **Shadow prices / IIS.** Does the current solver backend expose dual values
   and an infeasibility certificate we can read for constraint ranking, or do we
   need to switch backends?
4. **Diversity definition.** How `generate_multiple_plans` should parameterize
   "diverse" (punt strategies, stars-and-scrubs vs balanced) for the portfolio.
