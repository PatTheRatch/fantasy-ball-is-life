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
- **Regression:** current BBM flow (Streamlit + React) produces the same
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
