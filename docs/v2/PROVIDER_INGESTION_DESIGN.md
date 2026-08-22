# V2 Provider Ingestion Design

**Work-plan item 3** from [`FCP_V2_Product_Architecture_Charter.md`](../FCP_V2_Product_Architecture_Charter.md) §11: define raw snapshot storage, ingestion runs, ESPN adapter contracts, normalization outputs and replay behaviour.

**Status:** design. No code. Tables referenced here are defined in [`schema/04-provider-ingestion.md`](schema/04-provider-ingestion.md).

**Charter:** Decisions 5 (multi-provider), 14–15 (canonical NBA schedule, real matchup periods), 16 (raw retention), 17 (lineage), 18 (prefer unknown over confidently wrong), 19 (crosswalk), 28 (observability).

---

## Headline finding: the hardcoded calendar was never necessary

The schema phase flagged one blocking unknown — *can matchup periods be derived from ESPN, or must they be hand-maintained?* Charter Decision 15 and the non-negotiable *no hardcoded season calendars* both depend on the answer.

**They can be derived. ESPN has exposed the mapping the whole time.**

Verified against the installed library and the V1 source.

`espn_api/base_league.py:31` declares `_fetch_league(self, SettingsClass=BaseSettings)`, and **only football overrides it** (`football/league.py:39`). Basketball does not — so a basketball `League.settings` *is* a `BaseSettings`, which sets:

```python
# espn_api/base_settings.py:5
self.matchup_periods = data['scheduleSettings']['matchupPeriods']
```

Note the bracket access: **not** `.get()`. If ESPN omitted `matchupPeriods`, constructing a basketball `League` would raise `KeyError`. V1 constructs basketball leagues successfully in production against a real league — therefore **ESPN demonstrably returns this field for basketball**. That is production evidence, not inference from another sport.

Constructing a `BaseSettings` from a representative payload confirms the shape:

```
matchup_periods : {'1': [1, 2, 3, 4, 5, 6], '2': [7, 8, 9, 10, 11, 12, 13]}
type            : dict     key type: str
```

So it is `{matchup_period_id: [scoring_period_id, ...]}`, **keys are strings** (JSON object keys — cast on read).

And the other half already has real timestamps — from V1's own docstring at `data_feed.py:744`, `proGamesByScoringPeriod` *"does carry real game timestamps."*

Join the two and the calendar falls out:

```
settings.matchupPeriods       matchup_period → [scoring_period, …]
proGamesByScoringPeriod       scoring_period → [game{date: epoch_ms}, …]
                                     ⇓
              matchup_period → real start_date / end_date
```

**V1 never reads `settings.matchup_periods`.** I grepped the entire backend and frontend: zero references. The worker stores six fields off `settings` and drops this one. So the 22 hand-typed week ranges — duplicated in Python *and* TypeScript, keyed to one league's one season, and named on the original dossier's cut list — were avoidable from the start.

This also explains why V1's `_scoring_periods_for_week()` runs **backwards**: it starts from the hardcoded dates and searches the pro schedule for scoring periods that fall inside them, with a `pad=3` fudge because the inferred mapping is inexact. With `matchupPeriods` the mapping is exact and authoritative, and the pad disappears.

> **What remains open.** Existence and shape are settled by the argument above. Still to confirm against a live league: whether `matchupPeriods` covers playoff and championship periods as well as regular ones, how the All-Star break appears (its own period, or an extended one), and whether derived dates match the league's actual week boundaries. Those are content questions, not existence questions — they refine the mapping, they cannot invalidate the approach.

---

## Pipeline

Four stages, each durable, each independently replayable.

```
   ┌──────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────┐
   │  FETCH   │──▶│   PERSIST    │──▶│  NORMALIZE    │──▶│   RESOLVE    │
   │ provider │   │ raw_payloads │   │ canonical     │   │ identity     │
   │ HTTP     │   │ (evidence)   │   │ rows + lineage│   │ links/queue  │
   └──────────┘   └──────────────┘   └───────────────┘   └──────────────┘
        │                │                   │                   │
        └────────────────┴───────────────────┴───────────────────┘
                   all recorded under one ingestion_run
```

The stage boundary that matters is **persist before interpret**. Charter §6: *"Replay beats patching."* A normalization bug is fixed by shipping a new normalizer version and re-running it over stored payloads — no refetch, no dependence on the provider still serving the same data, and the old interpretation is superseded rather than erased.

