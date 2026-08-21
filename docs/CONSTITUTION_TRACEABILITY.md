# Constitution Traceability Matrix

**Purpose:** map every clause of [`PRODUCT_CONSTITUTION.md`](PRODUCT_CONSTITUTION.md) to the current implementation, the audit finding that governs it, and the concrete code that must change. One checklist instead of two documents held in your head.

**Companion to:** [`CLAUDE_FCP_AUDIT.md`](CLAUDE_FCP_AUDIT.md) (findings), [`CLAUDE_GREENFIELD_ARCHITECTURE.md`](CLAUDE_GREENFIELD_ARCHITECTURE.md) (the design that satisfies this matrix).

**Status legend**

| | Meaning |
|---|---|
| **MET** | Current implementation already satisfies the clause |
| **PARTIAL** | Satisfied somewhere, contradicted elsewhere |
| **VIOLATED** | Current implementation actively contradicts the clause |
| **ABSENT** | Nothing exists yet — net-new build, not debt |

Counts: **4 MET · 6 PARTIAL · 9 VIOLATED · 4 ABSENT**

---

## §1 · What FCP is — two product layers

| | |
|---|---|
| **Requires** | Shared league experience *and* private power-user experience, both first-class |
| **Status** | **PARTIAL** |
| **Today** | Shared layer is real: newsroom, power rankings, awards, transactions, standings, playoff planner. Private layer is Draft Room only — and it is neither authenticated nor per-user. |
| **Evidence** | `backend/api/routers/draft.py` (7 routes, no auth, flat/global) · `frontend/src/draft/storage.ts` (state in `localStorage`) |
| **Implication** | The private layer needs a real per-user persistence and authorization model. See §3. |

---

## §2 · Primary user is an individual manager; one league has many FCP users

| | |
|---|---|
| **Requires** | User-centric, not commissioner-centric. Many users per league, many leagues per user. |
| **Status** | **PARTIAL** |
| **Today** | Many-leagues-per-user works (`getMyLeagues`, `HomeResolver` picker). Many-users-per-league is modelled in the DB but nothing user-specific hangs off it beyond a claimed team name. |
| **Evidence** | `league_memberships(league_id, user_id, role, team_name)` — that is the entire per-user surface · `frontend/src/lib/memberships.ts` |
| **Implication** | `league_memberships` needs to become the anchor for user-scoped analytics, not just an ACL row. |

---

## §3 · Shared vs private information must be explicit

| | |
|---|---|
| **Requires** | Named private categories — draft strategy, target players, do-not-draft, waiver targets, trades considered, private evaluations, projection preferences, adjustments, watchlists, model settings. "Another manager must not be able to see these." |
| **Status** | **ABSENT** — and this is the single largest net-new build in the constitution |
| **Today** | There is **no user-scoped data model at all.** No watchlists, no notes, no per-user projection preference, no adjustments, no saved draft state. Draft config and picks live in the browser. The one thing resembling a private preference — the do-not-draft list — is a **process-global env var shared by every league on the deployment.** |
| **Evidence** | `backend/config.py:78-86` (`DO_NOT_DRAFT` global) · `frontend/src/draft/storage.ts` · no user-scoped tables in any of the 10 migrations |
| **Implication** | Needs tables, tenant-scoped repositories, `/me/**` API surface, and authorization. Not debt — absent. |

---

## §4 · Basketball intelligence is a reusable platform capability

| | |
|---|---|
| **Requires** | One shared layer for player identity, projections, category values, schedule math, roster value, league context, matchup logic, availability. Tools must not reinvent these. |
| **Status** | **VIOLATED** |
| **Today** | Player identity is reinvented four times with different thresholds and two different normalizers. Projection attachment is implemented five times (four in `data_feed`, one acknowledged port in `EspnAdapter`). Schedule math reads a hand-typed calendar duplicated across two languages. |
| **Evidence** | `data_feed.py:180` and `:406` (two `normalize_name`) · `:385,:833,:980,:194` (cutoffs 80/75/85/90) · `projections/adapter.py` ("a straight port of `get_current_rosters()`") · `data_feed.py:89` + `frontend/src/lib/matchupWeeks.ts` |
| **Implication** | Extract a pure domain layer. See the §4/§5 tension note below. |

