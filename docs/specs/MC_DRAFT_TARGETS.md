# Feature Spec: Monte Carlo draft category targets

**Status:** DRAFT — pending Aisha's technical review before implementation
(touches the approved Draft Room optimizer, so architecture sign-off per
`docs/AISHA_OPERATING_MANUAL.md`).
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
   by a parameter (`target_method="historical" | "monte_carlo"`), defaulting to
   `monte_carlo` when no league history is available and `historical` otherwise
   (final default is Aisha's/Patrick's call — see §Open questions).
2. `mc_targets_from_percentile()` output plugs into the existing
   `set_requirements()` path with **no change to `optimize_roster()`**.
3. MC runs on the same projected player pool the optimizer already loads (one
   source of truth for players/prices/values), via a documented column mapping —
   no second Excel read.
4. MC target generation is **deterministic** given a seed (reproducible drafts).
5. A given category set + percentile returns targets in < a few seconds for
   n_teams=1000 (validate; expose `n_teams` if we need to trade accuracy for
   speed).
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

## Open questions for Aisha / Patrick

1. **Default method:** auto (MC when no history, else historical) as proposed, or
   make MC the outright default now that we're building for new leagues too?
2. **Where MC lives long-term:** ship `draft/targets_mc.py` now as a standalone
   port, or hold until the backend package restructure so it lands in its final
   home? (Aisha flagged restructure-first in the projection review.)
3. **`avg_games_per_week`** is a hardcoded 3.6 knob in the v1 code. Keep as a
   constant, or derive per-player from the schedule (better, but more work)?
4. Coordinate with the **projection-source framework**: MC wants normalized
   per-game stats + price/value, which is exactly `PlayerProjection`. Should the
   MC adapter consume `PlayerProjection` directly once that framework lands,
   retiring the column-mapping shim?