V1 has no equivalent. A mapping bug there means refetching from ESPN and hoping upstream has not changed — which for completed weeks it may well have.

---

## Adapter contract

Provider objects never escape `providers/<name>/`. The protocol returns FCP DTOs.

```python
class FantasyProvider(Protocol):
    key: ProviderKey

    def verify(self, conn: Connection) -> ConnectionStatus: ...

    def fetch_league_season(self, conn, season: int) -> Fetched[LeagueSeasonDTO]: ...
    def fetch_teams(self, conn, season: int) -> Fetched[list[TeamDTO]]: ...
    def fetch_periods(self, conn, season: int) -> Fetched[list[MatchupPeriodDTO]]: ...
    def fetch_matchups(self, conn, period: int) -> Fetched[list[MatchupDTO]]: ...
    def fetch_rosters(self, conn, on_date: date) -> Fetched[list[RosterSlotDTO]]: ...
    def fetch_transactions(self, conn, w: PeriodWindow) -> Fetched[list[TransactionDTO]]: ...
    def fetch_player_pool(self, conn, season: int) -> Fetched[list[PlayerRefDTO]]: ...
```

`Fetched[T]` carries the normalized value **and** the raw payloads that produced it, so persistence and normalization stay coupled without the adapter knowing about the database:

```python
@dataclass(frozen=True)
class Fetched(Generic[T]):
    value: T
    payloads: list[RawPayload]     # endpoint, params, body, fetched_at
    observed_at: datetime
```

Three binding rules:

1. **Never subclass the provider library.** V1 has two classes subclassing `espn_api.basketball.League` and overriding its *private* loaders (`_fetch_players`, `_fetch_draft`, `_get_all_pro_schedule`). That is the charter §7 violation and a standing risk that a library patch release silently breaks analytics. `espn_api` may be used *inside* `providers/espn/client.py`, or dropped for direct HTTP; either way its objects stop at the package boundary.
2. **DTOs are FCP-shaped from the first line of the mapper.** No stage downstream handles a provider dict.
3. **Adapters do no I/O to our database.** They fetch and map. The service layer persists.

### DTO identity rule

DTOs carry **provider identifiers and raw names**, never FCP ids:

```python
@dataclass(frozen=True)
class RosterSlotDTO:
    provider_team_id: str
    provider_player_id: str | None
    raw_player_name: str
    raw_attributes: dict          # team, position, dob — matching evidence
    slot_code: str | None
    is_starting: bool | None
    injury_status: str | None
```

Resolution to `players.id` happens in the resolve stage, once, against the crosswalk. An adapter that tried to resolve identity itself would reintroduce exactly the per-call-site matching that V1 has four incompatible copies of.

---

## Ingestion runs and lineage

Every fetch happens inside a run. Every canonical row points back at it.

```
ingestion_runs(id, provider_id, connection_id, league_season_id, kind,
               normalizer_version, started_at, finished_at, status,
               error, stats, replayed_from_run_id)
```

`status` is `running | succeeded | partial | failed`. **`partial` is a first-class outcome** (charter Decision 28): a run that got matchups but not transactions says so, rather than succeeding quietly with half the data. V1's worker gets the isolation right — per-phase try/except returning `"ok"` or `"error: …"` — but the result is a dict returned over HTTP and then discarded. Here it is a row.

`stats` records rows read / written / superseded / queued, so a run that wrote nothing because nothing changed is distinguishable from a run that wrote nothing because it broke.

**Normalizer version is per run, not global.** Replaying week 7 under `v3` while week 8 was written under `v2` is normal and must stay explicable.

---

## Raw payload storage

```
raw_payloads(id, ingestion_run_id, provider_id, endpoint, request_params,
             fetched_at, http_status, content_hash, payload jsonb,
             storage_ref, byte_size)
```

**Decision: inline `jsonb`, not object storage, for V1.** Charter Decision 23 permits object storage and it will eventually be right, but inline keeps the payload write transactional with the run that produced it — which is the property that makes replay trustworthy. `storage_ref` is nullable from day one so the move needs no schema change.

Sizing check against V1's measurements: an `espn-api` `League()` construction pulls ~2.4 MB across four requests, of which the pro schedule is ~740 KB and the player map another large slice. At one league syncing every 15 minutes that is unacceptable to store verbatim — so:

