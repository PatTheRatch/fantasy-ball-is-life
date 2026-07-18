# Feature Spec: Pluggable Projection-Source Framework

**Status:** Open questions resolved by Patrick (product owner) 2026-07-08 —
pending Aisha's technical review before implementation
(architecture decision per `docs/AISHA_OPERATING_MANUAL.md`)
**Author:** Claude Code (implementation engineer)
**Date:** 2026-07-08
**Decision basis:** Product Decision B — user-uploaded projections now, our own
model later, all behind one framework.

---

## 1. User story

> As a fantasy manager, I want to bring projections from whichever source I
> trust — Basketball Monster, ESPN, Hashtag Basketball, or this app's own model —
> so that the optimizer, matchup win-probabilities, and recaps all run on *my*
> numbers without me reshaping spreadsheets by hand.

Secondary story (product): as the product owner, I want our own projection model
to be "just another source," so shipping it later requires zero changes to the
optimizer, dashboard, or recap features.

## 2. Acceptance criteria

1. A user can bring in projections from Basketball Monster (`.xls/.xlsx`
   upload, season **or** weekly export) or Hashtag Basketball (CSV upload or
   pasted table text), and the app auto-detects the source (with a manual
   override dropdown). ESPN exports are a follow-up adapter.
2. Whatever the source, the upload is normalized into one canonical
   `PlayerProjection` schema (§3). All downstream consumers (optimizer,
   matchup confidence, projected scoreboards, recaps) read **only** that schema —
   zero references to source-specific column names (`p/g`, `3/g`, …) outside the
   adapters.
3. Player names from any source resolve to ESPN roster players via the existing
   normalize + fuzzy-match pipeline; unmatched players are surfaced to the user
   (not silently dropped), with a count and a review list.
4. An upload that fails validation returns a clear error naming the missing/bad
   columns — never a 500, never a half-ingested state.
5. The active projection source is visible in the UI wherever projected numbers
   are shown (e.g. "Source: BBM season export, uploaded 2026-07-08").
6. Adding a new source requires writing one adapter class + tests only — no
   changes to consumers. (Proven by implementing at least two adapters in v1 of
   this feature.)

## 3. Data model impact

New canonical schema — `PlayerProjection` (one row per player per source upload):

| Field | Type | Notes |
|---|---|---|
| `player_key` | str | normalized name key (existing `normalize_name`) |
| `display_name` | str | as provided by source |
| `team` | str/null | NBA team code |
| `positions` | list[str] | e.g. `["PG","SG"]` |
| `games` | float/null | projected games (season or week horizon) |
| `minutes_pg` | float/null | |
| `pts_pg, reb_pg, ast_pg, stl_pg, blk_pg, tpm_pg, to_pg` | float | per-game counting stats |
| `fga_pg, fta_pg` | float | attempts (needed for FG%/FT% math) |
| `fg_pct, ft_pct` | float | |
| `value` | float/null | source's overall value/rank if present (BBM `$`/`LeagV`) |
| `injury_status` | str/null | |

New metadata record — `ProjectionSet`:

| Field | Notes |
|---|---|
| `source` | `bbm` \| `espn` \| `hashtag` \| `internal` \| `custom` |
| `horizon` | `season` \| `week` |
| `uploaded_at`, `filename` | provenance |
| `row_count`, `matched_count`, `unmatched_players` | ingest quality report |

Storage for v1: normalized parquet/JSON on disk under `data/projections/`
(gitignored), one file per `ProjectionSet`; latest-per-source index in a small
JSON manifest. No database migration required yet — when we add a DB, these two
schemas become its first two tables. **Derived stats (`fgm_pg = fga_pg × fg_pct`,
per-week scaling) are computed by consumers, not stored.**

## 4. API / UI impact

**API (replaces the current BBM-only pair):**

- `POST /projections` — multipart upload + optional `source` and `horizon` form
  fields (auto-detect when omitted). Returns the `ProjectionSet` metadata incl.
  match report. Existing callers keep working during migration via a
  `source=bbm` default.
