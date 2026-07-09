# Technical Review: Draft Room Spec

**Reviewer:** Aisha (lead systems engineer)
**Date:** 2026-07-09
**Spec under review:** `docs/specs/DRAFT_ROOM.md` (commit `6c37856`)
**Verdict:** ⚠️ **Approved to implement with one gate item and six spec amendments.**
Gate 1 is resolved (see revised analysis below); Gate 2 remains open but has a
workable v1 path.

---

## Gate Item 1: Solver Performance & Execution Model ✅ Resolved

### Benchmark results

| Scenario | Time | Notes |
|---|---|---|
| Single solve | **3.77s** | 564-player pool, 13 roster spots |
| 10 plans from scratch (`generate_multiple_plans`) | **42.45s** | One-time prep cost — not the per-pick workload |

These are measured on the VPS against the live BBM projections file.

### What actually happens per pick (the live-draft workload)

The 42s number is misleading — it's the **portfolio generation** cost
(pre-draft prep, or after a full reset). During a live draft, the per-pick
workload is much lighter:

1. **Health checks** (all 10 plans): each is an O(1) string lookup — is the
   drafted player in this plan's roster? The ban-diversity mechanism in
   `generate_multiple_plans` ensures plans target different top players, so
   a given pick typically breaks 0–2 plans, not all 10. <100ms total.

2. **Re-solves** (only broken plans): 0–2 plans × ~4s = **0–8s**.

That fits comfortably in a 30–90 second between-pick window. The
"warm cache" model works synchronously for the common case.

**The one scenario that needs a fallback:** a pick that breaks >3 plans
simultaneously (unusual — would require the same player appearing as a
target across many plans despite the ban mechanism). For that edge case,
return health statuses synchronously and re-solve in background, streaming
results via SSE. The spec should document both paths: sync for the common
case, async degradation for the rare cascade.

### Does cvxpy warm-start from the prior solution?

Technically no — each call creates fresh `cp.Variable` and `cp.Problem`
objects. But this doesn't matter because **we're not re-solving the same
problem**. When a player is drafted, the variable dimensions shrink (one
fewer boolean in the pool), so warm-start is structurally blocked regardless
of solver. The performance is still fine (3.77s per solve).

### What the spec needs to change

Document the per-pick execution model in §4:

> "On pick-log, the backend runs synchronous health checks on all saved
> plans (O(1) lookups, <100ms), then re-solves any plan whose roster lost
> the drafted player. In the common case (0–2 plans affected), the full
> response returns within 8 seconds — well within a typical between-pick
> window. If >3 plans break simultaneously, health statuses return
> immediately and remaining re-solves stream via SSE."

No architecture change needed — this is a spec clarification, not a redesign.

---

## Gate Item 2: Shadow Prices & IIS

### What the spec claims

> "expose the LP dual values (shadow prices) so relaxations rank by cost
> without iterating" (§4)
>
> "surface an infeasibility certificate / irreducible infeasible subset so we
> relax only the constraints actually at fault" (§4)
>
> "the proposed relaxation is the minimum-cost binding constraint (no
> brute-force over all 9 categories)" (§5)

### What the solver stack actually provides

**Current setup:** cvxpy → HIGHS (MILP solver, auto-selected for boolean
variables).

| Capability | HIGHS (MILP) | CLARABEL (LP, used for continuous) |
|---|---|---|
| Solves boolean problems | ✅ Yes | ❌ No |
| Dual values (optimal) | ❌ `None` | ✅ Available |
| Dual values (infeasible) | ⚠️ Partial (from pre-solve only) | ✅ Available |
| IIS certificate | ❌ Not exposed | ❌ Not exposed |

**In short: the current stack gives us neither reliable duals nor an IIS.** The
partial duals from HIGHS on infeasible models (I got `[-0.0, 1.0, 1.0]` on a
toy problem) are from the LP pre-solve phase and can't be trusted for ranking.

### LP relaxation workaround

You *can* solve the LP relaxation (drop `boolean=True`) with CLARABEL and get
real dual values. But those duals are for the *relaxed* problem — they tell you
which constraint binds in a world where you can draft 0.3 of a player. The
ranking they give may or may not match the actual MILP binding order. In
practice, for a 500+ variable model, LP relaxation duals often correlate with
MILP binding — but there's no guarantee.

### What the spec needs to change

Three options, ranked:

1. **Iterative relaxation (lowest risk, fits current stack).** For each
   category constraint, re-solve with it dropped. 9 categories × ~4s = ~36s
   worst-case. Since this only runs when *all* plans are broken (rare), 36s
   is acceptable. Cache the result. The spec should document this fallback
   path explicitly.

2. **LP relaxation duals (medium risk, faster).** Solve the LP relaxation
   of the infeasible problem, read duals from CLARABEL, rank constraints by
   shadow price magnitude, re-solve with the top-1 relaxed. This is faster
   (~4s for one LP solve) but needs validation that the LP duals reliably
   identify the right constraint to relax.

3. **Commercial solver (highest quality, cost + license overhead).** Gurobi
   or CPLEX expose real MILP duals and IIS extraction. Not recommended for
   v1 — the license overhead isn't worth it for a single-user app.

**Recommendation:** Use option 1 (iterative) for v1, document option 2 (LP
relaxation) as a performance upgrade path in the spec. Update §4 and §5 to
remove the claims about shadow prices and IIS.

---

## Broader Assessment

### What's sound

- **Data model (§3) is clean.** Client-authoritative, backend stateless,
  derived-not-stored is the right call for v1. The `DraftSession` /
  `SavedPlan` / `PickLogEntry` schemas are well-shaped and map naturally to
  the UI components described in §4.

