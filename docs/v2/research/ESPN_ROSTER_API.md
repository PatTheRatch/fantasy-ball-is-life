# ESPN roster API — external research + first-party verification

**Source:** ChatGPT (with browsing), commissioned 2026-08-22 to answer
[`BACKLOG.md`](../BACKLOG.md) open question #2 (*roster fetch cost — one request
per team per day, or one league-wide call?*).

**Status of this document:** the memo below is **external research, not a
decision**. Read §0 first — it records what our own live evidence confirms,
what it contradicts, and what the memo missed. Nothing here changes the schema
or the ingestion design until it is verified against a live league.

---

## §0 · Verification against first-party evidence

Checked against [`docs/ESPN_API_REVIEW.md`](../../ESPN_API_REVIEW.md) — V1's
live investigation against the real Patriot Games league, whose findings are
marked *confirmed* where reproduced against live data. That document outranks
the memo wherever the two disagree: it is measurement, not literature review.

| Memo claim | Verdict | Our evidence |
|---|---|---|
| `mRoster` is league-wide; one call returns every team's roster | **Confirmed** | V1 measured `mTeam,mRoster,mMatchup,mSettings,mStandings` as a **single 1,722,007-byte request** returning all 14 teams. A 14-team league costs 1 request, not 14. **This resolves open question #2.** |
| Box scores are one request per period via `mMatchupScore,mScoreboard` | **Confirmed** | V1: `league.box_scores(matchup_period=week)` = 1 request, 333,423 bytes for week 21. |
| `scoringPeriodId` is the daily atom for basketball | **Confirmed** | Consistent with V1's per-scoring-period transaction backfill and with `PROVIDER_INGESTION_DESIGN.md`. |
| Don't trust `mRoster&scoringPeriodId=N` as a historical roster store | **Adopt as-is (unverified, conservative)** | We have no first-party test either way. The memo's caution is the safe default and costs us nothing. |
| Lineup-change timestamps: investigate `MOVED` events in the league communication feed | **Contradicted for our stack** | V1 confirmed `recent_activity()` → `kona_league_communication` returns **HTTP 404** on our league. The memo's suggested audit trail is not available to us. |
| "No reliable field records when a manager moved a player into a slot" | **Contradicted — the memo missed the actual source** | See below. |

### What the memo missed: `mTransactions2` carries lineup movements

V1's weeks 1–21 backfill via `view=mTransactions2&scoringPeriodId={week}`
(plus an `x-fantasy-filter` header) returned 1,799 unique records, and the
item-level contract includes **source/destination lineup slot**, scoring
period, and proposed/process dates.

The season sample contained **872 `FUTURE_ROSTER` records holding 2,429
lineup-only items.**

V1 treated those as noise — correctly, for its purpose, since recap awards must
exclude lineup-only records. But for historical lineup capture they are not
noise: they are a **timestamped stream of lineup slot changes**, which is
exactly what the memo concluded did not exist.

### Why this matters more than the question we asked

[`PROVIDER_INGESTION_DESIGN.md`](../PROVIDER_INGESTION_DESIGN.md) §Sync
scheduling states:

> **Roster snapshots are the exception and must run daily from day one.** ESPN
> does not serve historical daily rosters, so a day not captured is gone
> permanently.

That premise now has two independent challenges:

1. The memo's `rosterForCurrentScoringPeriod` path — historical scoring-period
   rosters embedded in the matchup/scoreboard payload (memo confidence: high,
   ours: untested).
2. Our own `FUTURE_ROSTER` finding — a move stream that, anchored to one known
   roster state, reconstructs lineup history by replay. V1 demonstrably
   backfilled 21 weeks of it.

If either holds, daily roster capture is **recoverable**, not
capture-or-lose-forever, and the urgency that pushes historical capture to the
front of Slice 2 is overstated. If both fail, the design's premise stands and
every day of delay is permanent data loss.

**This is not a fact yet.** It is a live check, exactly the shape of S1-03 —
small, cheap, and it gates the sequencing of a whole slice. Recorded as open
question #6 in the backlog.

