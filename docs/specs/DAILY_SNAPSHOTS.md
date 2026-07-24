# Feature Spec: Daily Roster & Scoreboard Snapshots

**Status:** Product direction set by Patrick (owner) 2026-07-24 — pending
Aisha's technical review before implementation (per
`docs/AISHA_OPERATING_MANUAL.md`).
**Author:** Claude Code (implementation engineer)
**Date:** 2026-07-24
**Decision basis:** Capture longitudinal league state daily so we can build
richer analysis later. Both daily rosters **and** true intra-week scoreboard
*progression* are effectively **un-backfillable** (see §1) — ESPN doesn't
preserve mid-week roster/lineup state — so the value of capturing them now does
not depend on knowing the eventual use.

---

## 1. Why now — both datasets capture something ESPN doesn't keep

ESPN's API answers "what is this roster **right now**?" and "what were the
**final box scores** for a past matchup period?" — but it does **not** preserve
mid-week roster/lineup state. Once waivers run and a player is dropped, both the
prior roster *and* the day-by-day picture that depended on it are gone.

- **Daily rosters are ephemeral.** ESPN won't tell you who was on a team's
  roster last Tuesday. Capture them today or lose them permanently — the classic
  record-now-or-never case, worth doing even before we've decided what analysis
  it feeds.
- **Daily scoreboard *progression* is also effectively un-backfillable.** This
  is the subtle one, and an earlier draft of this spec got it wrong by calling
  daily scoreboards merely "reconstructable." What's actually reconstructable
  from ESPN is the **final week total** (that's what the `league_week_scoreboards`
  backfill relies on) — *not* the honest "who was ahead at the end of day 2."
  Rebuilding a mid-week standing requires knowing each team's active lineup on
  each day, and ESPN's final box score blurs or loses the contributions of
  players who were streamed in and dropped again before the week ended. So the
  deeper a league's in-week add/drop activity, the less faithfully the day-by-day
  score can be rebuilt. **The only clean source of true intra-week progression
  is to snapshot it as it happens.**

Both gaps share one root cause: **mid-week roster state that ESPN doesn't
retain.** That's why both belong in the priority tier — not rosters alone.

What *is* still reconstructable: final weekly results (already handled by
`league_week_scoreboards`). Daily capture is about the *trajectory*, not the
endpoint.

Storing complete daily blobs (rather than a premature normalized schema) means
any later reshaping — per-player timelines, churn metrics, lead-change
timelines — is itself backfillable *from our own storage*. Capture completely
now; normalize when a concrete use demands it.

## 2. What we capture

Two datasets, both once per day per league:

1. **Roster snapshot** — each team's full roster as of the capture time:
   players, positions, lineup slot (starter/bench/IR), and acquisition info
   where ESPN exposes it. Sourced from `feed.rosters_df(handles, on_date)` /
   `feed.get_current_rosters(...)` in `backend/league/data_feed.py`.
2. **Daily scoreboard snapshot** — the running category scoreboard for the
   current matchup week as of the capture time (intra-week progression).
   Sourced from `feed.get_current_scoreboard(handles, scoring_period=week)` —
   the same call the 15-min refresh worker already makes.

Capture happens **once daily, shortly after waiver processing** (§5), so the
roster snapshot reflects the post-waiver state — the moment the day's adds,
drops, and waiver claims have settled.

## 3. Data model

Two new tables, mirroring the immutable-per-bucket shape of
`league_week_scoreboards` (one row per time bucket, service-role write,
public-league RLS read).

### `league_roster_snapshots`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | `gen_random_uuid()` |
| `league_id` | uuid fk → leagues | |
| `season` | int | |
| `capture_date` | date | the day this snapshot represents |
| `espn_team_id` | int | ESPN team id (stable within a season) |
| `team_name` | text | denormalized for convenience (ESPN renames happen) |
| `payload_json` | jsonb | that team's full roster (players + slots + acquisition) |
| `captured_at` | timestamptz | exact capture instant |
| | | **unique (league_id, season, capture_date, espn_team_id)** |

Grain = one row per team per day. Fine for "roster on date X" and "player P's
ownership over time" (jsonb query); not so fine-grained that we normalize
prematurely. A normalized per-player-day table can be derived later from these
blobs if a feature needs it.

### `league_daily_scoreboards`
| Column | Type | Notes |
|---|---|---|
| `id` | uuid pk | |
| `league_id` | uuid fk → leagues | |
| `season` | int | |
| `capture_date` | date | |
| `week` | int | matchup period in progress that day |
| `payload_json` | jsonb | scoreboard rows (same shape as the scoreboard phase) |
| `captured_at` | timestamptz | |
| | | **unique (league_id, season, capture_date)** |

Both tables: `alter table … enable row level security;` + a
"read for public leagues" policy identical to `league_week_scoreboards`
(service role — the worker — is the only writer).

## 4. Capture job

- New worker entrypoint `backend/worker/daily_snapshot.py` exposing
  `capture_all_leagues()` that iterates every league (reusing the
  `RecapStore.list_league_slugs()` + per-league try/except **failure
  isolation** pattern from `refresh_all_leagues()`), and per league:
  1. resolve credentials + `connect()` (same as `refresh_league`);
  2. compute the current `capture_date` and `week`
     (`handles.league.currentMatchupPeriod`);
  3. upsert each team's roster into `league_roster_snapshots`
     (`on_conflict=league_id,season,capture_date,espn_team_id`, idempotent —
     re-running the same day is a no-op);
  4. upsert the day's scoreboard into `league_daily_scoreboards`
     (`on_conflict=league_id,season,capture_date`).
