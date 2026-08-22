# H-03 · Runs must always reach a terminal state

**Status:** NEXT (assigned) · **Depends on:** nothing (H-01 already merged) · **PR into:** `v2`
**Branch:** `fix/h-03-run-lifecycle-scope`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md) §Slice 1 hardening
**Source:** [`research/REDTEAM_TRIAGE.md`](../v2/research/REDTEAM_TRIAGE.md) §3
**Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

---

## The bug

`backend/services/matchups.py:178-213`. `sync_league_final_periods` opens a run
with `self.ingestion.start_run(...)` (line 178) and only reaches
`self.ingestion.finish_run(run, "succeeded", ...)` (line 212) if every statement
between them succeeds. There is no `try`/`except`/`finally`.

Every failure path in that span leaves the run without a terminal status:

- an adapter timeout inside `adapter.fetch_scoreboard(...)` (line 191);
- an unresolved team or missing provider id — `raise MatchupSyncError(...)` at
  `matchups.py:227, 230, 236, 239` inside `_persist_matchup`;
- any database constraint failure during `add` / `flush` (e.g. the
  `uq_matchups_live_slot` partial unique index in the supersession block,
  lines 259-274).

`backend/services/ingestion.py:116-131` — `finish_run` already accepts
`succeeded`, `partial` and `failed`, and the `run_status` enum
(`backend/models/enums.py:39-41`) already carries all four members. Nothing
structurally forces a caller down the `failed`/`partial` path, so on any
exception the run is abandoned mid-lifecycle.

**What actually happens is worse than "stuck `running` forever."** The service
never commits; the caller owns the transaction and rolls back on exception
(`backend/api/deps.py:59-61` `get_db`; the tests commit explicitly). So today an
exception discards the whole transaction — the run row included — and the run is
not *stuck* running, it is *gone*: no `succeeded`, no `failed`, no row at all.
Either way the outcome is the same violation:

> `# charter D28: job outcomes are queryable data, not log lines`

A job that failed must leave a queryable, durable `failed` row with the reason —
not a stale `running` row, and not nothing.

There is a second, quieter D28 gap on the *success* path. A payload missing some
of the season's scoring categories still finishes `succeeded`. H-01 made the
per-category data honest (a missing category is stored `result = NULL`, an
`UNKNOWN` outcome, never a `tie`), but the run that produced it still reports
unqualified success. D28 wants "partial" to be a first-class run outcome — a run
that got the matchups but not every category should say so.

### Scope reality check (differs from the one-liner)