- **Hash first, store on change.** `content_hash` is computed before insert; an unchanged payload records the run touched it and stores no second copy. Pro schedule and player map change rarely, so they collapse to a handful of rows per season.
- **Fetch narrowly.** V1 already proved the win here: `ScoreboardLeague` skips three of the four calls for the scoreboard path, saving ~740 KB. Adapters expose narrow fetches rather than one construct-everything call.
- **Final periods are never refetched**, so their payloads are written once.

---

## Normalization and write semantics

Normalization is a pure function per entity:

```python
def normalize_matchups(payloads: list[RawPayload], ctx: NormalizeContext)
        -> list[MatchupRow]
```

Pure means testable without a network or a database, and replayable over stored payloads by construction.

Write rules, per [`schema/README.md`](schema/README.md):

- **Never update a canonical fact.** Write the corrected row, then set `superseded_by_id` / `superseded_at` on the old one. Reads filter `superseded_at is null`.
- **Never delete.** The fact that we once believed something is itself history.
- **Idempotent by natural key.** Re-running a run over unchanged payloads produces zero writes, not duplicates.
- **Nulls stay null.** A missing stat is `null`, never `0`. V1's season-stats bug — every category reading zero — was exactly this conflation, and it shipped because zero looks like data.

---

## Identity resolution

One ladder, defined once in [`schema/04`](schema/04-provider-ingestion.md), used by every ingest. Restated here because it is the behavioural heart of the pipeline:

| Order | Method | Confidence | Action |
|---|---|---|---|
| 1 | existing link for this provider entity id | 1.000 | auto-link |
| 2 | NBA person id already crosswalked | 0.990 | auto-link |
| 3 | normalised name **and** birthdate | 0.950 | auto-link |
| 4 | normalised name, unique in pool | 0.850 | auto-link, flag for audit |
| 5 | fuzzy, above threshold, unambiguous | 0.700–0.849 | **queue** |
| 6 | anything else | — | **queue** |

What changes versus V1:

- **One `normalize_name`**, in the domain layer. V1 has two — one at module scope stripping accents and punctuation, one shadowed inside `add_bbm_projections` stripping *all* non-alpha — which disagree on hyphenated and suffixed names, so a player can resolve in one code path and vanish in another.
- **One threshold set**, as data. V1 has four literals at four call sites (80, 75, 85, 90).
- **A failed match is a row, not a silence.** V1 drops the player. The numbers still look plausible, so nobody notices.

Resolution runs *after* normalization and never blocks it. Unresolved rows are written with their provider identity recorded and land in `identity_review_queue`; the count surfaces on the status page.

---

## Sync scheduling

Per-league job units on the Postgres queue, not one loop over every league.

| Job | Cadence | Skips when |
|---|---|---|
| `sync_league_settings` | daily + on create | settings hash unchanged |
| `sync_periods` | daily | period set unchanged |
| `sync_current_period` | 15 min | period `final` |
| `sync_rosters` | daily | — (see below) |
| `sync_transactions` | 15 min | period `final` |
| `finalize_period` | on `end_date` + grace | already `final` |
| `resolve_identities` | after any ingest | queue empty |

**Finality is what makes this cheap.** Once `matchup_periods.status = 'final'`, that period is never refetched. A mid-season league syncs one period per cycle instead of twenty-two. V1 has no such concept, which is why its refresh is a synchronous 900-second HTTP request that re-derives everything every time and does not survive double-digit leagues.

**Roster snapshots are the exception and must run daily from day one.** ESPN does not serve historical daily rosters, so a day not captured is gone permanently. Charter Decision 10 wants lineup state "when obtainable"; this is the only obtainable window. It also gates manager-performance analytics (charter §3), which needs to know what was available at decision time.

> **The premise in that paragraph is under challenge and not yet re-verified.** Two candidate recovery paths have surfaced — `rosterForCurrentScoringPeriod` in the historical scoreboard payload, and `mTransactions2` `FUTURE_ROSTER` lineup-slot movements. See [`research/ESPN_ROSTER_API.md`](research/ESPN_ROSTER_API.md) §0 and backlog open question #6. **The daily-capture requirement stands until a live check says otherwise**: if we relax it and the premise was right, the lost days cannot be recovered. What the check changes is *sequencing urgency*, not the design.

---

## Replay

```
1. ship normalizer v(n+1)
2. create ingestion_run(kind='replay', replayed_from_run_id=<original>,
                        normalizer_version='v(n+1)')
3. re-run normalize() over the original run's raw_payloads
4. write corrected rows; supersede the rows the original run produced
5. resolve identities for anything newly matchable
```

