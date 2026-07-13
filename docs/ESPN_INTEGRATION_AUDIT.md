# ESPN Integration Audit — Backlog

**Date:** 2026-07-09
**Trigger:** Patrick asked for a review of the ESPN integration (`data_feed.py`,
`fantasy.py`, `config.py`, the `/league/*` and `/rosters/*` endpoints in `backend/api/`)
before building more features on top of it — specifically the Draft Room, whose
plan-diversity engine (`draft_strategies.py`) depends on `set_requirements()`
producing correct category targets.
**Method:** initial read-only code audit, followed by a sanitized live Patriot
Games review on 2026-07-12.

This is a tracked backlog, not a feature spec — most items are independent bug
fixes / hardening, not new product decisions. Pull individual items into their
own small PRs as they're prioritized.

> **Live follow-up complete:** [`ESPN_API_REVIEW.md`](ESPN_API_REVIEW.md) is the
> canonical evidence report. It confirms the findings below, measures request
> fan-out, documents the working `mTransactions2` contract, and adds P0 items
> for recap turnover inversion and playoff ghost-team rankings.

---

## Fixed

- [x] **Category-target week sampling was wrong** — `optimize_lineup.py`
  `get_target_stats()` used a hardcoded `range(16)` with an exclusion list whose
  last four indices (17-20) were unreachable dead code, and which excluded weeks
  8-9 based on a stale assumption (they aren't the All-Star break). Fixed to
  derive the sample from `league.settings.reg_season_count` and
  `effective_current_week` (both already used elsewhere in the codebase) and to
  skip any week with no matchup data instead of guessing magic numbers. This
  directly fed `set_requirements()`, i.e. every Draft Room plan's category
  targets — see commit on this branch, tests in
  `tests/test_get_target_stats.py`.

## Correctness — should fix before relying on the affected path

- [x] **`GET /rosters/current` silently zeroes games-left for every player
  — live-confirmed. Fixed (PR D).**
  When the optional `week_start_date`/`week_end_date` query params were omitted,
  `get_current_rosters` defaulted `week_start_date="2026-10-15"` *after*
  `week_end_date="2026-04-30"`, so `count_games_in_range`'s range check was
  always false (live: 181 roster rows, zero games-left by default; the correct
  week-21 dates produced 649 player-games). Fixed both ways: a new
  `resolve_roster_week_window()` derives a forward window from the matchup
  period (falling back to the league's current week) when a bound is omitted,
  and the `/rosters/current` GET+POST endpoints return 400 on an explicitly
  inverted range. Tests in `tests/test_roster_week_window.py`.
- [x] **Recap matchup winner ignores ESPN's own tiebreak resolution — found
  reviewing a live playoff week. Fixed.** `canonical_matchups()` computed the
  matchup winner purely from its own 9-category tally and called it `"Tie"`
  whenever both sides won the same number of categories (e.g. 4-4 with one
  category tied) -- but ESPN resolves that tie itself (playoff seeding, etc.)
  via the box score's own `winner` field, which the recap facts never looked
  at. A real playoff week landed exactly on this: a 4-4 matchup that ESPN
  had already decided showed up in the recap snapshot as an undecided tie.
  Fixed: `get_current_scoreboard()` now carries ESPN's authoritative
  `winner` (`espn_winner`) alongside each stat row, and `canonical_matchups()`
  defers to it (with a `tiebreak_resolved` flag) only when its own tally is
  genuinely tied -- a decisive tally is never overridden. Tests in
  `tests/test_recaps.py` and `tests/test_scoreboard_turnovers.py`.
- [ ] **Recap turnover winners are reversed — live-confirmed.**
  `get_current_scoreboard()` negates ESPN's positive turnover totals so
  frontend code can compare all categories as higher-is-better.
  `canonical_matchups()` then treats the already-negated values as
  lower-is-better. A live 57-vs-89 category was incorrectly awarded to the
  89-turnover side. Keep canonical turnovers positive and apply category
  direction once.
- [x] **Playoff all-play rankings synthesize zero-stat teams —
  live-confirmed. Fixed (PR C).** `MyLeague.get_wins()` reindexed every week to
  all league teams and filled missing rows with zero. Week 21 had 11 unique
  active teams but returned rankings for 14; each synthetic team received 11
  - [x] **Recap turnover winners are reversed — fixed (PR #25).**
    `get_current_scoreboard()` stores TO as a natural positive count (fewer
    is better), and `canonical_matchups()` applies lower-is-better once.
    Confirmed by `test_scoreboard_turnovers.py`.
  - [x] **Transactions are unavailable — fixed (PR #19).**
    `recent_activity()` returned HTTP 404, then `safe_recent_activity()` failed
    on missing `League.espn_s2`. Replaced with the working weekly
    `mTransactions2` adapter.
  - [x] **`get_projected_matchup_table` crashes — fixed (PR G).**
    Referenced `current_matchup_period`, which wasn't a parameter — always
    raised `NameError`. Now uses the `week` parameter that's actually in scope.
    CLI-only, not FastAPI.

## Reliability — real risk, not urgent

- [x] **Repeated, uncached ESPN calls in plan generation — fixed (PR F + G).**
  `generate_multiple_plans()` now reuses one `MyLeague` across a portfolio's
  plans via `get_cached_my_league()`, so 20 plans = 1 construction instead of
  20. The legacy `/optimizer/multiple-plans` endpoint now caps `n_plans` at 10
  via a Pydantic validator (PR G).
- [x] **No backend caching — fixed (E2 + E3 + F).** `connect()` and
  `_my_league()` are now backed by a `ContextVar`-scoped request cache; recap
  snapshot reuse has a 60s TTL. Full recap assembly: ~22 ESPN requests → ~6.
- [x] **Recap (connect) cache partially added (PR E2).** `connect()`
  is now backed by a `ContextVar`-scoped request cache (one `League`
  construction per HTTP request instead of four). Recap's 4 `connect()`
  calls → 1, saving 12 ESPN requests (~22 → ~10).
- [x] **MyLeague caching (PR F).** `_my_league()` is now cache-aware via
  the same `ContextVar` store, and the Draft optimizer routes through it.
  Recap's power_rankings + season_stats → 1 `MyLeague` construction (was 2).
  Draft Room: 10-plan portfolio → 1 `MyLeague` construction (was 11). Full
  recap assembly: ~22 ESPN requests → ~6 (with E2 + E3 + F).
- [x] **Snapshot reuse for recap readiness/generation (PR E3).** The
  readiness check and generate endpoint call ``assemble_weekly_snapshot()``
  seconds apart with the same parameters. A 60 s TTL app-level cache (max
  3 entries, LRU eviction) avoids redoing the full assembly when the two
  requests arrive back-to-back.
- [x] **Inconsistent error handling — partially fixed (PR E1).**
  `/league/meta`, `/league/teams`, `/league/standings` (`backend/api/routers/league.py`)
  had no try/except, unlike most other endpoints. Now wrapped and routed
  through the typed-error mapping below (504/502/500). The other ~18
  already-try/except'd endpoints in `league.py`/`draft.py`/`optimizer.py`
  still collapse every ESPN failure to a generic 500; broadening the typed
  mapping to them is left for a follow-up PR to keep this one reviewable.
- [x] **No timeout on any ESPN read — fixed (PR E1).**
  The installed `espn-api` library calls `requests.get()` without a timeout in
  its normal `league_get()` and `get()` methods. `safe_recent_activity()` does
  the same. Put all reads behind a gateway with explicit connect/read timeouts.
  `backend/league/gateway.py` now scopes a 5s connect / 15s read timeout onto
  espn-api's internal `requests.get` (rebinding the name inside its own module
  namespace, not the shared `requests` module, so unrelated callers like the
  Supabase auth check are unaffected) and translates transport failures into
  typed `ESPNTimeoutError` / `ESPNUnavailableError`. `safe_recent_activity()`'s
  direct call now goes through the same `espn_get()` wrapper. Tests in
  `tests/test_espn_gateway.py`.
- [x] **Silent failure swallowing — fixed (PR G).** `matchups_df()`
  (`data_feed.py:1656-1660`) caught all exceptions from `league.box_scores()`
  via a bare `except Exception: matchups = []`, masking real ESPN failures.
  Now logs the error with `logging.warning(exc_info=True)` while preserving
  the empty fallback for UI resilience.

## Minor

- [ ] A real league ID (`3853870`) is committed as a source-level default in
  `config.py:17`. Not a credential leak — `SWID`/`ESPN_S2` correctly default to
  `None`, and `.env` is gitignored — but worth swapping for an obviously-fake
  placeholder so it's clear it's not meant to be used as-is by others cloning
  the repo.
- [ ] Debug CSVs are written unconditionally to the working directory in
  several places (`data_feed.py`, e.g. `get_current_rosters`, `run()`).
- [ ] `MultiplePlansBody.out_prefix` (`backend/api/routers/optimizer.py`) is caller-controlled and used
  unsanitized in a file path (`optimize_lineup.py`, `generate_multiple_plans`)
  — a plausible path-traversal opening if this endpoint is ever exposed beyond
  a trusted single user. **Deferred; revisit before any multi-user or external
  exposure.**
- [ ] `league_id` is not overridable per-request in the API — every endpoint
  uses the module-level `config.LEAGUE_ID` constant. Expected for a
  single-league v1 (per the dossier's Decision A), but confirms multi-league
  support isn't there yet when that's eventually prioritized.

## Confirmed non-issues

- Fuzzy player-name matching (`normalize_name`, `fuzzy_map_names`,
  `add_bbm_projections` in `data_feed.py`) **is implemented**, not
  aspirational — the projection-source-framework spec can build on it as-is.

## Resolved by live ESPN review

- [x] Requested completed and playoff periods are honored by
  `box_scores(matchup_period=week)`; weeks 1, 20, 21, and 22 returned distinct,
  nonzero data. The zero-score else branch remains a future-period placeholder,
  not the source of the current recap failure.
- [x] `espn-api` v0.46.0 eagerly makes four requests per `League()`
  construction, totaling 2.48 MB in the sampled league.
- [x] `recent_activity()` still returns HTTP 404. The current fallback is also
  unusable; `mTransactions2` is the replacement.
