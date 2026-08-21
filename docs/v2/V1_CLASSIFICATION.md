# V1 Classification — KEEP / EXTRACT / REWRITE / KILL / DEFER

**Work-plan item 5** from [`FCP_V2_Product_Architecture_Charter.md`](../FCP_V2_Product_Architecture_Charter.md) §11.

**The unit is not the file.** Charter §9: *"It is the idea, invariant, algorithm, test case, or proven domain behavior."* This document classifies at that granularity and produces the actual port list for slice 1.

| Verb | Charter definition |
|---|---|
| **KEEP** | Already clean enough to preserve substantially as-is |
| **EXTRACT** | Valuable domain logic that should move behind a cleaner V2 boundary |
| **REWRITE** | The product concept is right; the implementation is tied to current scars |
| **KILL** | Legacy paths, duplication, global defaults, deployment residue, behaviour no longer wanted |
| **DEFER** | Useful idea that should not block the V2 foundation |

**Companion:** [`CLAUDE_GREENFIELD_ARCHITECTURE.md`](../CLAUDE_GREENFIELD_ARCHITECTURE.md) Part B classified *subsystems*. This classifies *ideas and invariants*, and adds the register in §7 — the behaviours V1 paid for in production bugs, which are the most valuable thing it has to hand over.

---

## 1 · Basketball domain

| Item | Verb | Note |
|---|---|---|
| 9-cat category set + direction rules | **EXTRACT** | To `domain/categories.py`; direction becomes a `categories.higher_is_better` column (charter D11), not a module-level set |
| `category_result()` W/L/T comparison | **EXTRACT** | Pure, tiny, correct. Carries three invariants (§7) |
| `WeeklyScoreboard` all-play / universe wins | **EXTRACT** | Vectorized, injectable data, genuinely good. Feed from FCP `matchups` rows instead of ESPN objects |
| Playoff participant exclusion (bye/eliminated) | **EXTRACT** | Invariant-dense; see §7. Do not re-derive |
| `standings_from_week_scoreboards()` fold | **EXTRACT** | Already the right shape — a fold over per-week rows. Becomes the only standings path |
| `get_target_stats()` week sampling | **EXTRACT** | Derives the sample from `reg_season_count` + current week; four invariants in §7 |
| `MyLeague` / `ScoreboardLeague` | **KILL** | Subclassing `espn_api.League` and overriding its private loaders is the charter §7 violation. The *narrow-fetch idea* survives as adapter methods |
| Auction optimizer (`OptimizeLineup`, cvxpy) | **EXTRACT** ⚠️ | **Gated — see §6.** 798 lines, zero CI coverage |
| Plan diversity / strategy portfolio | **EXTRACT** ⚠️ | Gated with the optimizer |
| Draft engine (per-pick health + selective re-solve) | **EXTRACT** | The cleanest module in V1 — already pure, solver injected. Nine invariants in §7 |
| Monte Carlo category targets | **EXTRACT** ⚠️ | Gated |
| Forge Value / auction valuation | **EXTRACT** ⚠️ | Gated, and least verified of the four |
| Consistency tiers / confidence | **EXTRACT** algorithm, **REWRITE** source | Algorithm is fine; it reads a SQLite file that does not exist. Source becomes `nba_player_games` |
| Playoff schedule planner | **KEEP** | Pure functions, honest empty states, wiring in the router. The best-shaped feature in V1 |
| `storyline_metrics()` | **DEFER** | Useful for the story engine, not foundational |
| Deterministic awards | **EXTRACT** | Concept and computation both good |
| Recap fact assembly | **REWRITE** | Concept exactly right; implementation is a three-way reconciliation across overlapping snapshot tables with layered try/except. Week finality deletes the need |

---

## 2 · Projections