The backlog says "wrap run-owning services." **There is exactly one run-owning
service today.** `grep` for `start_run` across `backend/` and `tests/` returns
only `MatchupSyncService.sync_league_final_periods` (plus the definition and its
own unit tests). `backend/worker/` has no source — only stale `.pyc` files
(`refresh.cpython-*.pyc`) with no `.py`; there is no scheduler, celery, or cron
anywhere (consistent with the triage's §"Re-severed" notes). So this bite covers
one caller. The value of the fix is that the **next** run owner inherits the
guarantee for free by using the context manager instead of raw
`start_run`/`finish_run` — the same "structure prevents it, discipline does not"
logic behind S1-05's scopes. This is called out again under *Notes for review*.

## The rule

A run that has been opened must reach exactly one terminal status —
`succeeded | partial | failed` — and that status must be **durable**
(committed), independent of whether the work it recorded was committed or rolled
back. The original exception must still reach the caller unchanged.

`partial` means the run completed but the data it produced is known-incomplete.
For this bite, "incomplete" has one precise meaning, inherited from H-01: **at
least one persisted `matchup_category_results.result` is `NULL`** — i.e. a
scoring category whose value was `None`/NaN on a side and therefore resolved to
`Result.UNKNOWN` (`_RESULT_MAP[Result.UNKNOWN] is None`, `matchups.py:50-55`).
A bye produces no category rows at all (`_normalize` returns `matchup, []`,
`matchups.py:309`) and so is **never** partial. Partial is derived by counting
`NULL` results, never stored on the matchup — same discipline H-01 used for
completeness.

## The fix

### 1. The run-lifecycle context manager

Add a context manager to `IngestionService` in `backend/services/ingestion.py`:

```python
from collections.abc import Iterator
from contextlib import contextmanager

RUN_RUNNING = "running"   # add alongside the existing RUN_* constants

    @contextmanager
    def run_scope(
        self,
        provider_key: str,
        kind: str,
        *,
        connection_id: uuid.UUID | None = None,
        league_season_id: uuid.UUID | None = None,
        replayed_from_run_id: uuid.UUID | None = None,
    ) -> Iterator[IngestionRun]:
        """Open a run and guarantee it reaches a terminal status on exit.

        On entry the run is opened and committed as ``running`` so it is durable
        immediately. On normal exit the run is committed with whatever terminal
        status the body set via ``finish_run`` (defaulting to ``succeeded`` if
        the body set none). On an exception the work is rolled back, the run is
        stamped ``failed`` with the error and committed, and the original
        exception is re-raised.
        """
        run = self.start_run(
            provider_key,
            kind,
            connection_id=connection_id,
            league_season_id=league_season_id,
            replayed_from_run_id=replayed_from_run_id,
        )
        self.runs.commit()          # durable 'running' — survives a later rollback
        try:
            yield run
        except Exception as exc:
            self.runs.rollback()    # discard partial work AND clear an aborted txn
            run = self.runs.get(run.id)   # committed as running → survives rollback
            self.finish_run(run, RUN_FAILED, error=_format_error(exc))
            self.runs.commit()
            raise
        if run.status == RUN_RUNNING:       # body never called finish_run
            self.finish_run(run, RUN_SUCCEEDED)
        self.runs.commit()          # commits the work + the terminal status atomically
```

**Contract, spelled out:**

- **Entry.** `start_run` opens the run; `self.runs.commit()` makes it durable as
  `running` *before* any work runs. This commit is load-bearing: it is what lets
  the run row survive the `rollback()` on the failure path. It is also what makes
  an in-flight run queryable while it runs.
- **Normal exit.** The body is expected to call `finish_run(run, "succeeded" |
  "partial", stats=...)` before the `with` block closes. The context manager
  then commits — so the work rows (matchups, category results, raw payloads) and
  the terminal status commit **together**, atomically. You never get a
  `succeeded` run with no data, or committed data under a `running` run. If the
  body set no terminal status, the manager defaults to `succeeded` (the backstop
  that makes "always terminal" structural rather than conventional).
- **Exception exit.** `self.runs.rollback()` first — this both discards any
  half-written matchups/payloads and clears an aborted transaction (a DB
  constraint failure leaves the session in a state where the *next* statement
  raises `PendingRollbackError`; rolling back is what makes the `failed` write
  possible). The run object survives because it was committed as `running` at
  entry; re-`get` it, stamp `failed` with the formatted error, commit that
  single row, then `raise` to re-propagate the **original** exception unchanged.
- **Error capture.** `_format_error(exc)` is a small module helper returning a
  bounded string (`f"{type(exc).__name__}: {exc}"`, truncated to a sane length —
  the `ingestion_runs.error` column is `Text`, but keep it a message, not a full
  traceback). The exception is re-raised with a bare `raise`, so the caller sees
  the same exception type and `__traceback__`.
- **Hard-kill boundary (stated, not fixed).** `except Exception` deliberately
  does not catch `KeyboardInterrupt`/`SystemExit` or a process kill. A process
  that dies mid-run cannot stamp itself; that leaves a durable `running` row,
  which is a reaper's job, not a context manager's. Call this out in the PR;
  see *Out of scope*.

### 2. Repository support for the commit boundary

`run_scope` must control commit/rollback without reaching into a raw `Session`
(the service holds repos, not a session). Mirror the existing
`MatchupRepository.flush()` seam (`repos/matchups.py:158-165`): add to
`IngestionRunRepository` in `backend/repos/ingestion.py`:

```python
    def commit(self) -> None:
        self.session.commit()

    def rollback(self) -> None:
        self.session.rollback()
```

Because every repo in the sync (`IngestionRunRepository`, `RawPayloadRepository`,
`MatchupRepository`, `LeagueSeasonRepository`) is bound to the **same** `Session`,
one `runs.commit()` commits the run *and* the matchup/payload work. This is why
the single-session design works and no session-factory injection is needed.

### 3. Rewire `MatchupSyncService.sync_league_final_periods`

Replace the bare `start_run(...)` / `finish_run(..., "succeeded")` bracket
(`matchups.py:178-213`) with the context manager, and decide `succeeded` vs
`partial` from the unknown-category count:

```python
    season = self.league_seasons.get(league_season_id)
    if season is None:
        raise MatchupSyncError(f"unknown league_season: {league_season_id!r}")
        # deliberately BEFORE run_scope: a missing season is a precondition
        # failure, not a run that started and failed. No run is opened.

    with self.ingestion.run_scope(
        season.provider_key, kind="matchups", league_season_id=league_season_id
    ) as run:
        ... existing load + loop, now accumulating unknowns ...
        summary = SyncSummary(periods, matchups, created, superseded, unchanged, unknowns)
        status = RUN_PARTIAL if summary.unknown_categories else RUN_SUCCEEDED
        self.ingestion.finish_run(run, status, stats=asdict(summary))
    return summary
```

- `_persist_matchup` returns `(outcome, unknown_count)` where `unknown_count =
  sum(1 for r in results if r.result is None)` from the freshly normalized
  `results` (available on every path — created, superseded, *and* unchanged, so
  an identical resync of already-partial data is still reported partial). The
  loop accumulates `unknowns`.
- `SyncSummary` (frozen dataclass, `matchups.py:58-66`) gains a final field
  `unknown_categories: int`. It is constructed in exactly one place, so the new
  positional argument is a one-line change; it flows into `run.stats` via
  `asdict(summary)` (JSONB, additive — no migration).
- Import `RUN_PARTIAL` / `RUN_SUCCEEDED` from `backend.services.ingestion`
  (already defined there, `ingestion.py:32-34`).
- Leave `status="final"` on the matchup rows (`matchups.py:301, 327`) alone —
  matchup-level completeness is H-07's problem, not this bite's (see H-01's same
  boundary).

## Files

- `backend/services/ingestion.py` — `RUN_RUNNING` constant; `_format_error`
  helper; `run_scope` context manager; `contextlib.contextmanager` /
  `collections.abc.Iterator` imports.
- `backend/repos/ingestion.py` — `IngestionRunRepository.commit()` and
  `.rollback()`.
- `backend/services/matchups.py` — use `run_scope`; thread the unknown-category
  count; `SyncSummary.unknown_categories`; `RUN_PARTIAL`/`RUN_SUCCEEDED` status
  selection.
- `tests/services/test_ingestion.py` — `run_scope` contract tests.
- `tests/services/test_matchups_sync.py` — partial/succeeded stamping; update the
  `_service` helper so the mocked ingestion exposes a working `run_scope`.
- `tests/services/test_matchups_sync_postgres.py` — end-to-end terminal-state
  tests against a real DB.

Nothing else. No migration, no schema change, no model change.

## Tests

The invariant is *"an opened run always reaches a durable terminal status, and
the original exception still reaches the caller."* It is tested at the context
manager (hermetic), at the sync service (hermetic), and end-to-end against
Postgres, because the failure path was never exercised before.

**`tests/services/test_ingestion.py` — the context-manager contract (hermetic).**
Drive a real `IngestionService` with fakes: a `ProviderRepository` returning a
provider, a recording `IngestionRunRepository` fake that stores runs in a dict,
exposes `get`/`add`, and records an ordered log of `commit`/`rollback` calls, and
a stub `RawPayloadRepository`.

1. `run_scope` normal exit, body calls nothing → run ends `succeeded`,
   `finished_at` set, a commit happened. (backstop default)
2. `run_scope` normal exit, body calls `finish_run(run, "partial", ...)` → status
   stays `partial`; the manager does not overwrite it.
3. **`run_scope` body raises → run ends `failed`, `run.error` contains the
   exception message, and the *same* exception propagates (`pytest.raises`).**
   This is the test that fails against the current code (which has no
   `try`/`except`/`finally`).
4. `run_scope` commits the run as `running` *before* yielding: assert the run is
   `running` and a commit was already recorded at the point the body runs.
   Catches an implementation that only commits at the end — where a mid-run crash
   would leave nothing durable.
5. On the exception path, `rollback` is recorded **before** the `failed` commit
   (assert against the ordered call log). Catches an implementation that tries to
   write `failed` into an already-aborted transaction (which would itself raise
   `PendingRollbackError` and mask the real error).

**`tests/services/test_matchups_sync.py` — partial/succeeded stamping (hermetic).**
Update `_service` so the fake `ingestion` provides a real context manager for
`run_scope` (e.g. an `@contextmanager` that yields a fake run) plus `finish_run`
and `record_payload` spies; existing tests keep asserting on `finish_run`.

6. **A scoreboard missing a scoring category → `finish_run` is called with
   `"partial"`.** The core new behaviour; catches an implementation that always
   stamps `succeeded`. (Reuse the H-01 shape: home missing `REB`.)
7. A complete scoreboard (all categories on both sides) → `finish_run` called
   with `"succeeded"`. Regression guard against over-eager partial stamping.
8. A bye-only sync (away is `None`, zero category rows) → `"succeeded"`, not
   `"partial"`. Catches treating "no category rows" as "missing categories."
9. Update `test_normalizes_matchup_and_category_results` (line 148): keep
   `finish_run.assert_called_once()` and additionally assert the status argument
   is `"succeeded"`.

**`tests/services/test_matchups_sync_postgres.py` — end-to-end (real DB).**
Reuse the `_seed` / `_service` helpers already in the file.

10. **A failing sync leaves a durable `failed` run and no orphan rows.** Point
    the sync at a `_FakeAdapter` whose `fetch_scoreboard` raises (an adapter
    timeout — the triage's example; an unresolved team is the same path). Expect
    `MatchupSyncError`/the raised error to propagate. Then, in a fresh query:
    exactly one `ingestion_runs` row, `status == "failed"`, `finished_at` not
    null, `error` populated; and zero `matchups` / zero `raw_payloads` for that
    run (the work rolled back, the run did not). This is the headline test and it
    fails against current `v2` (no run row survives, or it is `running`).
11. **A partial sync marks the run `partial` without losing the result.** Seed a
    scoreboard that omits one of the season's scoring categories; the sync
    succeeds. Assert `ingestion_runs.status == "partial"` and that the matchup +
    its category rows are still persisted (the missing category stored
    `result IS NULL`, the others intact). Proves partial qualifies success, it
    does not discard it.
12. **A clean sync commits `succeeded` durably.** After a successful sync,
    without the test issuing its own `commit`, a run row exists with
    `status == "succeeded"`. Proves `run_scope` owns its commit. (May be folded
    into the existing success-path assertions.)

Cite the origin on the ported guarantee, per `CONTRIBUTING.md`:
`# charter D28: job outcomes are queryable data, not log lines`

## Acceptance criteria

- [ ] Any exception after a run is opened leaves a durable `failed`
      `ingestion_runs` row with the reason, and the original exception reaches
      the caller unchanged.
- [ ] A successful run is committed `succeeded`; a run whose payload was missing
      scoring categories is committed `partial`; a bye is not partial.
- [ ] The terminal status is committed independently of whether the work
      committed — a rolled-back sync still leaves a `failed` run, and a
      `succeeded`/`partial` run's data and status commit atomically.
- [ ] `run_scope` is the single seam; `MatchupSyncService` no longer calls
      `start_run`/`finish_run` directly on the happy path.
- [ ] No migration, no schema change, no new enum member (`run_status` already
      has all four values).
- [ ] `pytest && ruff check backend tests && mypy` clean;
      `tests/test_architecture.py` passes.

## Data model / API impact

**None to the schema.** No migration: `run_status` already has `running`,
`succeeded`, `partial`, `failed` (`enums.py:39-41`;
`schema/04-provider-ingestion.md:81`), and `ingestion_runs.status`/`error`
already exist. `SyncSummary.unknown_categories` adds one key to the
`ingestion_runs.stats` JSONB blob — additive, no DDL. No HTTP API surface
changes (no route reads runs, and the sync is not wired to a route), so no
openapi regeneration.

## Rollback

Pure code change plus tests; reverting the squash commit is clean. Reverting
restores the bug (opened runs can be abandoned on failure and partial payloads
report unqualified success) — if a rollback is ever needed, record why.

## Out of scope

- **An orphan-run reaper.** A process killed mid-run (SIGKILL, OOM) cannot stamp
  itself and leaves a durable `running` row. Sweeping stale `running` runs to
  `failed` after a timeout is a separate concern that needs a clock and a policy;
  not this bite. Say so in the PR.
- **`matchup.status = "final"` completeness.** Matchups are still hardcoded
  `final` regardless of category coverage (triage #22). That is matchup-level,
  not run-level, and belongs to **H-07** (finality needs a producer). H-03 only
  makes the *run* say `partial`.
- **`matchup_periods.status = "final"`** — nobody writes it; that is **H-07**.
- **Retries, backoff, scheduling, per-league serialisation** (advisory locks /
  `FOR UPDATE`) — **H-08**, and unreachable today with no scheduler.
- **Replay's `NORMALIZER_VERSION` as an argument** (triage §"Re-severed" #3) —
  build it when replay is built.
- **Touching the `run_status` enum, the `finish_run` signature, or the confidence
  / resolution logic.** No enum member is added or removed.
- **Wiring the sync to a route or worker.** No live caller exists; this bite
  hardens the service so the first real caller inherits the guarantee.

## Notes for review

Claude will check:

- That `run_scope` guarantees a terminal status on **both** exits — normal (with
  the `succeeded` backstop when the body sets none) and exceptional — and that
  test 3 genuinely fails against current `v2` (a test that passes before the fix
  is not a test of this bug).
- That the exception is re-raised **unchanged** — same type, original traceback —
  so the caller's error handling is unaffected.
- That the run is committed `running` at entry and therefore survives the
  rollback on failure (test 4), and that `rollback` precedes the `failed` commit
  so an aborted transaction cannot mask the real error (test 5).
- That `partial` is derived by counting `NULL` category results and that a bye
  (zero category rows) is never partial (test 8) — the same absent-vs-empty
  distinction H-01 turned on.
- That the terminal status is durable independently of the work transaction
  (tests 10-12), which is the whole of D28: a failed job is a queryable row, not
  a rolled-away nothing.
- That this is a single reusable seam: the next run owner should use `run_scope`,
  not raw `start_run`/`finish_run`. There is only one owner today, so the payoff
  is structural, not immediate — flag any future `start_run` call that bypasses
  the manager.
- That no migration, no enum change, and no `finish_run` signature change appear
  in the diff.
