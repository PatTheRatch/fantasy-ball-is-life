# ESPN Integration Audit — Backlog

**Date:** 2026-07-09
**Trigger:** Patrick asked for a review of the ESPN integration (`data_feed.py`,
`fantasy.py`, `config.py`, the `/league/*` and `/rosters/*` endpoints in `backend/api/`)
before building more features on top of it — specifically the Draft Room, whose
plan-diversity engine (`draft_strategies.py`) depends on `set_requirements()`
producing correct category targets.
**Method:** read-only code audit (no live ESPN access from this environment);
findings not yet confirmed against live ESPN behavior are marked below.

This is a tracked backlog, not a feature spec — most items are independent bug
fixes / hardening, not new product decisions. Pull individual items into their
own small PRs as they're prioritized.

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

- [ ] **`GET /rosters/current` silently zeroes games-left for every player**
  when the optional `week_start_date`/`week_end_date` query params are omitted.
  `data_feed.py:1052-1053` defaults `week_start_date="2026-10-15"` *after*
  `week_end_date="2026-04-30"`, so `count_games_in_range`'s range check is
  always false. No validation catches the inverted default. Fix: derive sane
  defaults from the current matchup period, or validate `start <= end` and
  400 if not.
- [ ] **`get_projected_matchup_table` crashes** (`data_feed.py:876-878`) —
  references `current_matchup_period`, which isn't a parameter or local
  variable, so it always raises `NameError`. Its only caller is the
  `python data_feed.py` CLI entrypoint (`run()`, line ~1979), not the FastAPI
  app, so this doesn't affect the running API today — but the CLI is currently
  broken.

## Reliability — real risk, not urgent

- [ ] **Unbounded, uncached ESPN calls in plan generation.**
  `generate_multiple_plans()` (`optimize_lineup.py`) constructs a brand-new
  `MyLeague` → live `League()` fetch **per plan**, and `POST
  /optimizer/multiple-plans` (`backend/api/routers/optimizer.py`) exposes `n_plans` as a client-supplied
  int with no upper bound — one request can trigger unbounded live ESPN
  traffic. Each plan can also call `get_universe_wins` up to
  `reg_season_count` times inside `get_target_stats`. **Relevant to the Draft
  Room spec:** confirm whether Aisha's `~3.77s/solve` benchmark included a real
  ESPN round-trip — if `MyLeague` construction is part of the per-plan cost in
  production, the spec's "0-2 re-solves, 0-8s between picks" model may be
  optimistic. Fix: reuse one `MyLeague` across a portfolio's plans, cap
  `n_plans` server-side.
- [ ] **No caching anywhere.** Every request hits ESPN live
  (`backend/api/main.py` `_handles()`/`_my_league()`). A short-TTL cache keyed by
  `(league_id, season)` would remove most of the rate-limit exposure above.
- [ ] **Inconsistent error handling.** `/league/meta`, `/league/teams`,
  `/league/standings` (`backend/api/routers/league.py`) have no try/except, unlike most other
  endpoints that convert ESPN failures to a clean `HTTPException(500, ...)`.
  Unhandled exceptions currently surface as raw framework 500s.
- [ ] **No timeout on a fallback network call.** `safe_recent_activity()`
  (`data_feed.py:446`) calls `requests.get(url, cookies=cookies)` with no
  timeout — and it's the fallback used specifically when
  `league.recent_activity()` fails (`data_feed.py:712-714`), i.e. the
  most likely-to-hang path is the unprotected one.
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

## Needs live ESPN access to confirm (can't check from this sandbox)

- [ ] `get_current_scoreboard`'s else-branch (`data_feed.py:1165-1177`)
  hardcodes scores to `0` instead of reading `matchup.home_team.stats` —
  unclear if that's intentional (e.g. a deliberate placeholder for a state ESPN
  doesn't expose) or a bug.
- [ ] Whether `espn_api` v0.46.0's `League()` fetches the full season schedule
  eagerly on construction, or lazily per call — determines the true severity of
  the unbounded-calls risk above.
- [ ] Whether the ESPN `recent_activity()` 404 bug referenced in
  `safe_recent_activity`'s own docstring still occurs in v0.46.0, i.e. whether
  the `requests`-based fallback is still needed at all.