| Item | Verb | Note |
|---|---|---|
| `PlayerProjection` canonical schema | **KEEP** | V1's single best design asset. Makes/attempts not percentages |
| Adapter protocol (`detect`/`parse`) | **KEEP** | Extend for provider-live sources |
| BBM / Hashtag / ESPN adapters | **EXTRACT** | Parsing logic is fine; rehome behind `providers/` |
| Week-scoped set invalidation | **KEEP** | Genuinely good — a stale set falls through automatically. Nine invariants in §7 |
| ESPN virtual-set sentinel | **REWRITE** | Concept survives as `projection_sources.kind='provider_live'`; the magic string does not |
| `ProjectionStore` (parquet + `manifest.json`) | **KILL** | Ephemeral container disk. Highest-severity finding in the audit |
| Global `active` horizon map | **KILL** | One anonymous caller changes projections platform-wide |
| `get_active_projections()` ambient read | **KILL** | Replaced by pure `resolve_projections(source, horizon, adjustments)` |
| Legacy `BBM_Projections.xls` disk fallback | **KILL** | Also the reason 20 tests skip in CI |
| Accuracy scoreboard (M-2) | **EXTRACT** | Design is sound; only its storage was wrong |
| Backtest harness + naive baseline (M-3a) | **KEEP** | Correct sequencing — benchmark before model |
| `normalize_name()` (module-level) | **EXTRACT** | Becomes *the* one implementation |
| `normalize_name()` (shadowed in `add_bbm_projections`) | **KILL** | Disagrees with the module-level one on hyphens and suffixes |
| `fuzzy_map_names()` | **EXTRACT** | Thresholds become data in the resolution ladder, not literals |
| `add_bbm_projections` / `add_projections` / `attach_projections` / `attach_projections_to_movesets` | **KILL** | Four attachment paths with four cutoffs (80/75/85/90). One resolution stage replaces all |

---

## 3 · NBA data

| Item | Verb | Note |
|---|---|---|
| `nba_player_seasons` / `nba_player_bio` column design | **KEEP** | Makes and attempts, per-game with season-total minutes. Add `player_id` FK |
| `nbadata/ingest.py` (nba_api) | **EXTRACT** | Currently IP-blocked; the shaping logic is still correct |
| `nbadata/csv_backfill.py` (Kaggle) | **EXTRACT** | The working path. Re-run as a V2 ingestion run, not a bulk import |
| `nbadata/reader.py` | **REWRITE** | Becomes a repository; keep the null-safe dtype coercion |
| Pagination past PostgREST's 1,000-row cap | **KILL** | Artifact of PostgREST. Real SQL does not need it |
| Game logs (`data/game_logs.db`) | **REWRITE** | The file does not exist and nothing creates it. Becomes `nba_player_games` |

---

## 4 · Newsroom

| Item | Verb | Note |
|---|---|---|
| Facts / editions separation | **KEEP** | Charter D13 already implemented correctly |
| Version numbering + `one_published` partial index | **KEEP** | DB-enforced invariant. Port verbatim |
| `publish_recap_edition()` security-definer RPC | **KEEP** | Lock, authorize, supersede, publish — atomic and correct |
| `recaps/service.py` `require_admin()` | **EXTRACT** | The only correct authorization in V1 |
| Prompts + voice spec | **EXTRACT** | Hard-won tuning; rehome out of `data_feed.py` |
| Structured generation via JSON repair + corrective retry | **REWRITE** | Use native structured output / tool use. Repair-then-retry masks failures |
| `/matchup-commentary`, `/league-recap`, `/season-commentary` | **KILL** | Superseded, unauthenticated, unmetered LLM spend |
| Power-ranking blurb caching per week | **KEEP** (concept) | In V2 it is just the row |
| `make_prompt()` living in `data_feed.py` | **KILL** | Prompt construction in the data layer |

---

## 5 · Platform, API, frontend

