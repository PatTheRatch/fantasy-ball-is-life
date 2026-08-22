# H-01 · Unknown is not a tie

**Status:** NEXT (assigned) · **Depends on:** nothing · **PR into:** `v2`
**Branch:** `fix/h-01-unknown-is-not-a-tie`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md) §Slice 1 hardening
**Source:** [`research/REDTEAM_TRIAGE.md`](../v2/research/REDTEAM_TRIAGE.md) §1
**Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

---

## The bug

`domain/categories.py:82-84` — `compare()` returns `(TIE, TIE)` whenever either
side's value is `None` or NaN. `services/matchups.py:345-356` persists that as
`result='tie'`. `services/standings_read.py:95-97` counts every stored `'tie'`
into `category_ties`, and `domain/standings.py:95,100` folds it into each team's
record.

So **a missing stat currently produces a real category tie.** A row recording
"we never received FG% for this matchup" is byte-identical to one recording
"both teams shot exactly .478", and both move the standings.

The existing code is a deliberate, documented decision — the `_comparable`
docstring explains it was chosen to avoid V1's null-vs-zero conflation. It
succeeds at that and then commits a subtler version of the same error. Charter
§10 is explicit:

> The absence of a result must never be indistinguishable from a result, and a
> computation that ran on partial inputs must say which inputs were missing.

A tie is a result. This is a live correctness bug in shipped code.

## The shape of the fix

Unknown becomes a real outcome in the domain vocabulary, `NULL` in storage, and
an excluded-and-counted quantity in the fold.

**There is no migration.** `matchup_category_results.result` is *already*
nullable (`0008_matchups.py`) — the schema anticipated unknown; only the domain
collapsed it. If you find yourself writing a migration, stop and re-read this
line.

**Do not add a `partial` member to any enum.** `Matchup.status` reuses
`enums.period_status` (`scheduled | in_progress | final`), so adding `partial`
would pollute `MatchupPeriod`'s enum with a value meaningless for periods. It is
also unnecessary: the per-category `NULL` rows say *exactly* which inputs were
missing, which is what the charter asks for and is strictly better than a coarse
matchup-level flag. Completeness is derived by counting, never stored.

## Files

**`backend/domain/categories.py`**
- Add `UNKNOWN = "U"` to `Result`.
- `compare()` returns `(Result.UNKNOWN, Result.UNKNOWN)` when either side is
  non-comparable. Keep `_comparable` as-is — it is correct; only the outcome it
  maps to is wrong. Update its docstring: the point is no longer "missing ties",
  it is "missing is its own outcome."
- `tally()` returns **`(home_wins, away_wins, ties, unknowns)`** — a 4-tuple. The
  current `else: ties += 1` branch at line 151 is the bug in miniature; unknown
  must not fall into it. This is a breaking signature change; fix every caller.

**`backend/services/matchups.py`**
- `_RESULT_MAP` (line 47) maps `Result.UNKNOWN → None`. Keep it a total mapping
  over `Result` so a future member cannot be silently dropped.
- `_normalize` unpacks the 4-tuple from `tally`. **`computed_result` must not be
  decided by unknown categories**: compute `home`/`away`/`tie` from the known
  wins only, exactly as now.
- Leave `status="final"` alone. Matchup-level completeness is derived, per the
  rule above.

**`backend/domain/standings.py`**
- `MatchupResult` gains `category_unknowns: int = 0`.
- `StandingRow` gains `unknown: int` — a team's season count of category
  outcomes that could not be determined.
- `standings_through`: accumulate unknowns separately. **`total` must stay
  `w + losses + t`** (line 104) so `win_pct` is a percentage of *decided*
  categories. An unknown category must never dilute or inflate a win
  percentage.

**`backend/services/standings_read.py`**
- The fold at lines 95-97 counts `r.result == 'home'|'away'|'tie'`; add a
  fourth count for `r.result is None` and pass it through as
  `category_unknowns`.
- `StandingTeamRow` gains `unknown`.
- `StandingsResult` gains `complete: bool` and `unknown_category_count: int`
  (season totals across the folded periods). This is the honesty surface — a
  fix that silently drops unknown categories would violate the same
  non-negotiable it is meant to satisfy.

**`backend/api/routers/standings.py`**
- `StandingRowOut` gains `unknown: int`; `StandingsResponse` gains
  `complete: bool` and `unknown_category_count: int`. Map them in the existing
  comprehension.

**`frontend/openapi.json` + `frontend/src/shared/api/openapi.d.ts`**
- Regenerate both — `python scripts/export-openapi.py` and
  `npm run generate:client` in `frontend/`. **CI drift-gates both files** and
  will fail if the response model changed without them. This is the one place
  this ticket touches the frontend, and it is mechanical.

## Tests

The invariant is *"unknown is never a result"*, and it needs testing at each
layer it passes through, because it was lost in transit before.

**`tests/domain/test_categories.py`**
1. `compare()` with `None` on either side returns `UNKNOWN`, **not** `TIE`.
2. `compare()` with NaN on either side returns `UNKNOWN`.
3. A genuine equal-value comparison still returns `TIE` — the two must stay
   distinguishable, which is the entire point.
4. `tally()` counts unknowns separately and does not inflate `ties`.

**`tests/domain/test_standings.py`**
5. A matchup with unknown categories folds W/L/T from the decided ones only.
6. `win_pct` is computed over decided categories — a team at 4-3 with 2 unknown
   has the same `win_pct` as one at 4-3 with 0 unknown, and **not** the value it
   would have at 4-3-2.

**`tests/services/test_matchups_sync.py`** (hermetic)
7. A scoreboard DTO missing a scoring category persists that category's row with
   `result=None`, and the row still exists — absent, not dropped.
8. `computed_result` is decided by the known categories only.

**`tests/services/test_standings_read.py`**
9. A stored `NULL` category result does not increment any team's tie count.
10. `complete=False` and a correct `unknown_category_count` when any folded
    matchup has an unknown category; `complete=True` for a fully known season.

**`tests/api/test_standings_route.py`**
11. The envelope carries the new fields.

Cite the origin on the ported invariant, per `CONTRIBUTING.md`:
`# charter §10: absence of a result must be distinguishable from a result`

## Acceptance criteria

- [ ] A missing stat produces `result=NULL`, never `'tie'`.
- [ ] Standings W/L/T and `win_pct` are computed over decided categories only.
- [ ] The API envelope reports whether the table was folded from complete data.
- [ ] No migration in the diff. No new enum members.
- [ ] `pytest && ruff check backend tests && mypy` clean; `frontend/` typecheck,
      lint, test, build clean; both CI drift gates pass with regenerated files.

## Data model / API impact

No schema change. The API response model gains three fields (additive, so no
frontend breakage), which forces an openapi snapshot + client regeneration.

## Rollback

Pure code change plus regenerated artifacts; reverting the squash commit is
clean. Note that reverting restores the bug — if a rollback is ever needed,
the reason should be recorded.

## Out of scope

- **Rendering unknown in the UI.** S1-11c already touches the league page and
  will surface it; this ticket only makes the data honest and available. Say in
  the PR description that the field is unrendered so it is not forgotten.
- **`partial` as a run status** — that is H-03.
- **Anything that writes `matchup_periods.status`** — that is H-07.
- The identity ladder's birthdate conflict — that is H-02.

## Notes for review

Claude will check: that `TIE` and `UNKNOWN` are genuinely distinguishable end to
end, that `win_pct` denominators exclude unknowns, that `_RESULT_MAP` stays
total, that no migration appears, and that the tests would actually fail against
the current `main`-branch behaviour — a test that passes before the fix is not a
test of this bug.