- `GET /projections` — returns normalized rows for the active set;
  `?source=&horizon=` filters.
- `GET /projections/sets` — list uploaded sets with provenance + match quality.
- `PUT /projections/active` — choose which set the app currently uses.

**Internal:** `data_feed.read_projections_xls()` becomes the guts of
`BbmAdapter`; `optimize_lineup.py` and the projected-scoreboard path switch from
raw BBM column names to `PlayerProjection` fields.

**UI (React):**

- Upload card gains a source dropdown (default "auto-detect") and shows the
  post-upload match report (rows read / matched / unmatched list).
- A small "Projections: {source} · {date}" badge on Draft, In-Season, and
  projected-scoreboard views (acceptance criterion 5).

## 5. Test plan

- **Adapter unit tests** with a golden fixture file per source (small,
  anonymized): assert exact normalized output, including TO handling and
  FG%/FT% attempt columns.
- **Auto-detect tests:** each fixture is detected correctly; ambiguous files
  fall back to "ask the user" rather than guessing.
- **Name-resolution tests:** accents, punctuation, Jr./III suffixes, and a
  known-unmatched name → appears in `unmatched_players`.
- **Contract test for consumers:** run the draft optimizer end-to-end against a
  fixture `ProjectionSet` from two different sources; identical schema in →
  valid roster out from both.
- **Validation tests:** truncated file, missing required columns, empty file →
  4xx with a named-column error; manifest/state unchanged.
- **Regression:** current BBM flow (React) produces the same
  optimizer results before and after the refactor on the same input file.

## 6. Rollback / failure considerations

- **Ingest is atomic:** normalize → validate → write to a temp path → swap into
  the manifest. A failed upload leaves the previously active set untouched.
- **Feature flag:** consumers read through one accessor
  (`get_active_projections()`). If the framework misbehaves, we point that
  accessor back at the legacy BBM reader — one-line rollback, no data loss.
- **Bad projections are user-fixable:** the active-set switcher (`PUT
  /projections/active`) doubles as rollback to any earlier upload.
- **Failure modes to design for:** source changes its export format (adapter
  version pinned per upload; detection fails loudly), duplicate player rows
  (dedupe rule: keep highest-minutes row, report it), and partially matched
  uploads (proceed, but badge the match rate in the UI so the user knows).

---

## Design sketch (for review, not binding)

```
ProjectionAdapter (protocol)
  ├── detect(file) -> confidence          # sniff headers
  ├── parse(file) -> list[PlayerProjection]
  └── source_id, supported_horizons

Registry: [BbmAdapter, HashtagAdapter, EspnAdapter, InternalModelAdapter*]
                                                       (*future — Decision B)
Resolver: normalize_name + rapidfuzz against ESPN rosters (existing code, reused)
Store:    data/projections/{source}_{horizon}_{timestamp}.parquet + manifest.json
Accessor: get_active_projections(horizon) -> DataFrame[PlayerProjection]
```