No provider traffic. Fully auditable — the old interpretation, the new one, and the run that produced each all remain queryable.

This is what makes "we got week 7 wrong" a fifteen-minute fix rather than an archaeology project, and it is why persist-before-interpret is worth the storage.

---

## Failure handling and observability

Charter Decision 28. Every failure mode V1 produced was silent.

| Failure | V2 behaviour |
|---|---|
| Provider unreachable / timeout | Typed error, run `failed`, `last_error` on the connection, retry with backoff |
| Credentials expired | Connection `status='invalid'` + `last_error` — a fact the owner can be shown, not a stack trace |
| One entity kind fails | Run `partial`, other kinds still commit |
| Payload unparseable | Payload still stored; normalization fails loudly; replay after a fix |
| Player unresolvable | Queued and counted; never dropped |
| Nothing changed | Run `succeeded`, `stats.written = 0` — distinct from a broken run |

**Port V1's ESPN gateway largely intact.** Explicit connect/read timeouts, typed `ESPNTimeoutError` / `ESPNUnavailableError`, 504/502/500 mapping, and — the careful part — a monkeypatch scoped by rebinding `requests` inside espn-api's *own module namespace* rather than mutating the shared module, so unrelated callers keep their own error handling. It is genuinely good work and it exists because the library issues `requests.get()` with no timeout at all.

Status page surfaces, per league: last successful sync per kind, periods pending finalization, open identity-queue depth, connection status, failed runs in the last 24h.

---

## ESPN specifics

Carried forward from V1's live investigation so it is not rediscovered.

| Fact | Consequence |
|---|---|
| `League()` fires 4 requests, ~2.4 MB | Narrow fetches per adapter method; never construct-everything |
| `recent_activity()` returns 404 | Use the `mTransactions2` view — V1's working adapter |
| `scoringPeriodId` does not align to UTC calendar days | Never infer dates from ids; use `proGamesByScoringPeriod` timestamps |
| Days with no NBA games consume no scoring-period id | Period date ranges come from game timestamps, not id arithmetic |
| Box scores carry ESPN's own `winner` | Store as `provider_result` alongside `computed_result` — V1 shipped a playoff recap calling a decided 4–4 matchup a tie because it never consulted this |
| `box_scores(matchup_period=…)` honours completed and playoff periods | Backfill of past periods works |
| Auth is cookie-based (`SWID` + `espn_s2`) | Expiry is routine — surface it, do not just fail |
| No request timeouts in the library | Gateway patch is mandatory before any call |

---

## Testing

| Layer | Approach |
|---|---|
| Adapters | Golden-file tests over sanitised `raw_payloads`. The pipeline generates its own fixtures — V1 needed a bespoke capture script for one. |
| Normalizers | Pure functions; table-driven tests including malformed and partial payloads |
| Resolution ladder | Fixture pool with known collisions — hyphenated names, suffixes, two players sharing a name, accented spellings |
| Idempotency | Run twice over identical payloads, assert zero second-pass writes |
| Replay | Normalize under v1, then v2, assert supersession and that both interpretations remain queryable |
| Finality | Assert a `final` period is never refetched |
| Live smoke | One real ESPN league, run manually, asserting `matchupPeriods` is populated and derived dates match reality |

The **first** test to write is the live smoke check on `matchupPeriods` — everything above depends on it.

---

## Open questions

1. **Live confirmation of `matchupPeriods`** (blocking, above). Basketball leagues specifically; key types; how the All-Star break and playoff periods appear. First task of implementation.
2. **Roster fetch cost.** Daily snapshots for N teams — is that one request per team per day, or one league-wide call? Determines whether daily capture is cheap or needs batching.
3. **Grace period before finalizing.** ESPN occasionally adjusts a completed week's stats. Recommend 48h after `end_date`, with a manual re-open path — a period wrongly frozen is worse than one frozen late.
4. **Kaggle NBA backfill as an ingestion run.** Recommend running it as `provider_key='kaggle'` rather than a bulk import: it exercises the pipeline end to end on a real dataset with genuine name ambiguity, and populates lineage honestly. Also the first real load for the identity review queue.
5. **Payload retention.** Unbounded for V1 (charter §6: data is king, storage is cheap). Revisit at ~10 GB.

---

*Design phase. Verified against library source and V1 code at `1a00272`; live ESPN confirmation still outstanding.*