**Do not act on this by relaxing the daily-capture design.** The asymmetry is
brutal: if we relax it and the premise was right, the lost days are
unrecoverable. Keep daily capture in the design until the live check says
otherwise.

---

## §1 · The memo, verbatim

> Everything below this line is the external memo as delivered. Its confidence
> ratings are its own. Where §0 contradicts it, §0 wins.

### Scope

ESPN Fantasy Basketball (fba) roster data exposed by the undocumented API used
by fantasy.espn.com and libraries such as cwendt94/espn-api.
Research date: 2026-08-22.

### Executive summary

For Fantasy Basketball, the primary roster read is:

```
GET https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{YEAR}/segments/0/leagues/{LEAGUE_ID}
    ?view=mRoster
    &scoringPeriodId={SCORING_PERIOD_ID}
```

`mRoster` is league-wide. A single call returns `teams[]`, with each team's
roster under `teams[].roster.entries[]`; there is no need to issue one HTTP
request per fantasy team. ESPN also accepts a team-scoping parameter commonly
documented as `rosterForTeamId`, which can reduce the response to one team's
roster, but this is an optimization rather than a requirement. The `espn_api`
wrapper itself initializes a league by combining `mTeam`, `mRoster`, `mMatchup`,
`mSettings`, and `mStandings` in one request and then iterates `data["teams"]`.

The most important caveat is historical state. `scoringPeriodId` definitely
affects scoring-period-specific data returned with roster/player objects, but
the evidence is weaker that a bare `mRoster&scoringPeriodId=N` should be treated
as a canonical historical snapshot of roster membership and lineup placement for
arbitrary old NBA dates. Some reverse-engineered documentation describes
`mRoster` as returning the roster "for scoring period," while other
documentation explicitly calls the entries the current roster.

For a production platform that needs authoritative historical daily lineups, the
safer source is the scoring/matchup payload for that historical
`scoringPeriodId`, specifically
`schedule[].home/away.rosterForCurrentScoringPeriod.entries[]` returned through
the matchup/scoreboard family of views. That structure exists specifically to
represent the roster used for the requested scoring period. The current
`espn_api` Basketball implementation queries `mMatchupScore` + `mScoreboard`
with an explicit `scoringPeriodId` for its `box_scores()` path.

There is no published ESPN rate-limit contract. Community reports include users
sustaining roughly 60 requests/minute without obvious problems, but that is
anecdotal, not a safe documented quota. For one private league, a sync design
measured in tens or low hundreds of requests per day, batched into league-wide
calls rather than team-by-team calls, is dramatically below reported community
usage.

Finally, roster responses tell you what slot a player occupies and whether that
player/roster is currently locked, but the memo found no reliable field that
records the timestamp when a manager moved a player into that slot. ESPN's
league communication/activity feed does include a `MOVED` activity type, which
may offer an audit trail in some leagues.
*(§0: that feed 404s for us; `mTransactions2` is the real source.)*

### 1 · Roster endpoint and views

Canonical league endpoint:

```
https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba/seasons/{YEAR}/segments/0/leagues/{LEAGUE_ID}
```

`fantasy.espn.com/apis/v3/...` has historically worked as well, but newer
community documentation and ESPN's own browser traffic commonly use
`lm-api-reads.fantasy.espn.com`.

**Is it one request per team?** No. One league-wide call is sufficient. The
response is conceptually:

```json
{ "teams": [ { "id": 1, "roster": { "entries": [] } },
             { "id": 2, "roster": { "entries": [] } } ] }
```

**Team-only filtering.** A community writeup documents `rosterForTeamId={TEAM_ID}`
alongside `view=mRoster` and `scoringPeriodId`. There are also examples in the
wild using `forTeamId`, so ESPN's internal query vocabulary has varied over
time. Use it only as an optional bandwidth optimization after verifying it
against a current browser request.