---

## §5 · Projections are a first-class system — source × horizon × adjustments

| | |
|---|---|
| **Requires** | Three **separate** concepts: source, horizon, user adjustments. Per-user source choice. Shared analytics pinned to a default methodology. Adjustments must not overwrite the source. |
| **Status** | **PARTIAL** — the canonical schema is right; everything around it is wrong |
| **Today** | Source and horizon exist and are well-modelled. **User adjustments do not exist.** **Per-user source choice does not exist** — the active set is a single global `{horizon: set_id}` map, so one anonymous caller changes projections for every user in every league. Stored on ephemeral container disk. |
| **Evidence** | `projections/adapter.py:23-64` (canonical schema — good) · `projections/store.py:41,76-80` (global `active` map, `league_slug` is metadata only) · `api/routers/projections.py` (`PUT/DELETE /projections/active`, no auth) |
| **Implication** | Move to Postgres; make the active selection `(user_id, league_id, horizon)`; add an adjustments layer that composes rather than mutates. |

---

## §6 · FCP should eventually own projections

| | |
|---|---|
| **Requires** | First-party model participates in the same system as external sources. No redesign when it is ready. |
| **Status** | **MET (by design)** |
| **Today** | This is the framework's best property and it genuinely holds. Every consumer reads only `PlayerProjection`, so an `fcp` adapter drops in with zero consumer changes. M-2 (accuracy) and M-3a (backtest + naive baseline) already exist as the merge gate. |
| **Evidence** | `projections/adapter.py` · `projections/registry.py` · `projections/accuracy.py` · `projections/backtest.py` |
| **Implication** | Preserve this abstraction verbatim. It is the highest-value design asset in the repo. |

---

## §7 · External platforms are adapters, not the domain model

| | |
|---|---|
| **Requires** | `provider → normalized FCP league model → features`. FCP owns league, team, manager, roster, matchup, transaction, scoring settings, schedule, season. Adding Yahoo/Sleeper must not rewrite domain logic. |
| **Status** | **VIOLATED** — structurally, not incidentally |
| **Today** | **The domain model *is* the ESPN client.** `MyLeague` and `ScoreboardLeague` both subclass `espn_api.basketball.League` and override its *private* loaders. There is no normalized FCP league object anywhere; ESPN objects flow directly into analytics. |
| **Evidence** | `league/fantasy.py:14` (`class MyLeague(League)`, overrides `_get_all_pro_schedule`) · `league/scoreboard_fetch.py:30-56` (`ScoreboardLeague`, overrides `_fetch_players`/`_fetch_draft`/`_get_all_pro_schedule`) |
| **Implication** | Adding Yahoo is currently a domain rewrite, exactly what the clause forbids. Highest-leverage structural change. |

---

## §8 · Player identity must belong to FCP

| | |
|---|---|
| **Requires** | Durable FCP player id. ESPN/NBA/BBM/Hashtag/Yahoo ids map onto it. **"Player names should not be the canonical join key."** |
| **Status** | **VIOLATED** — names *are* the only join key |
| **Today** | Every join in the system is a normalized name string. No FCP player id exists. Two different normalizers produce different keys for hyphenated and suffixed names. A mismatch does not error — it silently drops the player from a projection set or optimizer pool. |
| **Evidence** | `data_feed.py:180` vs `:406` (accents/periods stripped vs *all* non-alpha stripped) · `nba_player_seasons.normalized_name` as the stated ESPN join key · `nbadata/ingest.py:34`, `csv_backfill.py:52` (global NBA layer importing the ESPN layer for a string function) |
| **Implication** | `players` + `player_external_ids` + an auditable alias/resolution table. Name matching becomes an ingest-time step, never a query-time join. |