**v1 scope (per Patrick's answers, 2026-07-08):**

- `BbmAdapter` — port of the existing reader; handles **both horizons**:
  season exports (`BBM_Projections.xls`, needed for the draft) and weekly
  exports (`WeeklyProjections.xls`).
- `HashtagAdapter` — second adapter. Hashtag Basketball is a paid source and
  its site blocks automated access, so the adapter must be **input-tolerant**:
  accept (a) a CSV/Excel file if their premium tier exports one, and (b) a
  **pasted table** (user copies the projections table from the browser into a
  textarea; adapter parses tab/whitespace-delimited text). No scraping — it's
  unreliable against their bot protection and a ToS risk.
- Store/accessor (on-disk parquet + manifest), the four endpoints, and the
  upload UI with the paste option.
- ESPN adapter and the internal model are follow-ups.

**Resolved questions (Patrick, 2026-07-08):**
1. ~~Database?~~ **Deferred** — on-disk parquet + manifest store for v1;
   schemas become the first DB tables when a database is introduced.
2. ~~Second adapter?~~ **Hashtag Basketball**, with the caveat above: it is not
   free, export availability is unconfirmed (site 403s automated checks), so
   the adapter ships with file **and** paste-input modes. Action: verify with a
   real Hashtag account whether premium offers CSV export; if yes, add a golden
   fixture from it.
3. ~~Horizons?~~ **Both in v1** — season projections (required for the draft
   optimizer) and weekly-horizon uploads. `ProjectionSet.horizon` is therefore
   load-bearing from day one, and the accessor takes `horizon` as a required
   argument.

---

## Addendum: Implementation sequencing + ESPN adapter moved into v1 (2026-07-14)

Prompted by Patrick scoping the app's intra-week features (a live per-matchup
scoreboard + projections). The live scoreboard already exists end-to-end
(`/scoreboard/current` → `get_current_scoreboard()` → `InSeason.tsx`) and
needed no new work. Projections is this framework — but Patrick's stated
priority reorders v1: **default to ESPN's own rolling stats first** (no manual
download required every week), with BBM/upload as the alternative, not the
other way around. §"v1 scope" above (2026-07-08) sequenced `BbmAdapter` and
`HashtagAdapter` first and called an ESPN adapter a follow-up; this addendum
supersedes that ordering only — the acceptance criteria and data model are
unchanged.

**Why this is cheap to move up:** the underlying logic already exists.
`get_current_rosters()` (`backend/league/data_feed.py:1391-1502`) already reads
each roster player's ESPN `Last 15`/`Last 30` day averages
(`player.stats["{year}_last_{15,30}"]`) and projects rest-of-week production
by multiplying by games remaining — this is not new code, it's an existing
function that needs porting into the `ProjectionAdapter` shape.

**Hard constraint this framework must respect:** ESPN's rolling Last-15/30
splits only exist mid-season (no games played yet at draft time), so
`EspnAdapter` can only ever serve `horizon = 'week'`. The draft optimizer's
`horizon = 'season'` need is unaffected by this reordering and still requires
BBM (or an equivalent season-long source) — `EspnAdapter` does not replace
`BbmAdapter`, it just ships first for the horizon it *can* serve.

### PR sequence

| PR | Scope | Notes |
|---|---|---|
| **P-1** | `EspnAdapter` (`horizon='week'` only) + a minimal `get_active_projections('week')` accessor defaulting to it; wire the in-season projected-scoreboard view to use it with zero setup (no upload required) | Port of the existing Last-15/Last-30 logic in `get_current_rosters()` — no store/manifest needed for this adapter specifically (ESPN is always live, nothing to persist). Smallest, safest PR; delivers Patrick's "don't depend on downloading BBM every week" want immediately. `detect()` trivially returns high confidence always (not file-based). |
| **P-2** | Store + manifest (`data/projections/`, parquet + `manifest.json`) + `BbmAdapter` (both horizons — season horizon is required for the draft optimizer, which `EspnAdapter` cannot serve) + the four endpoints (`POST/GET /projections`, `GET /projections/sets`, `PUT /projections/active`) | Port of existing `read_projections_xls`/`add_bbm_projections`. Existing callers keep working via the `source=bbm` default (spec §4). |
| **P-3** | Swap consumers — draft optimizer (season horizon), projected scoreboard + matchup confidence (week horizon) — off raw BBM/ESPN columns onto `PlayerProjection` / `get_active_projections()` | Contract test required by spec §5: identical optimizer output before/after the refactor on the same BBM fixture file. |
| **P-4** | Upload UI: source dropdown (default auto-detect), post-upload match report, "Projections: {source} · {date}" badge on Draft / In-Season / projected-scoreboard views | Acceptance criterion 5. |
| **P-5** | `HashtagAdapter` (file + paste-input modes) | Last, per the spec's own caveat: paid source, export availability unconfirmed. Open action item carried over from 2026-07-08: verify with a real Hashtag account before building the fixture. |