| Item | Verb | Note |
|---|---|---|
| ESPN gateway (timeouts, typed errors, scoped patch) | **KEEP** | Relocate to `providers/espn/client.py`. Nine invariants in §7 |
| Worker per-phase / per-league failure isolation | **KEEP** (concept) | Becomes per-job isolation |
| `worker/refresh.py` synchronous loop | **REWRITE** | 900s HTTP request over all leagues; dies in the low tens |
| `RecapStore` | **KILL** | 32 methods, six aggregates, no connection pooling |
| Four caching layers | **KILL** | Exist only because requests fetch ESPN inline |
| Slug middleware + `_LEAGUE_CTX` ContextVar | **KILL** | Replaced by explicit scope injection |
| `_resolve_ctx()` "first league in the DB" fallback | **KILL** | The charter D12 violation |
| pgcrypto credential RPC | **KILL** | Sends the key to Postgres as a parameter |
| `config.py` personal globals (`DO_NOT_DRAFT`, `POSITION_OVERRIDES`, `GAMES_PER_WEEK`, `MIN_SEASON_GAMES_FILTER`) | **KILL** | → `manager_league_prefs` / `manager_do_not_draft` |
| Hardcoded week calendars (Python **and** TypeScript) | **KILL** | Derivable from `settings.matchupPeriods` — see the ingestion design |
| `legacy_redirects.py` (17 routes) | **KILL** | Its own docstring says remove after cutover |
| `render.yaml`, `cron_entrypoint.py` | **KILL** | Dead Render residue |
| `out_prefix` → `to_csv()` in the optimizer API | **KILL** | Unauthenticated arbitrary file write |
| `path` form field → `pd.read_excel(path)` | **KILL** | Unauthenticated arbitrary file read |
| React 19 / Vite / Tailwind / react-query stack | **KEEP** | No framework problem |
| `api.ts` (1,090 lines, hand-maintained) | **KILL** | Generate from OpenAPI |
| Dual axios clients (`client` / `directClient`) | **KILL** | Dev-proxy workaround in production code |
| `ui/` design system | **EXTRACT** | Absorb the duplicate `components/Card`, `season/Skeleton` |
| Draft UI decomposition (board, rail, controls, editors) | **EXTRACT** | Well factored already |
| `draft/storage.ts` as system of record | **REWRITE** | → server `draft_sessions`; keep as offline cache |
| `navigation.ts`, `useLeagueSlug`, `stateUtils`, `seasonUtils` | **KEEP** | Small, pure, tested |
| `lib/matchupWeeks.ts` | **KILL** | Duplicated hardcoded calendar |
| Direct browser → Supabase data calls | **REWRITE** | Supabase for auth only |
| Auth surfaces (login/signup/reset/update) | **KEEP** | Work fine |
| `pages/InSeason.tsx`, `pages/Season.tsx` shims | **KILL** | P-7 leftovers |

---

## 6 · Gated ports — verify before moving

Four items are marked EXTRACT ⚠️ because they are valuable *and* unverified. Charter §9 names current FCP a **test oracle**; this is where to use it.

**The draft optimizer, plan diversity, MC targets, and Forge Value have zero CI coverage.** Twenty tests skip on `player_rankings/BBM_Projections.xls`, which is gitignored and cannot be committed — so the most complex, highest-value code in the product has never been exercised by CI.

Required before any of the four moves:

1. **Commit a synthetic projection fixture** — ~200 players with realistic distributions, checked in. This alone un-skips 20 tests.
2. **Capture characterization tests from V1.** Run the current optimizer against the fixture, record outputs, assert V2 reproduces them. Charter §9's "test oracle" made literal.
3. **Verify the solver cap interacts sanely with feasibility.** `SOLVER_TIME_LIMIT_SECONDS=8` was added because real MC-derived targets took 8–24s unbounded. What a *timeout* returns versus an *infeasible* solve is undocumented and matters.
4. **Forge Value specifically has no test file at all.** `test_player_values.py` and `test_auction_values_mc.py` exist but the pricing model itself is unvalidated. Treat as least-trusted of the four.

Do not port these on trust. They are the flagship, and "it worked for one draft" is not coverage.

---

## 7 · The invariant register

**This is the most valuable thing V1 has to hand over.** Each of these was paid for with a production bug, and each is encoded in a named test. They are behaviours, not code — port the behaviour and the test, whatever the implementation looks like.