---

## §9 · Data layers must not be mixed

| | |
|---|---|
| **Requires** | Source · normalized · derived analytics · user-specific analytics · presentation, kept distinct. |
| **Status** | **VIOLATED** |
| **Today** | One 2,699-line module holds the ESPN client, name matching, projection attachment, transaction parsing, scoreboard math, **LLM prompt construction**, Excel readers, a season calendar, and a CLI that writes 15 CSVs to the working directory. `RecapStore` spans six unrelated aggregates. ~120 lines of domain math sit inline in a route handler. |
| **Evidence** | `league/data_feed.py` (`make_prompt` at `:2171`, `run()` at `:2574`) · `recaps/store.py` (32 methods, leagues → recaps → NBA data) · `api/routers/league.py:110-230` |
| **Implication** | The layer split is the reorganizing principle for the target architecture. |

---

## §10 · Historical state matters

| | |
|---|---|
| **Requires** | "What did this league look like after Week 7?" answered correctly. History never reconstructed from today's rosters. Completed facts durable. |
| **Status** | **PARTIAL** — achieved, but by compensation |
| **Today** | The original snapshot table was rolling-latest, so every past-week view rendered current state and season transaction totals saw one week ("trades were effectively invisible all season"). Fixed by adding two more tables and reconciling all three at read time with layered try/except degradation. It works; it is compensation, not design. |
| **Evidence** | `20260723120000_league_week_scoreboards.sql` and `20260724120000_league_week_transactions.sql` (both migration comments state the bug) · `recaps/assemble.py:418-500` (the reconciliation) |
| **Implication** | The root cause is a missing concept: **week finality.** Add it and one table replaces three. |

---

## §11 · Freshness must be explicit

| | |
|---|---|
| **Requires** | Live / periodically refreshed / historical-immutable, understandable without reading the implementation. |
| **Status** | **VIOLATED** |
| **Today** | Within one router, `/power-rankings`, `/standings`, `/season-stats` read stored snapshots while `/meta`, `/schedule`, `/matchups/current-week`, `/playoff-schedule` and both confidence endpoints hit live ESPN inside the request. **A caller cannot tell from the URL which they will get** — and the live ones are the slow ones (140–171s constructions measured in production). |
| **Evidence** | `api/routers/league.py` (`_snapshot_read` vs `_handles()` in adjacent handlers) · `league/cache.py:20-33` |
| **Implication** | Freshness class must be a property of the data model, not an accident of which PR wrote the handler. |

---

## §12 · Multi-league is fundamental; nothing league-specific becomes global

| | |
|---|---|
| **Requires** | League settings, season, roster config, ownership, draft config, matchup state, team identity all per-league. Private preferences never global. |
| **Status** | **VIOLATED** |
| **Today** | The multi-league migration converted the league-data half of the API and stopped. **18 routes remain flat and global** — draft, optimizer, projections, commentary — falling back to "the first league row in the database." Draft pool hygiene, games-per-week, and the do-not-draft list are process-wide env vars. The frontend bakes the league slug at build time. |
| **Evidence** | `api/deps.py:29-45` (`_resolve_ctx` single-league fallback) · `config.py:71-99` · `.github/workflows/deploy.yml` (`VITE_RECAP_LEAGUE_SLUG=patriot-games`) · `lib/supabase.ts:17` |
| **Implication** | Every route league-scoped or user-scoped; no global configuration of league-specific values. |

---

## §13 · The Newsroom is a real pillar; LLM never authoritative