P-1 through P-3 are the load-bearing pieces (a real source-agnostic accessor
existing consumers actually read through). P-4 is UI polish on top of a
working P-2/P-3. P-5 is intentionally last — it's the one adapter with
unresolved real-world access questions, and nothing else in v1 depends on it.

---

## Addendum: post-merge review — precedence & lifetime decisions (2026-07-14)

P-1..P-5 merged and were reviewed against this spec (Claude, 2026-07-14). The
adapters, store, and endpoints individually work as scoped. The review found a
cluster of bugs sharing one root cause the spec never pinned down: **precedence
and lifetime for the `week` horizon** — when an uploaded set, the live ESPN
source, and a per-request override disagree, who wins and for how long.
Confirmed consequences in the merged code:

- An uploaded weekly BBM set stays active forever (no expiry, no clear
  affordance) — live ESPN becomes unreachable without hand-editing
  `manifest.json`, defeating the ESPN-first goal of the addendum above.
- The In-Season "BBM File" per-request upload is dead: the framework path in
  `get_projected_scoreboard()` always yields rows (ESPN fallback), so the
  legacy `bbm_df` branch is unreachable — an uploaded file silently renders
  ESPN numbers instead.
- `ProjectionBadge` shows the most recently *uploaded* set, not the *active*
  one (wrong after a rollback via `PUT /projections/active`).
- A bare `except Exception` around the framework path hides any live
  `EspnAdapter` failure — invisible degradation to the legacy path, no log.
- P-3's optimizer swap is capability-only: no production `OptimizeLineup`
  call site passes `projections_rows`, so uploads have zero effect on the
  live Draft Room.
- `HashtagAdapter` maps `fgm`/`ftm` columns to fields that don't exist on
  `PlayerProjection` and never derives FG%/FT% from makes+attempts — that
  data is silently dropped.
- Both `get_current_rosters()` and `EspnAdapter` hardcode the `2026_last_N`
  stats key — silently all-zero projections at next season's rollover.

**Decisions (Patrick, 2026-07-14):**

1. **Week-scoped uploads + manual clear.** `ProjectionSet` gains a `week`
   field (for `horizon='week'` sets), defaulted from the current matchup
   period at upload time and overridable in the upload form.
   `load_active('week')` honors a set only while its week matches the current
   matchup week — ESPN comes back automatically at week rollover. A manual
   clear affordance also exists for mid-week escape.
2. **ESPN is a virtual, always-available set.** Registered in the manifest
   (`source='espn'`, no parquet file). Selecting it is the ordinary
   `PUT /projections/active`; picker and badge treat it uniformly
   ("Projections · ESPN Last 15 · live"). The registry special-cases the
   virtual id by calling `EspnAdapter` live.
3. **Explicit request wins.** A per-request `projections` param or uploaded
   `bbm_df` overrides the store for that request only; the store is the
   default when the request doesn't specify a source. Restores the original
   per-request upload semantics.

Symmetry note: clearing/expiring the `season` horizon falls back to the
optimizer's legacy on-disk `BBM_PROJECTIONS_PATH` read — acceptable, but say
so in the endpoint description rather than leaving it implicit.

### Fix-PR sequence

| PR | Scope | Notes |
|---|---|---|
| **P-6** | Store/registry semantics: `week` field on `ProjectionSet` + week-scoped `load_active`; virtual ESPN set + clear affordance; precedence in `get_projected_scoreboard()` (explicit request → store → ESPN live), restoring the per-request `bbm_df` path; replace the silent `except Exception` with a logged fallback | The load-bearing fix — everything else builds on these semantics |
| **P-7** | Badge + picker: `ProjectionBadge` reads the true active set (incl. virtual ESPN, e.g. via an `is_active` flag or a dedicated active endpoint); In-Season source picker gains an "Uploaded set" option and a switch-back-to-ESPN affordance | Depends on P-6 |
| **P-8** | Deliver P-3's original claim: wire `get_active_projections('season')` into the draft router's `OptimizeLineup` construction sites (legacy disk read as fallback); contract test at the router level, not just the translation function | Closes the "capability-only" finding |
| **P-9** | Small fixes: `HashtagAdapter` derives FG%/FT% from FGM/FGA + FTM/FTA when only makes/attempts are present (or the dead mapping + comment are removed); remove unused `_BASE_STATS`; derive the `{SEASON}_last_N` stats key from config in both `get_current_rosters()` and `EspnAdapter` | Independent of P-6/P-7; can land any time |