- **Never-empty guarantee (§2 criterion 2, §6) is actually achievable.**
  The best-available-by-value board (computed directly from projections, no
  solver) is a real, always-available floor. The relaxation proposal path
  adds the second layer. Even if the solver crashes entirely, the user sees
  *something* actionable. This is correctly designed.

- **Resilience engine is additive (§6).** Degrades to single-plan solving
  (today's behavior) if warming misbehaves. This is the right architecture
  for a new feature — it can be toggled off without breaking the core loop.

- **V1 scope boundary is drawn in the right place.** Same-device autosave
  (localStorage), manual-first input, no ESPN sync dependency, deferred
  League Landscape panel. None of these gate the core value.

- **Manual-first decision (D6/D7) is architecturally correct.** ESPN's
  unofficial APIs don't expose live auction state reliably. Building the
  system to not depend on it avoids the most common failure mode.

### What's risky

- **Plan diversity claim is unverified.** The spec says
  `generate_multiple_plans` yields "N distinct, individually feasible plans"
  (§5), but the current mechanism (cycling percentile + banning top-price
  player) produces plans that often share 8–10 of 13 players. The spec's
  "user-selectable strategy shapes" (balanced, punt, stars & scrubs, D8)
  haven't been mapped to solver parameters. The punts are particularly
  important — to punt a category you drop it from `set_requirements`, which
  is a simple parameterization, but the spec should document which parameter
  map corresponds to which shape.

- **Health classification is ambiguous.** "At risk (feasible but hinges on
  a scarce player)" — what makes a player "scarce"? The spec doesn't define
  the heuristic. Is it position scarcity (only 3 PF remain)? Price scarcity
  (player >90th percentile value)? A concrete definition is needed before
  implementation.

- **`SavedPlan.roster` staleness.** The spec says `roster` is "current
  computed roster given `picks`" but doesn't specify *when* this recompute
  happens. On pick-log, the backend can re-solve each plan — but if we go
  with async (Gate 1, Path A), the roster is stale between the health check
  returning and the background solve completing. The UI needs to handle the
  "stale roster" state gracefully.

- **Warm cache data structure is undefined.** §4 describes the *mechanism*
  (recompute at pick time) but not the *artifact* that the cache holds. If
  it's a dict of `{plan_id: {health, next_target, roster}}`, where does it
  live? On the client (returned in pick POST response)? On the server
  (against the stateless principle)? This needs to be explicit.

### What's missing from the spec

1. **Concurrency model.** What happens when two picks are logged in rapid
   succession (e.g., the user clicks "add pick" twice before the first POST
   resolves)? The spec needs a queuing/versioning strategy — at minimum, a
   `picks_version` counter on the client that's echoed back.

2. **localStorage persistence schema.** D12 says "same-device autosave" but
   doesn't specify the serialization format. Is it JSON of the full
   `DraftSession`? A subset? What's the migration strategy when the schema
   changes across deploys?

3. **Player name resolution in pick logging.** When a user types "Giannis"
   into the pick log, how does it resolve to the `player_key` in the
   projection set? The spec should reference the existing
   `normalize_name` + fuzzy-match pipeline from
   `PROJECTION_SOURCE_FRAMEWORK.md` and make it explicit that pick logging
   goes through the same resolver.

4. **Undo of a non-last pick.** The spec says "recompute from the full
   `picks` log, not incremental patching" (§6). This is correct for
   correctness but needs a performance note: a mid-sequence undo in a
   10-pick draft triggers a full portfolio re-solve — same cost as a new
   pick, ~40s. This is acceptable but should be documented so the frontend
   shows a spinner.

### What the test plan (§5) is missing

- **Benchmark regression test.** A test that asserts single-solve < 5s and
  10-plan generation < 60s, run in CI, so performance regressions are caught.
- **localStorage round-trip.** Save a `DraftSession`, refresh the page, load
  it back, assert identity.
- **Rapid-pick stress.** Fire 3 pick POSTs in parallel, assert all are
  processed and final state is correct.

---

## Summary

| Section | Verdict |
|---|---|
| §0 Locked decisions | ✅ Product calls, not engineering — out of scope |
| §1 User story | ✅ Clear, well-scoped |
| §2 Acceptance criteria | ✅ Measurable, covers the guarantees |
| §3 Data model | ✅ Clean, needs warm-cache artifact defined |
| §4 API/UI | ⚠️ Execution model unspecified (sync vs async) |
| §5 Test plan | ⚠️ Missing benchmark + persistence + concurrency tests |
| §6 Rollback | ✅ Correctly designed additive pattern |

**Required spec amendments before implementation:**

1. **Gate 2 — Resolve the shadow-price/IIS approach.** Replace the dual-value/IIS
   claims in §4/§5 with the iterative relaxation approach. Document the fallback
   path: value board is always available, relaxation runs only when all plans
   break (rare), and iterating over 9 categories with re-solves is acceptable
   (~36s worst-case, cached after first run).
2. **Document the per-pick execution model in §4.** Per the Gate 1 resolution
   above: health checks sync, 0–2 re-solves sync, >3 cascade uses async/SSE.
3. **Define plan diversity parameters.** Map each strategy shape (balanced,
   punt X, stars & scrubs, spread value) to concrete `set_requirements` and
   `percentiles_cycle` configurations.
4. **Define the "scarce player" heuristic** for the "At Risk" health
   classification.
5. **Specify the warm-cache data structure** — what exactly is cached, where
   it lives, and how the client consumes it.
6. **Add concurrency, persistence, and benchmark tests** to §5.

After these changes, the spec is cleared for implementation. Gate 2 needs a
quick re-check to confirm the relaxation approach is correctly documented;
everything else is editorial.