| | |
|---|---|
| **Requires** | `league facts → deterministic story inputs → generated editorial`. LLM never the source of standings, awards, transactions, rankings, results. Multi-season history. |
| **Status** | **MET** — this is the best-realized clause in the codebase |
| **Today** | Facts and prose are already separate and separately versioned. Immutable fact snapshots; editions reference a snapshot id; a partial unique index guarantees one published edition per week; publish is an atomic security-definer function that checks admin rights inside the transaction. Awards are deterministic. |
| **Evidence** | `league_week_snapshots` + `recap_editions` + `recap_editions_one_published_idx` + `publish_recap_edition()` in `20260712150000_recap_phase1.sql` · `recaps/awards.py` |
| **Implication** | Preserve the model. Only gap: multi-season history is not surfaced, and delivery/distribution is unaddressed (see open questions). |

---

## §14 · Draft Room is a private power-user product

| | |
|---|---|
| **Requires** | May stay private now; per-manager private if exposed. Engine separable from UI and persistence. |
| **Status** | **PARTIAL** |
| **Today** | Engine separability is genuinely achieved — `engine.py` is pure, no cvxpy/pandas/ESPN, solver injected as `solve_fn`. But the routes are unauthenticated and global, and "private" state is browser-local, so it is device-bound with no recovery mid-draft. |
| **Evidence** | `draft/engine.py:1-20` (good) · `api/routers/draft.py` (7 unauthenticated routes) · `draft/storage.ts` |
| **Implication** | Cheapest correct short-term action is to gate the routes, not redesign the engine. |

---

## §15 · Future private decision tools need a natural home

| | |
|---|---|
| **Requires** | Streaming, waivers, trades, comparison, schedule optimization, playoff planning, roster construction can be added without duplicating core basketball logic. Do not build speculatively. |
| **Status** | **ABSENT (correctly)** |
| **Today** | Specced, unbuilt: Streaming Advisor, Trade Analyzer, Daily Snapshots. Built: Playoff Schedule Planner (W-series), which is a good precedent — pure functions in `league/playoff_schedule.py`, wiring in the router, honest empty-state reasons. |
| **Evidence** | `docs/specs/STREAMING_ADVISOR.md`, `TRADE_ANALYZER.md`, `DAILY_SNAPSHOTS.md` (all spec-only) · `league/playoff_schedule.py` |
| **Implication** | The test of §4 is whether the next tool needs zero new basketball logic. Today it would need its own name-matching and projection plumbing. |

---

## §16 · Scale — hundreds to thousands, not millions

| | |
|---|---|
| **Requires** | Legitimate multi-user product. No speculative distributed infrastructure. |
| **Status** | **VIOLATED** at the current refresh model |
| **Today** | Refresh is **one synchronous HTTP request** looping every league sequentially, nine phases each, against an ESPN connection observed at 140s+ per league, under a 900s client timeout. No queue, no retry beyond the next 15-minute tick. Process-local caches and on-disk state mean the backend **cannot run more than one container.** |
| **Evidence** | `worker/refresh.py:290,478` · `worker/cron_entrypoint.py:19` (900s) · `league/cache.py` (four process-local caches) |
| **Implication** | Not a scalability-theatre problem — this breaks in the low tens of leagues. Needs per-league job units, which is the *simple* answer, not the complex one. |

---

## §17 · Commercial assumption — no trusted-user assumptions

| | |
|---|---|
| **Requires** | Do not assume one trusted user, one trusted league, one global configuration, free unlimited external API usage, or free unlimited LLM usage. Security, authorization, tenancy, usage controls, durability appropriate for a real public product. |
| **Status** | **VIOLATED** on every listed assumption |
| **Today** | **53 of 71 routes have no authentication.** No membership check exists anywhere on the read path — a slug is sufficient to read a private league. Three LLM endpoints accept request-body content with no auth and no rate limit, billed to the owner's key. `POST /projections` reads an arbitrary server-side path. `/optimizer/multiple-plans` writes an arbitrary server-side path. |
| **Evidence** | `routers/league.py` (21), `draft.py` (7), `legacy_redirects.py` (17), `projections.py` (6), `commentary.py` (3), `optimizer.py` (2) — all unauthenticated · `projections.py:62-64` (`pd.read_excel(path)`) · `optimizer.py:144,170` → `optimizer.py:723,748` (`out_prefix` → `to_csv`) |
| **Implication** | Authorization must be structurally unbypassable, not a decorator someone remembers to add. |