### Category semantics
| Invariant | V1 test |
|---|---|
| Turnovers: fewer wins | `test_category_result_turnovers_lower_wins` |
| Every other category: more wins | `test_category_result_other_stats_higher_wins` |
| Ties and NaN tie, never crash | `test_category_result_ties_and_nan` |
| TO is stored as a **positive count**; direction applied only at comparison | `test_get_current_scoreboard_keeps_turnovers_positive` |
| The provider's own `winner` is authoritative and must reach the recap | `test_get_current_scoreboard_exposes_espn_authoritative_winner` |
| Turnover direction survives end-to-end into the recap | `test_scoreboard_feeds_correct_turnover_winner_to_recap` |

> Shipped bug: reversed turnover winners in published recaps.

### All-play / playoffs
| Invariant | V1 test |
|---|---|
| A regular week includes every team | `test_regular_week_all_14_teams_participate` |
| Bye teams are **excluded, never zero-filled** | `test_early_playoff_two_byes_excluded` |
| Eliminated teams are excluded | `test_late_playoff_four_eliminated_excluded` |
| Teams with no matchup row that week do not appear | `test_get_wins_ignores_ghost_league_teams` |
| A bye team returns empty, not zeros | `test_get_wins_bye_team_returns_empty_frame` |
| TO direction holds inside all-play too | `test_turnovers_fewer_is_better_in_allplay` |

> Shipped bug: 14 rankings for 11 active teams; each ghost awarded 11 turnover wins.

### Date windows
| Invariant | V1 test |
|---|---|
| Explicit dates pass through untouched | `test_explicit_dates_pass_through` |
| A missing window derives forward from the matchup period | `test_derives_window_from_matchup_period_when_dates_missing` |
| An explicit period beats the league's current week | `test_explicit_period_beats_league_week` |
| Partial dates fill only the missing bound | `test_partial_dates_fill_only_missing_bound` |
| An inverted range is rejected **before** touching the provider | `test_rosters_current_endpoint_400s_on_inverted_before_touching_espn` |

> Shipped bug: default window ran 2026-10-15 → 2026-04-30, so every player silently showed zero games left.

### Week sampling
| Invariant | V1 test |
|---|---|
| Sample only regular-season weeks already played | `test_only_samples_regular_season_weeks_played_so_far` |
| Stop at the regular season even if the current week is later | `test_stops_at_regular_season_even_if_current_week_is_later` |
| Skip weeks with no matchup data rather than crashing | `test_skips_weeks_with_no_matchup_data_instead_of_crashing` |
| Fall back to schedule length when `reg_season_count` is unavailable | `test_falls_back_to_length_of_schedule_when_reg_season_count_unavailable` |

> Shipped bug: hardcoded `range(16)` with unreachable exclusions fed every draft plan's category targets.

### Historical correctness
| Invariant | V1 test |
|---|---|
| Standings derive from per-week rows, not rolling state | `test_derives_standings_from_weeks_not_rolling_state` |
| Fewer weeks yields a different table | `test_fewer_weeks_yields_different_table` |
| A week's feed uses that week's rows, not the latest | `test_week_feed_uses_that_weeks_rows_not_latest` |
| Season transactions are cumulative across weeks | `test_season_transactions_are_cumulative` |
| Backfill fetches only missing weeks | `test_backfill_fetches_only_missing_weeks` |
| One failing week never blocks the others | `test_backfill_isolates_failing_week` |
| Empty input is empty, not an error | `test_empty_input_is_empty_not_error` |

> Shipped bugs: past weeks rendered the current scoreboard; trades invisible all season.

### Projection precedence
| Invariant | V1 test |
|---|---|
| An active set is honoured only when its week matches | `test_active_set_honored_when_week_matches` |
| A stale set is ignored and falls through to live | `test_active_set_ignored_when_week_mismatches` |
| Week-scoped loads require a current week | `test_active_set_requires_current_week` |

### Transport policy
| Invariant | V1 test |
|---|---|
| A default timeout is applied to every provider call | `test_patch_applies_default_timeout_to_espn_api_requests_get` |
| The patch is idempotent | `test_patch_is_idempotent` |
| **The shared `requests` module is never mutated** | `test_patch_does_not_mutate_the_shared_requests_module` |
| Timeouts and connection errors become typed errors | `test_patch_translates_timeout_to_typed_error` |
| A caller-supplied timeout wins | `test_espn_get_respects_caller_supplied_timeout` |
| Timeout maps to 504, other transport failure to 502 | `test_status_code_timeout_is_504` |