---

## Addendum: season-boundary robustness + intra-week validation (2026-07-15)

Prompted by two questions from Patrick while P-6 was in flight: what happens
when the season is over or not yet started, and can the intra-week projected
scoreboard actually be tested. Both investigated against the live league in
its current (offseason) state; findings below.

### What actually happens at the boundaries (verified live)

- **Season over (current state):** benign. The real endpoint forces the
  projection window to `now → week_end`; in the offseason that's *inverted*
  (start after end), so zero games fall in it → projected == current final
  tallies. `get_projected_scoreboard()` runs without error and shows finals.
  Two minor artifacts:
  - It writes a stray `Week {N}_scoreboard.csv` (and a `week_{N}_roster.csv`
    on the legacy path) into the process working directory on **every** call —
    leftover debug `.to_csv`. Real litter/perf bug.
  - Viewing a *completed* week in projected mode with that week's own explicit
    dates (not `now`) double-counts: current already holds the whole week and
    the projection adds the same games again.
- **Preseason (before week 1, games scheduled but unplayed):** the ideal case —
  current == 0, full week projected. Fine.
- **Next season (2026-27) — the real landmine:** the weekly calendar is a
  hardcoded constant, `MATCHUP_WEEKS_2025_26`, containing 2025-26 dates only.
  At rollover `currentMatchupPeriod` resets to 1, but week 1 still maps to last
  October's dates, so the window never overlaps the new schedule →
  `games_left = 0` for everyone → **projections silently return all zeros.**
  Compounded by the `2026_last_N` stats-key hardcode (P-9). The feature does
  not error at season start — it quietly returns nothing until both the
  calendar and the stats-key year are updated, which is worse because nobody
  notices.

### Can intra-week be tested now?

- **Not against live ESPN:** offseason has no in-progress games, and the
  `now → week_end` window is empty, so the live path yields zero projections.
  Genuine live validation is only possible once 2026-27 games are being played
  (~Oct 2026) *and* the calendar is fixed.
- **Historical replay does not work:** ESPN finalizes completed weeks, so
  `get_current_scoreboard(past_week)` returns full-week finals, never a
  "3 of 5 games played" mid-week snapshot. Replaying a past week gives
  `final + remaining-games projection` = double count; a genuine partial week
  cannot be reconstructed from history.
- **What works now:** a synthetic-fixture integration test. Build a fake
  `ESPNHandles` (teams/rosters with Last-N averages + a schedule, plus a fake
  partial box score) representing "Wednesday, 3 of 5 games played," and assert
  the merge: `projected == current + avg × games_left`, plus the per-category
  W/L logic. This validates the merge math and would catch the double-count and
  inverted-window bugs. It does **not** validate live ESPN field shapes — that
  is inherently a live-season check. (P-6's tests cover store/registry
  precedence but no test exercises the current+projected merge itself.)

### Fix-PR additions

| PR | Scope | Notes |
|---|---|---|
| **P-10** | Season-boundary robustness: de-hardcode the weekly calendar (derive per-season, or key it by `config.SEASON` so rollover doesn't silently zero everything) and pair it with P-9's stats-key year fix; guard the inverted/empty window explicitly (return "no projection available" state rather than a misleading zeroed one); remove the stray `.to_csv` debug writes from the scoreboard/roster path | Higher-stakes than P-9's cosmetics — this is what silently breaks the whole projected view at next season's start |
| **P-11** | Synthetic intra-week integration test: a fake `ESPNHandles` at a mid-week state (partial box score + games remaining) asserting `projected == current + avg × games_left` and the per-category W/L result; the only way to validate the merge before live games return | Closes the untested-merge gap; complements P-6's precedence tests |