- New store methods on `RecapStore`: `upsert_roster_snapshot(...)`,
  `upsert_daily_scoreboard(...)`, and read helpers
  (`get_roster_snapshot(league_id, season, date, team)`,
  `list_roster_snapshot_dates(...)`).
- **Idempotent by date**, so a retry (or a second run in the same day) never
  duplicates. Off-season / pre-draft leagues: skip cleanly if ESPN returns no
  roster (no error, just record nothing).

### Scheduling
- New systemd unit pair in `deploy/`: `fcp-daily-snapshot.service` (oneshot,
  curls a secret-guarded `POST /admin/daily-snapshot`, mirroring the existing
  `fcp-snapshot-refresh` unit) + `fcp-daily-snapshot.timer`.
- `POST /admin/daily-snapshot` on the admin router, guarded by the existing
  `WORKER_SECRET`, calling `capture_all_leagues()` — same shape and guard as
  `POST /admin/refresh-all`.

## 5. The one real decision: *when* is "after waivers"

"An hour after waivers" is **league-specific** — ESPN waiver processing
day/time is a per-league setting. Two options:

- **Phase 1 (recommended start): one fixed daily capture time**, chosen to sit
  after typical overnight ESPN waiver processing (e.g. **11:00 UTC ≈ 6–7am ET**).
  Simple, and it secures the un-backfillable roster data immediately. A single
  `OnCalendar=*-*-* 11:00:00` timer.
- **Phase 2 (later, optional): per-league waiver-aware timing** — read each
  league's waiver settings and schedule the capture ~1h after that league's
  processing window. More correct; more work. Not worth blocking Phase 1 on.

Recommendation: ship the fixed-time capture now (data starts banking today),
refine to per-league timing once the simple version is proven.

## 6. Storage estimate

Deliberately generous, since the owner is fine buying Supabase space:

- **Rosters:** ~12 teams × ~180 capture days ≈ **2,160 rows/league/season**
  (each a small roster blob). At 100 leagues ≈ 216k rows/season — trivial for
  Postgres.
- **Daily scoreboards:** ~180 rows/league/season. Negligible.

No retention policy in v1 — keep everything (that's the point). Revisit
cross-season retention only if it ever becomes material (it won't soon).

## 7. Phases

| Phase | Scope | Depends on | Done when |
|---|---|---|---|
| **D-1** | `league_roster_snapshots` migration + store upsert/read methods | — | Migration applies in `test-rls`; store methods unit-tested |
| **D-2** | `capture_all_leagues()` roster capture + `POST /admin/daily-snapshot` (WORKER_SECRET) + failure isolation | D-1 | Hermetic tests: all leagues captured, one failure isolated, idempotent same-day re-run |
| **D-3** | `fcp-daily-snapshot` service + timer (fixed daily time) | D-2 | Unit deployed; a real capture writes one row/team/day |
| **D-4** | `league_daily_scoreboards` migration + capture wired into the same job | D-2 | Daily scoreboard row written per league per day |
| **D-5** *(optional, later)* | Per-league waiver-aware capture timing | D-3 | Capture fires ~1h after each league's waiver window |

D-1→D-4 (rosters *and* daily scoreboards) is the priority path — both capture
un-backfillable mid-week state (§1). Rosters lead only because they're the
simplest first slice, not because scoreboards are optional. D-5 is a later
refinement.

## 8. Test plan

- Store methods: upsert targets the right conflict key; reads filter by
  date/team; empty → `None`/`[]`.
- Capture job (hermetic — mock `connect`/feed + `RecapStore`): every league
  captured; one league failing does not block others; same-day re-run is
  idempotent (no duplicate rows); a league with no roster records nothing
  without erroring.
- Endpoint: `POST /admin/daily-snapshot` requires `WORKER_SECRET` (403/500
  cases), returns a per-league result map.
- **Run the suite in a clean env** (`env -u CRED_ENCRYPTION_KEY … pytest`) and
  mock `RecapStore` with a real-signature spec so a missing/leaked env var or a
  store-signature drift fails locally, not only in CI.

## 9. Risks & open questions

- **ESPN rate/ToS** — one extra roster pull per league per day is negligible
  vs the existing 15-min refresh; unchanged risk profile.
- **Roster shape stability** — ESPN roster fields (lineup slots, acquisition
  type) vary; store the raw shape and normalize downstream, so a field change
  never breaks capture.
- **Team identity** — `espn_team_id` is stable within a season; team *names*
  change (we store both). Cross-season identity is out of scope.
- **Open:** exact fixed capture time (11:00 UTC is a starting proposal — tune
  to observed waiver processing).
- **Open:** whether daily scoreboards should also seed the
  `league_week_scoreboards` final-week row (avoids a separate backfill) — decide
  in D-4.

## 10. Out of scope (v1)

- Any user-facing UI or analysis on this data — this spec is **capture only**.
  Timelines, churn metrics, waiver-ROI, ownership graphs, and **intra-week
  lead-change / comeback-and-collapse tracking** ("you were up 6–1 on
  Wednesday and lost") are separate features built later *on top of* the
  stored snapshots — and that last one is only possible *because* we capture
  daily progression (§1).
- Normalized per-player-day tables (derive later from the blobs if needed).
- Cross-season player/team identity resolution.
- Retention/archival policy.