### Draft engine
| Invariant | V1 test |
|---|---|
| Unaffected plans are left untouched **and not re-solved** | `test_apply_pick_leaves_unaffected_plans_untouched_and_uncalled` |
| Only the broken plan re-solves | `test_apply_pick_resolves_only_the_broken_plan` |
| A plan with no feasible replacement is marked broken, not crashed | `test_apply_pick_marks_plan_broken_when_no_replacement_is_feasible` |
| Fallback returns the first alive plan in order | `test_pick_fallback_returns_first_alive_plan_in_order` |
| All plans broken yields `None`, not an exception | `test_pick_fallback_is_none_when_every_plan_is_broken` |
| Plan ids are deterministic slugs that survive round-tripping | `test_plan_id_is_a_clean_deterministic_slug` |
| An infeasible pool raises a **clear** error | `test_favorite_team_representation_beyond_pool_raises_clear_error` |

> Product principle these encode: **never freeze on bad input.** Worth carrying explicitly into V2.

### Test infrastructure
| Item | Verb | Note |
|---|---|---|
| Autouse secret-scrubbing fixture | **KEEP** | Makes local runs structurally match clean CI. Best test infra in V1 |
| Stub `LeagueContext` autouse fixture | **REWRITE** | → scope fixtures |
| RLS boundary suite (16 tests) | **REWRITE** | Retarget at application authz, keep RLS as backstop |
| Named regression test per production bug | **KEEP** (the habit) | |

---

## 8 · Deferred

| Item | Why deferred |
|---|---|
| Streaming advisor, trade analyzer, daily snapshots | Spec-only. Charter §15: do not build for architectural completeness |
| Manager-performance analytics | Needs daily roster history, which only accrues after slice 1 starts capturing it |
| `storyline_metrics()` | Story-engine input, not foundational |
| Multi-season records / rivalries surfaces | Need imported history first |
| Self-delivering recaps | **Flag:** the dossier's founding goal, absent from the charter. Not deferred by decision — by omission. Worth an explicit call |
| FCP projection model (M-3) | Charter D6 — the framework exists for it; the model comes after |

---

## 9 · Slice 1 port list

Everything needed for *user → manager → league → season → ESPN sync → canonical teams/players/periods → one shared league page*, with tenancy from day one (charter D26).

**Port now**

1. ESPN gateway → `providers/espn/client.py` (**KEEP**, + its 9 invariants)
2. `normalize_name()`, module-level only (**EXTRACT**)
3. `fuzzy_map_names()`, thresholds as data (**EXTRACT**)
4. Category semantics + `category_result()` (**EXTRACT**, + 6 invariants)
5. Date-window derivation (**EXTRACT**, + 5 invariants)
6. `WeeklyScoreboard` all-play (**EXTRACT**, + 6 invariants)
7. Standings fold (**EXTRACT**, + 7 invariants)
8. Worker failure-isolation concept → job design (**KEEP**)
9. Secret-scrubbing test fixture (**KEEP**)

**Explicitly not in slice 1:** the optimizer and its three companions (gated, §6), all projection machinery, the newsroom, every private manager table.

**Delete on sight, no V2 equivalent:** `data_feed.py`, `RecapStore`, all four caches, both hardcoded calendars, `config.py` personal globals, `legacy_redirects.py`, `render.yaml`, `cron_entrypoint.py`, the two arbitrary-path endpoints, `api.ts`, `matchupWeeks.ts`.

---

## Tally

| Verb | Count |
|---|---|
| KEEP | 21 |
| EXTRACT | 24 (4 gated) |
| REWRITE | 13 |
| KILL | 32 |
| DEFER | 6 |

The shape is the recommendation restated: **the basketball logic survives, the application around it does not.** Forty-five items carry forward as ideas, algorithms or invariants; thirty-two are residue.

---

*Design phase. Classified against `02dd625`.*
