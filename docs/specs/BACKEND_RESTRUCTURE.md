# Feature Spec: Backend package restructure

**Status:** APPROVED by Aisha (2026-07-12, in the PR #12 review) — all three
open questions resolved (see "Resolved by Aisha" below). Cleared for
implementation once PR #12 merges. This is the restructure her
projection-framework review flagged as "restructure-first," and it resolves
`MC_DRAFT_TARGETS.md` open question #1.
**Author:** Claude Code (implementation engineer)
**Date:** 2026-07-12
**Decision basis:** Patrick (2026-07-12): before the next feature (weekly
recap automation, dossier Decision D), do the long-deferred cleanup — "that
flat file structure is not great… we never really scaffolded this project."
The dossier has carried "Restructure the flat backend into a package" as an
open item since consolidation, and every feature since has widened the flat
layout (13 top-level modules at the time of writing, 6 of them draft-related).

---

## 0. Why now, concretely

- `api.py` is 2,227 lines / 34 endpoints in one file, mixing league data,
  three AI-commentary endpoints (with large inline prompt blobs), all six
  Draft Room endpoints plus their private helpers, the auction simulator,
  and projections upload. It is the first file anyone evaluating this
  codebase opens.
- The Draft Room is now six sibling modules (`optimize_lineup`,
  `draft_engine`, `draft_strategies`, `draft_targets_mc`, `player_values`,
  `auction_values_mc`) with no grouping — the MC spec explicitly asked
  where this should live long-term (open question #1: "ship
  `draft/targets_mc.py` now… or hold until the backend package
  restructure?"). This spec is the answer: the package restructure happens
  first, and MC lands at `backend/draft/targets_mc.py`.
- The next feature (recap scheduling + delivery) wants a natural home for
  scheduler/delivery code; today there is nowhere to put it that isn't
  another root-level module.
- Sellability (Patrick, 2026-07-12): the project should be organized well
  enough to sell later. A conventional package layout is table stakes for
  that.

## 1. User story

> As the owner (and possible future seller) of this codebase, I want the
> backend organized as a conventional Python package with one module per
> concern, so a new engineer (or a buyer's reviewer) can find the draft
> engine, the ESPN layer, and the API surface without reading a 2,200-line
> file — and so the next feature lands in an obvious place.

## 2. Acceptance criteria

1. All backend modules live under a `backend/` package, grouped by concern
   (§4 layout). No root-level `.py` files except `app.py` (Streamlit
   internal tool, which imports from the package).
2. **Zero wire-format changes.** Every endpoint keeps its exact path,
   request schema, and response schema. The frontend requires no changes
   beyond none at all — `frontend/src/api.ts` is untouched.
3. **Zero behavior changes.** Pure moves + import updates + mechanical
   `api.py` splitting. Any real refactor found along the way is deferred to
   its own change.
4. The full test suite passes unchanged in count (106 at time of writing;
   test files update imports only).
5. `git mv` (or equivalent) preserves file history through the moves.
6. The uvicorn entrypoint changes once, documented in README and
   `.github/workflows/ci.yml` if referenced: `uvicorn backend.api.main:app`.
7. Done in **two PRs** to stay reviewable (§4 phasing), each green under the
   new CI gate.

## 3. Data model impact

None. No persisted data, no schema, no migration. `config.py` moves but its
env-var names and defaults are unchanged.

## 4. API / UI impact

No externally visible API or UI change (criterion 2). Internal layout:

    backend/
      __init__.py
      config.py                  # moved as-is
      league/                    # ESPN integration layer
        data_feed.py
        fantasy.py               # MyLeague (power rankings, universe wins)
      draft/                     # the Draft Room engine
        optimizer.py             # <- optimize_lineup.py
        engine.py                # <- draft_engine.py (per-pick recompute)
        strategies.py            # <- draft_strategies.py
        targets_mc.py            # <- draft_targets_mc.py  (MC spec Q1 answer)
        values.py                # <- player_values.py (Forge Value)
        auction_sim.py           # <- auction_values_mc.py
      analytics/
        consistency.py
      commentary/
        prompts.py               # prompt blobs lifted out of api.py
        generate.py              # Anthropic client calls
      projections/               # reserved (Aisha Q3): projection-source
        __init__.py              # framework adapters land here; empty for now
      api/
        main.py                  # FastAPI app factory + shared deps
        routers/
          league.py              # /league/*, /power-rankings, /rosters, ...
          draft.py               # /draft/* + _build_pool_context etc.
          commentary.py          # /matchup-commentary, /league-recap, /season-commentary
          projections.py         # /projections upload + feed
          optimizer.py           # legacy /optimizer/* endpoints
    app.py                       # Streamlit internal tool (root), imports backend.*
    tests/                       # imports updated, structure unchanged

**Phasing:**

- **PR 1 — the move + rename.** `git mv` modules into the package **with
  their new basenames** (Aisha Q2: rename now — `optimize_lineup.py` →
  `draft/optimizer.py`, `draft_strategies.py` → `draft/strategies.py`, etc.),
  update imports everywhere (tests, `app.py`), add the empty reserved
  `backend/projections/__init__.py` (Aisha Q3), and keep `api.py` intact as
  `backend/api/main.py` plus the deprecated root shim (§6). Mechanical;
  reviewable as a rename diff.
- **PR 2 — split `api.py`.** Extract the routers and the commentary module
  from `main.py`. This is the only part with real surgery, so it gets its
  own review. Router extraction is FastAPI-conventional
  (`APIRouter` + `include_router`), no handler logic edited.

**Renaming resolved (Aisha Q2, 2026-07-12): rename in PR 1, not later.** The
package prefix supplies the context the old basename carried, so the
redundant prefix drops — that navigability *is* the point of the restructure.
`git mv` preserves history; CI + the test suite catch any missed import.

## 5. Test plan

- Full suite green after each PR, same test count (106) — the suite itself
  is the primary guard since this is behavior-preserving.
- CI (new, `.github/workflows/ci.yml`) gates both PRs on a bare checkout —
  which also proves no import silently depends on the old layout.
- Manual smoke after PR 1 and PR 2: `uvicorn backend.api.main:app` boots;
  `/health` 200; one `/draft/plans` round trip against the ESPN-isolated
  launcher (same pattern the test suite uses); `streamlit run app.py` boots.
- `pip install -e .`-style packaging is explicitly **out of scope** (no
  `pyproject.toml` build config yet — the repo is an app, not a library).

## 6. Rollback / failure considerations

- Each PR is a single squash-merge revert away from the prior layout; no
  data or schema involvement means revert is complete rollback.
- The riskiest failure is an import cycle exposed by the moves
  (e.g. `draft/` ↔ `league/`): today `optimize_lineup` imports `fantasy`
  and `config` only, and the pure modules (`engine`, `strategies`) import
  nothing heavy — cycles are unlikely, but PR 1 will fail fast in CI if one
  appears, before any router surgery is attempted.
- Deployment entrypoint drift: anything outside this repo that runs
  `uvicorn api:app` (shell history, a server config) breaks on PR 1.
  Mitigation: keep a root-level `api.py` shim (`from backend.api.main import
  app`) for one release, marked deprecated, then delete it in PR 2.

---

## Resolved by Aisha (2026-07-12, PR #12 review)

1. **§4 layout — approved as written.** `commentary/` as its own package is
   correct: it currently holds 3 endpoints with large inline prompt blobs,
   and `commentary/prompts.py` is the natural home for them (separating
   prompts from routing is "the key cleanup this restructure enables").
2. **Rename now** (not a later chore) — `optimize_lineup.py` →
   `draft/optimizer.py`, `draft_strategies.py` → `draft/strategies.py`, etc.
   The package prefix supplies the context; dropping the redundant prefix is
   the point. Folded into the §4 phasing above.
3. **Reserve `backend/projections/` now.** Add an empty
   `backend/projections/__init__.py` in PR 1 so it isn't a second rename
   cycle when the projection-source framework lands. Added to the §4 layout
   and PR 1 phasing.