---

## §18 · Rebuild constraint — sunk cost is zero, but do not rebuild for cleanliness

| | |
|---|---|
| **Requires** | Anything may be replaced. Genuinely good things should survive. |
| **Status** | **N/A** — governs the recommendation |
| **Open question** | The clause says migration effort is not a constraint, but does not distinguish **code** from **data**. Replaceability differs sharply: NBA seasons/bios are re-backfillable from the CSV; ESPN league data is refetchable; **published recap editions are not** (LLM output bound to a specific week's facts, and §13 promises multi-season history); auth users and memberships are live. |
| **Implication** | Needs an explicit line before any rebuild begins. |

---

## §19 · Existing domain IP must be evaluated on merit

| | |
|---|---|
| **Requires** | Evaluate, do not assume preserve or discard. Named: auction optimization, draft strategies, MC targets, Forge Value, all-play, category direction, historical standings, recap facts, deterministic awards, projection normalization, accuracy evaluation, ESPN transport hardening. |
| **Status** | **N/A** — governs the classification |
| **Audit verdicts** | Rated genuinely good: canonical projection schema, recap publication model, ESPN gateway, all-play/`WeeklyScoreboard`, category-direction rules, worker failure isolation, benchmark-first sequencing. Rated untrustworthy until measured: the optimizer itself — 798 lines of cvxpy with **zero CI coverage** (20 tests skip on a gitignored `.xls`). |
| **Evidence** | `tests/test_draft_api_integration.py` + 3 others, all skipping "projections file not present" |
| **Implication** | Do not port the optimizer without first putting a committed synthetic fixture behind it. |

---

## §20 · Architecture priorities

| | |
|---|---|
| **Requires** | Correctness > domain boundaries > security/tenancy > durability > understandability > testability > feature velocity > operational simplicity > performance > scalability. Boring and explicit. |
| **Status** | **PARTIAL** — and the ordering indicts the current system |
| **Today** | The top four priorities are exactly where the audit's critical findings sit: durability (state wiped every deploy), security/tenancy (53 open routes), domain boundaries (two god modules). Performance — ranked 9th — is where the most engineering effort has gone: four bespoke caching layers, a narrow-fetch `League` subclass, single-flight locks. |
| **Evidence** | `Dockerfile:20` + `docker-compose.yml` (no backend volume) + `deploy.yml` (`--force-recreate`) · `league/cache.py` |
| **Implication** | Reordering effort to match this list is most of the rebuild's justification. |

---

## §21 · Developer and agent comprehensibility

The clause's own 17 questions, scored against the current repo. **This is the acceptance test for any proposed architecture.**

| Question | Answerable today? |
|---|---|
| Where does external data enter FCP? | ⚠️ Three places: `data_feed.connect()`, `nbadata/*`, direct browser→Supabase |
| What is the canonical FCP player? | ❌ Does not exist — a normalized name string |
| What is the canonical league? | ⚠️ Split: `leagues` row + `LeagueContext` + `MyLeague` (an ESPN object) |
| What is the canonical fantasy team? | ❌ A team-name string; no entity |
| What is the canonical roster? | ❌ A DataFrame shape |
| What is the canonical matchup? | ⚠️ Several shapes across `matchups_df`, scoreboard payloads, `canonical_matchups()` |
| What is the canonical projection? | ✅ `PlayerProjection` |
| Where does basketball business logic live? | ❌ Mostly `data_feed.py`, some in routers |
| Where does user-specific logic live? | ❌ Nowhere — it does not exist |
| What data is persisted? | ⚠️ Postgres + container disk + a SQLite file that does not exist |
| What data is calculated? | ⚠️ Varies by endpoint |
| What data is current vs historical? | ❌ Not determinable from the URL or the schema |
| What data belongs to a user? | ❌ Only `team_name` |
| What data belongs to a league? | ✅ Reasonably clear |
| What can each user access or mutate? | ❌ Undefined for 53 routes |
| Where should a new feature be implemented? | ⚠️ Precedent conflicts by PR series |

**Score: 2 clear, 6 partial, 8 unanswerable.** The clause's own failure condition — *"if answering those questions requires extensive repository archaeology, the architecture has failed"* — is met.

---

## §22 · Explicit non-goals

| | |
|---|---|
| **Requires** | No native apps, real-time chat, social network, every platform, distributed infra, multi-sport, speculative ML, every provider, play-by-play, premature billing. |
| **Status** | **MET** |
| **Today** | None of these exist. The one adjacent risk is `docs/specs/FCP_PROJECTIONS.md` M-7 (gradient boosting) — but it is explicitly gated on measured improvement against M-2, which is the correct guard. |

---

## §23 · Architectural north star

> *"A shared fantasy league world that is fun to follow, powered underneath by a private analytical weapon for managers who want to win… The architecture should make those relationships obvious rather than allowing them to become three unrelated products accidentally sharing a repository."*

| | |
|---|---|
| **Status** | **VIOLATED** — and the clause names the exact current failure mode |
| **Note** | The audit reached this independently, from code rather than intent: *"FCP is three products sharing one process — a draft optimizer, a league newsroom, and a projections research platform. They share a player-name join key and an ESPN connection, and almost nothing else."* Two different methods, same conclusion. |
| **Implication** | The shared basketball-intelligence layer is what makes the three one product. It is the load-bearing element of the target design. |

---

## Cross-cutting notes for the architecture phase

### A. §4 and §5 are in tension — resolving it is a load-bearing decision

§4 wants **one** shared intelligence layer. §5 wants **per-user** projection sources and adjustments, while league-shared analytics use a **pinned** default methodology.

The same computation must therefore run in two modes:

```
shared  → compute(facts, source = league.default_source, adjustments = ∅)
private → compute(facts, source = user.preferred_source, adjustments = user.adjustments)
```

This only works if the intelligence layer is a **pure function of explicit inputs** rather than a service that reads "the active projections" from ambient state. Today's `get_active_projections()` reads a process-global singleton off disk — structurally the opposite. Every domain function must take its projection view as a parameter.

### B. Three clauses collapse into one missing concept

§10 (historical correctness), §11 (explicit freshness), and the three-snapshot-table duplication all trace to one absent idea: **week finality.** Once a league week is `final`, its results are immutable and never refetched. With that concept, one `matchups` table replaces `league_state_snapshots` + `league_week_scoreboards` + `league_week_transactions`, and every read path knows its own freshness class.

### C. Observability is missing from §20 and should be added

Every failure mode this system has produced has been **silent**: `/matchup-confidence` returning 500 in production apparently unnoticed; players silently dropped from projection sets on a name mismatch; the 140–171s construction discovered only by reading production logs; the M-3a backtest command that could never have run. §20 lists ten priorities and none is *"you can tell when it is broken."* Recommend adding it between testability and feature velocity.

### D. Questions the constitution still does not answer

1. **Self-delivering recaps** — the dossier's founding goal ("the demo that sells this") is absent from §13. Dropped, or assumed? It determines whether outbound delivery, scheduling, and delivery state exist at all.
2. **Publish FCP projections publicly?** §6 settles ownership; publication is still open, and §5's redistribution constraint may conflict with `FCP_PROJECTIONS.md` §5's public "our model vs Basketball Monster, measured" page.
3. **Data vs code under §18's zero-sunk-cost rule** — see §18 above.
4. **Offseason assumption-maintenance burden** — `FCP_PROJECTIONS.md` §4 calls it "the part BBM actually charges for" and flags it as a real risk. A labour commitment, not an engineering one.

---

*Traceability current as of `8092789`. Findings sourced from [`CLAUDE_FCP_AUDIT.md`](CLAUDE_FCP_AUDIT.md); code references are `path:line` against that commit.*