**Combining views.** Views can be repeated
(`?view=mTeam&view=mRoster&view=mSettings&scoringPeriodId=42`). `espn_api`
initializes leagues with `["mTeam","mRoster","mMatchup","mSettings","mStandings"]`,
so combining views is normal ESPN client behaviour.

### 2 · Does `scoringPeriodId` give the roster as of that date?

**Proven:** basketball is a daily-scoring sport here; `scoringPeriodId`
identifies the atomic scoring day, whereas `matchupPeriodId` normally spans
several. ESPN accepts `view=mRoster&scoringPeriodId=N`, and reverse-engineered
clients (e.g. `ffscrapr`) have used that form for years.

**Not proven:** that `mRoster&scoringPeriodId=17` always returns exactly the
roster membership and slot assignments that existed at that period. One recent
project describes `mRoster` as returning "current roster entries for all teams"
even while requiring a `scoringPeriodId`. An entry combines three kinds of data
— fantasy roster membership, fantasy lineup slot, and player stat data for a
scoring period. Changing `scoringPeriodId` clearly changes the third. Whether
ESPN reliably rewinds the first two is less firmly documented.

**Community evidence on "how far back":** no well-supported test matrix was
found for basketball. There are *unanswered* `espn_api` threads specifically
about fetching prior-week basketball data, which is itself a warning.

Stronger evidence exists for old scoring-period box score state: `espn_api`'s
basketball implementation accepts historical `scoring_period` values and calls
`{"view": ["mMatchupScore","mScoreboard"], "scoringPeriodId": scoring_id}`. The
raw `schedule[]` payload has been observed to contain
`.home/.away.rosterForCurrentScoringPeriod.entries[]` with `lineupSlotId`,
`playerId`, and player data.

**Recommended interpretation:**

```
mRoster                                  = authoritative CURRENT roster
mMatchupScore / mScoreboard + period N   = preferred source for "who was in
                                           which slot on day N"
```

Capture the photograph when ESPN gives you the photograph. Do not assume the
current roster endpoint doubles as a time machine.

### 3 · Roster payload fields

At `teams[].roster.entries[]`:

```json
{
  "acquisitionDate": 1709863200000,
  "acquisitionType": "DRAFT",
  "injuryStatus": "ACTIVE",
  "lineupSlotId": 0,
  "pendingTransactionIds": null,
  "playerId": 4905919,
  "playerPoolEntry": {},
  "status": "ONTEAM"
}
```

**`lineupSlotId`** is the fantasy lineup position, not the NBA player's natural
position. The `espn_api` basketball map:

```
0 PG · 1 SG · 2 SF · 3 PF · 4 C · 5 G · 6 F · 7 SG/SF · 8 G/F
9 PF/C · 10 F/C · 11 UTIL · 12 BENCH · 13 IR · 14 (internal) · 15 Rookie
```

The robust starter test is therefore `lineupSlotId not in {12, 13}`.
**Do not hard-code "0 means starter" — in basketball 0 is PG.** The slot
universe is league-customizable; `settings.rosterSettings` is authoritative for
unusual leagues.

**`acquisitionDate`** — Unix epoch **milliseconds**. When the player was
acquired onto the roster, *not* when the lineup slot last changed.

**`acquisitionType`** — observed: `DRAFT`, `WAIVER`, `FREE_AGENT`, `TRADE`.

**Injury status** — two layers: `entries[].injuryStatus` and
`entries[].playerPoolEntry.player.injuryStatus` / `.injured`. `espn_api` reads
the entry then lets the nested player override. Store the ESPN string; do not
model an exhaustive enum (values have varied by sport/year).

**`playerPoolEntry`** — `id`, `onTeamId`, `lineupLocked`, `appliedStatTotal`,
`status`, and `player.*` (`id`, `fullName`, `defaultPositionId`,
`eligibleSlots[]`, `proTeamId`, `injured`, `injuryStatus`, `stats[]`). Some
payloads also expose `rosterLocked` and `tradeLocked` — current editability,
not history.

