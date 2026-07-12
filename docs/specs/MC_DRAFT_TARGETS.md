# Feature Spec: Monte Carlo draft category targets

**Status:** IMPLEMENTED on branch `feat/mc-draft-targets`, pending Aisha's
review of both spec and code (touches the approved Draft Room optimizer, so
architecture sign-off per `docs/AISHA_OPERATING_MANUAL.md`). Engine ported to
`draft_targets_mc.py`; wired into `OptimizeLineup.set_requirements` as the
default; 12 engine tests pass (`tests/test_mc_draft_targets.py`).

**Amendment (2026-07-10):** the line above originally said the optimizer
integration test "needs live ESPN and is not in the automated suite" — that
turned out to be wrong, and correcting it is what surfaced a real bug. MC
targets are history-independent by design (§0), so `set_requirements` at its
new default needs **no ESPN connection at all** — the one thing every other
target-setting test in this repo had to mock away for unrelated reasons (the
*old* method's ESPN dependency) doesn't apply here. Once that was noticed and
a real, unmocked solve was actually run
(`tests/test_plan_diversity_integration.py::test_default_recipe_solves_for_real_with_mc_targets_and_stays_bounded`,
new), it found `cp.Problem.solve()` had no time limit and several
category/percentile combinations in the Draft Room's original defaults took
8–24s+ or hung outright. Fixed in
[`DRAFT_ROOM.md`](DRAFT_ROOM.md#3-data-model-impact)'s matching amendment:
`config.SOLVER_TIME_LIMIT_SECONDS` bounds every solve, and
`draft_strategies.STRATEGY_PERCENTILE_BANDS` was retuned to a range that's
reliably fast against real MC targets. Nothing in *this* spec's own claims
(§2.5's "<a few seconds for n_teams=1000") was wrong — that's target
*computation* time (confirmed ~1.2s) and always was; the slow part was the
*optimizer's* solve using those targets, one layer downstream, which this
spec's test plan didn't cover and correctly scoped as the Draft Room's
concern, not this feature's.
**Author:** Claude Code (implementation engineer)
**Date:** 2026-07-09
**Decision basis:** Patrick asked to bring back his existing Monte Carlo work
(2026-07-09) and scoped it to the **draft category-target** piece
(`monte_carlo_targets.py` from the v1 `fantasy_bball` codebase — already written,
~340 lines of working logic). Not a rewrite: we port his logic into a clean
importable module and wire it into the draft optimizer.

---

## 0. Context: two ways to set draft targets

The draft optimizer (`optimize_lineup.OptimizeLineup`) maximizes one category
subject to per-category floor **targets** (`self.requirements`). Today those
targets come from `get_target_stats()`:

- **Current (historical):** `league.get_universe_wins(weeks=[w])[cat].quantile(p)`
  averaged over past weeks → "what a top-`p` team *scored* in real matchups last
  season." Backward-looking, and **requires league history** to exist.

Patrick's MC method is an alternative source for the same targets:

- **Monte Carlo:** `monte_carlo_drafts_13team_daily()` simulates ~1,000 realistic
  drafts from *this season's* projected player pool under the real roster
  template (PG, SG, SF, PF, C, G, F, UTIL×3, BN×3; max 3 C; $200 budget), then
  `mc_targets_from_percentile()` takes the `p`-th percentile team per category.
  Forward-looking, grounded in the current pool, and needs **no history**.

The MC method's history-independence is the reason to bring it in now: it works
on day one for a new league or new user (Decision A — wider launch).

## 1. User story

> As a manager prepping a draft, I want my category targets derived from
> simulating real drafts of this year's player pool — not from last season's
> box scores — so the optimizer aims at goals that are actually achievable given
> who's available, even in a brand-new league with no history.

## 2. Acceptance criteria

1. The optimizer can source its `requirements` from **either** method, selected
   by a parameter (`target_method="historical" | "monte_carlo"`). **Default is
   `monte_carlo`** (Patrick, 2026-07-09) — it's history-independent, so it works
   for every league including brand-new ones. `historical` remains available as
   an explicit opt-in.
2. `mc_targets_from_percentile()` output plugs into the existing
   `set_requirements()` path with **no change to `optimize_roster()`**.
3. MC runs on the same projected player pool the optimizer already loads (one
   source of truth for players/prices/values), via a documented column mapping —
   no second Excel read.
4. MC target generation is **deterministic** given a seed (reproducible drafts).
5. A given category set + percentile returns targets in < a few seconds for
   n_teams=1000 (validate; expose `n_teams` if we need to trade accuracy for
   speed).
7. Per-game projections are scaled to per-week by a single documented constant
   **`GAMES_PER_WEEK = 3.5`**, not the old hardcoded 3.6 and not a per-player
   schedule derivation (Patrick, 2026-07-09 — a blanket season-average is the
   right precision for target-setting). Derivation: 82 games ÷ ~23.4 *playable*
   weeks (regular season minus the All-Star break) ≈ 3.5, consistent with the
   fantasy-standard 3–4 games/week. Lives in `config.py` as one tunable value.
6. TO is handled with the correct sign convention (lower is better) consistently
   with the optimizer and the projection framework — asserted by a test.

## 3. Data model impact

None persisted. MC produces an in-memory `{category: float}` dict, same shape as
today's targets. No new tables, no migration. (If we later cache simulated-team
distributions, that's a follow-up — not in scope.)

## 4. API / UI impact

- **Internal:** new module `draft/targets_mc.py` (port of `monte_carlo_targets.py`:
  `normalize_columns`, `add_eligibility_flags`, `_softmax`,
  `monte_carlo_drafts_13team_daily`, `mc_targets_from_percentile`), plus a thin
  adapter that maps the optimizer's `player_data_df` columns
  (`PTS`→`PTS_PG`, `$`/`Value`→`Price`/`Value`, `Pos`→`is_PG…is_C`) into the
  shape the MC functions expect.
- **`OptimizeLineup`:** `set_requirements(..., target_method=...)` gains the MC
  path; `get_target_stats` stays as the historical path.
- **API:** the draft-plan endpoints (`/draft/plans` and the multiple-plans path)
  gain an optional `target_method` field, default per §2.1. No new endpoint.
- **UI:** Draft Room shows which target method produced the current plan
  (one line, e.g. "Targets: Monte Carlo p80"). Full surfacing can follow the
  DraftPage work already in flight; minimum is the label.

## 5. Test plan

- **Port fidelity:** golden test — same seed + same fixture pool → identical
  targets to the v1 `mc_targets_from_percentile()` output (guards the port).
- **Shape contract:** MC targets dict has exactly the 9 category keys the
  optimizer expects, all finite, FG%/FT% in [0,1].
- **TO sign test:** MC target for TO is treated as "lower is better" end-to-end
  (roster chosen under an MC TO target doesn't blow past it).
- **Determinism:** two runs, same seed → identical; different seed → different
  but same-order-of-magnitude.
- **Integration:** `optimize_roster()` produces a valid 13-man roster when fed
  MC targets, for both a punt and a balanced category set.
- **History-independence:** MC path runs with `league` history unavailable
  (mock) and still returns targets; historical path raises/falls back as designed.
- **Perf guard:** n_teams=1000 completes under the §2.5 budget on CI.

## 6. Rollback / failure considerations

- **Additive + flagged:** the historical method stays the default-eligible path;
  `target_method="historical"` is a one-argument rollback with identical prior
  behavior. No existing call site changes meaning unless it opts in.
- **Infeasible pool:** `monte_carlo_drafts_13team_daily` already raises
  `RuntimeError` if it can't build feasible teams (e.g. pool too small/expensive).
  The optimizer must catch this and fall back to the historical method (or a
  clear error), never crash a draft-day request.
- **Determinism seed** is pinned in config so results don't shift under the user
  mid-draft.
- **Column-mapping drift:** if the optimizer's player columns change, the adapter
  fails loudly with a named-column error (not silent bad targets) — same posture
  as the projection framework.

---

## Resolved by Patrick (2026-07-09)

- **Default method:** Monte Carlo, outright (see §2.1).
- **Games per week:** single documented constant `GAMES_PER_WEEK = 3.5` in
  `config.py` (see §2.7); no per-player schedule derivation.

## Open questions for Aisha

1. **Where MC lives long-term:** ship `draft/targets_mc.py` now as a standalone
   port, or hold until the backend package restructure so it lands in its final
   home? (Aisha flagged restructure-first in the projection review.)
2. Coordinate with the **projection-source framework**: MC wants normalized
   per-game stats + price/value, which is exactly `PlayerProjection`. Should the
   MC adapter consume `PlayerProjection` directly once that framework lands,
   retiring the column-mapping shim?
