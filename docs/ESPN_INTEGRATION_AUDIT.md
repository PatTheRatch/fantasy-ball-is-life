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
  turnover wins. Fixed: weekly all-play now runs only among teams with a real
  matchup row that week (bye/eliminated teams are excluded, never zero-filled),
  `get_universe_wins` drops the empty per-week frames, and TO direction is
  sourced from the shared `data_feed.LOWER_IS_BETTER_STATS` constant (the
  downstream negated-TO convention used by power rankings and the draft
  optimizer is preserved). Tests in `tests/test_allplay_playoff_participants.py`
  (14 active / 12+2 bye / 10+4 eliminated, ghost exclusion, TO direction).
- [ ] **Transactions are unavailable — live-confirmed.**
  `recent_activity()` returned HTTP 404, then `safe_recent_activity()` failed
  on missing `League.espn_s2`. Replace both with the documented weekly
  `mTransactions2` adapter before enabling transaction recap awards.
- [ ] **`get_projected_matchup_table` crashes** (`data_feed.py:876-878`) —
  references `current_matchup_period`, which isn't a parameter or local
  variable, so it always raises `NameError`. Its only caller is the
  `python data_feed.py` CLI entrypoint (`run()`, line ~1979), not the FastAPI
  app, so this doesn't affect the running API today — but the CLI is currently
  broken.

## Reliability — real risk, not urgent

- [ ] **Repeated, uncached ESPN calls in plan generation — live-confirmed.**
  `generate_multiple_plans()` (`optimize_lineup.py`) constructs a brand-new
  `MyLeague` → live `League()` fetch **per plan**, and `POST
  /optimizer/multiple-plans` (`backend/api/routers/optimizer.py`) exposes `n_plans` as a client-supplied
  int with no upper bound — one request can trigger unbounded live ESPN
  traffic. Each plan can also call `get_universe_wins` up to
  `reg_season_count` times inside `get_target_stats`. **Relevant to the Draft
  Room spec:** confirm whether Aisha's `~3.77s/solve` benchmark included a real
  ESPN round-trip — if `MyLeague` construction is part of the per-plan cost in
  production, the spec's "0-2 re-solves, 0-8s between picks" model may be
  optimistic. The modern Draft Room caps `n_plans` at 10, but its default
  portfolio still has an inferred 44 ESPN requests (27.3 MB) before page
  bootstrap. Fix: reuse one `MyLeague` across a portfolio's plans and cap or
  retire the legacy unbounded endpoint.
- [ ] **No backend caching — live-confirmed and quantified.** Every request hits ESPN live
  (`backend/api/deps.py` `_handles()`/`_my_league()`). A short-TTL cache keyed by
  `(league_id, season)` would remove most of the rate-limit exposure above.
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
- [ ] **Silent failure swallowing.** `matchups_df()`
  (`data_feed.py:1384-1388`) catches all exceptions from `league.box_scores()`
  via a bare `except: matchups = []`, which masks real ESPN failures as "no
  data" instead of surfacing them.

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
  a trusted single user.
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