**`status`** — `ONTEAM`, `FREEAGENT`, `WAIVERS`, `INJURED_RESERVE`. Location
and meaning differ between `mRoster` and `kona_player_info`; retain the raw
value rather than collapsing into one semantic field.

### 4 · Authentication and rate limiting

Private leagues require browser-session cookies `espn_s2` and `SWID` (the
latter normally brace-wrapped `{XXXXXXXX-...}`). They are credentials — encrypt
at rest, never log.

**Published rate limit: unknown.** No documented quota, no stable rate-limit
header contract. A March 2025 r/fantasyfootballcoding discussion has one user
reporting "probably around 60 per minute without any issues" — one anecdote,
not a guarantee. The `espn_api` maintainer has warned that per-player request
workflows "might rate limit your request." There is also August 2026 evidence
of some ESPN public endpoints returning Akamai 403 Access Denied to application
code while still working in browsers, showing CDN/abuse controls can
discriminate by client behaviour.

**Safe operating assumption:** because `mRoster` is league-wide, polling every
five minutes is 12 requests/hour, 288/day — *not* 288 × team count. That is
orders of magnitude below the anecdotal ceiling. Implement cache/dedup,
exponential backoff, jitter, single-flight per league, no concurrent historical
backfill, hard pause on 403/429, and long-lived caching of completed scoring
periods. Build around "we only need a tiny fraction of that," not around
"60/minute is safe."

### 5 · Daily lineup locks and timestamps

- **Starting vs benched?** Yes — `lineupSlotId` (12 bench, 13 IR).
- **Locked right now?** Often — `lineupLocked` / `rosterLocked` / `tradeLocked`.
  Lock *state*, not an edit timestamp.
- **When did the manager set the lineup?** No reliable field found in `mRoster`.
  Nothing resembling `lineupChangedAt`. `acquisitionDate` is not that field.
  *(§0: `mTransactions2` `FUTURE_ROSTER` items are the source the memo was
  looking for.)*
- **When does the lock occur?** For daily formats, players generally lock at the
  scheduled start of their individual real-world game. Derivable from the
  pro-team schedule (`date`, epoch ms) — but that is the *expected lock time*,
  not the time a manager clicked.

### 6 · Recommended ingestion strategy

Model ESPN data as two separate concepts:

**Current roster state** — one `view=mTeam&view=mRoster` call per sync;
persist `league_id, team_id, player_id, lineup_slot_id, acquisition_type,
acquisition_date, injury_status, status, synced_at, raw_payload`.

**Daily historical lineup snapshot** — for every completed `scoringPeriodId`,
persist the nested `schedule[].home/away.rosterForCurrentScoringPeriod.entries[]`.
Key by `(league_id, season_id, scoring_period_id, team_id, player_id)`; store
slot, active/bench/IR, category contribution, `snapshot_fetched_at`. Once a
period is complete, treat it as immutable except via deliberate reconciliation.

**Transaction history** — separately ingest `view=mTransactions2&scoringPeriodId={DAY}`
for a proper ownership event stream, rather than inferring acquisition history
from current state.

### 7 · Confidence matrix (memo's own ratings)

| Question | Answer | Confidence |
|---|---|---|
| Primary roster view | `mRoster` | High |
| One request for whole league | Yes | High |
| Team filtering exists | `rosterForTeamId` observed | Medium |
| `scoringPeriodId` = one NBA fantasy day | Yes | High |
| Bare `mRoster` reconstructs historical membership | Unknown / insufficient evidence | **Low** |
| Historical lineup in matchup/scoreboard payloads | Yes | High |
| Starter/bench/IR available | `lineupSlotId` | High |
| Acquisition timestamp | `acquisitionDate`, epoch ms | High |
| Current lock state | `lineupLocked` / `rosterLocked` | Medium-High |
| Exact timestamp manager changed lineup | No reliable field found | High *(§0 contradicts)* |
| ESPN publishes a rate quota | No | High |
| ~60 req/min observed without problems | Anecdotal | Medium |
