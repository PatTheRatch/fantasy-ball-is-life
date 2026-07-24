# Feature Spec: Trade Analyzer

**Status:** Product direction set by Patrick (owner) 2026-07-24 — pending
Aisha's technical review before implementation (per
`docs/AISHA_OPERATING_MANUAL.md`).
**Author:** Claude Code (implementation engineer)
**Date:** 2026-07-24
**Decision basis:** Extends the Streaming Advisor's valuation engine
(`STREAMING_ADVISOR.md` S-2: per-category expected contribution + season
surplus-over-replacement) from waiver moves to **trades** — the other big
in-season decision. Mostly machinery reuse; the new idea is the
**fairness vs fit** split.

---

## 1. User story

> My leaguemate offered me their PG for my C. Is this fair? And even if it's
> fair in a vacuum — does it actually help *my* build, in *my* matchup
> categories, for the rest of *this* season?

## 2. The core idea: fairness ≠ fit

Every trade gets two independent verdicts:

1. **Fairness (context-free):** sum of season-horizon player values
   (surplus-over-replacement, same 9-cat value math the draft optimizer's
   `value_col` uses) on each side. Answers "is this a rip-off?" — the number
   every league argument wants.
2. **Fit (context-full):** apply the trade to *your* roster, recompute your
   projected per-category profile vs the league, and show the deltas.
   Answers "does this help YOU?" A perfectly fair 2-for-1 can still be wrong
   for your build (you traded your only blocks source), and a slightly
   "unfair" trade can still be right (you're punting the category you gave
   up). Category deltas are shown against your rest-of-season league
   ranking per category — the same normalized margins the advisor's gap
   analysis uses, aggregated to season scope.

Deterministic math, no LLM in the verdict (optional narrative later, same
policy as the advisor).

## 3. Pipeline

1. **Input:** two team names + player lists per side (1-for-1 up to
   3-for-3), from the league's current rosters. v1 is *evaluate a proposed
   trade*, not *search for trades to propose* (see §7).
2. **Valuation (reused):** the advisor's S-2 module — season per-game value
   per player, surplus over replacement, per-category expected contribution.
   Projection source = the framework's active season source (BBM today, FCP
   later — free upgrade).
3. **Fairness:** Σ surplus each side, with an uncertainty band (± based on
   projection confidence) so near-ties read as "even" not false precision.
4. **Fit, per side:** post-trade roster → projected per-category totals →
   category-rank deltas vs the league (e.g. "AST: 7th → 3rd; BLK: 4th →
   9th"). Roster-slot sanity: flag if the trade leaves an illegal/undraftable
   position mix.
5. **Output:** verdict card — fairness meter + both teams' category deltas +
   flags ("this trades away your only C").

## 4. API + UI

- `POST /leagues/{slug}/trade-analyzer` with
  `{team_a, players_a[], team_b, players_b[]}` → verdict payload. Stateless,
  on-demand; no persistence in v1 (a saved-trades log is a later nicety).
  Public-read like other league endpoints — anyone in the league can evaluate
  any hypothetical (it's all data the league can already see).
- UI: **"Trade Analyzer"** page under the league (`/leagues/:slug/trade`),
  linked from the More menu. Two roster-picker columns (players from the
  latest snapshot's rosters), verdict card below, auto-updating as players
  are picked (D-P6: no "Analyze" button needed once both sides are non-empty).

## 5. Phases

| Phase | Scope | Depends on | Done when |
|---|---|---|---|
| **T-1** | Verdict engine: fairness (Σ surplus ± band) + fit (per-category rank deltas) on top of the advisor's valuation module | Advisor S-2 | Hermetic tests: fair/unfair goldens; the punt case (unfair-but-fits flagged as such); 2-for-1 roster-count handling |
| **T-2** | `POST /leagues/{slug}/trade-analyzer` endpoint | T-1 | Contract tests: unknown team/player 404s; response shape; determinism |
| **T-3** | UI page + More-menu link (slug-scoped route + query keys per N-3 rules) | T-2 | Vitest: pickers populate from rosters; verdict renders both verdicts; empty/error states |

Sized like an N-4-style slice series; T-1 is the only real thinking.

## 6. Test plan

- Golden trades: star-for-scrubs (unfair), balanced 1-for-1 (even within
  band), fair-but-bad-fit (fairness ✅, fit shows a category cratering).
- Ratio categories recomputed via makes/attempts post-trade; TO inverted.
- Property: analyzer(A→B) is the exact mirror of analyzer(B→A).
- Meta: clean-env + `spec=` mocks.

## 7. Risks & open questions

- **Depends on Advisor S-2 existing** — sequencing: build the advisor's
  valuation module first; the trade analyzer is its second consumer (which
  also pressure-tests the module's API).
- **Value model honesty:** fairness is only as good as the active projection
  source; show the source badge (the framework's UI rule) on the verdict.
- **Open:** include rest-of-season schedule (games remaining per team) in
  fit? Cheap to add; decide in T-1.
- **Open:** multi-team trades (3-way) — out of v1, revisit on demand.

## 8. Out of scope (v1)

- Trade *finder* ("suggest trades I should offer") — a search layer over the
  same engine; big combinatorial surface, later.
- Keeper/dynasty valuation horizons.
- Executing or messaging trades on ESPN.
- Persistence/history of analyzed trades.
