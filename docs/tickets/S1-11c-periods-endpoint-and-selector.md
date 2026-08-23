# S1-11c · Periods endpoint + selector

**Status:** NEXT (assigned) · **Depends on:** S1-11b (merged, `10f1a90`), H-01, H-04a/b
**Branch:** `feat/s1-11c-periods-selector` · **PR into:** `v2`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md)
**Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

---

## This closes Slice 1

Charter §11.6 asked for a thin vertical slice — *user → manager → league →
season → ESPN sync → canonical teams/players/matchup periods → one shared
league page* — to **prove the architecture before rebuilding every feature**.
Everything in that chain is built except the ability to look at the league at a
point in time, which is what makes it a *history* product rather than a
current-state dashboard.

When this merges, work-plan item 6 is done and Slice 2 can be cut.

It is also the first new read path written against the tenancy foundation
H-04a/b just landed. If the scoped repository or the policy matrix makes this
awkward, that is a finding worth reporting, not working around.

## Two halves, one bite

Backend endpoint, then the frontend that consumes it. Kept together because a
periods endpoint nothing renders does not close anything. If it grows past a
reviewable size, the API boundary is the natural split — say so rather than
pushing a 900-line PR.

---

## Backend

### `GET /api/v1/leagues/{league_season_id}/periods`

Policy `LEAGUE_SCOPED`, gated by `require_league_member`, exactly like
`standings`. Response:

```json
{ "data": [
  { "id": "…", "ordinal": 1, "label": "Week 1", "type": "regular",
    "status": "final", "start_date": "2025-10-21", "end_date": "2025-10-27" }
] }
```

Ordered by `ordinal` ascending.

**Return every period, not only the final ones.** The reader should see the
season's actual shape — including the periods not yet played — rather than a
silently filtered list that makes a half-finished season look complete. Which
ones are *selectable* is a UI decision (below), and it is driven by `status`,
which is why `status` is in the payload.

**Excluded fields, deliberately:**

- `provider_period_id` — provider identifiers do not escape the ingestion
  layer (`schema/README.md` §Identifiers; charter D19). It has no business on
  the wire.
- `finalized_at` — nothing writes it yet (that is **H-07**). Shipping a field
  that is always `null` teaches every future consumer that it means "not
  finalized," and they will be wrong the day H-07 lands.

**Envelope: `{data: [...]}` and nothing else.** No `as_of` / `freshness` /
`stale`. Those exist on standings because standings is *derived* and its
freshness is a real question. Periods are synced facts; inventing a freshness
envelope for them would be cargo-culting the shape.

### Files

- `backend/repos/matchups.py` — add `periods()` to `LeagueSeasonRepository`
  returning all periods in ordinal order, via `scoped_select` like its
  neighbours. Do **not** add a new repository; this is the same scope and the
  same table family as `final_periods()`.
- `backend/api/routers/periods.py` — new thin router, mirroring
  `routers/standings.py`: `@declare_policy`, `require_league_member`, a
  Pydantic wire model, no logic.
- `backend/api/deps.py` — a `get_periods_*` dependency that builds the scope
  from `require_league_member`, the same shape as `get_standings_service`.
  **The gate must be in the dependency chain, not just the route** — H-04b's
  matrix test now checks this transitively, and it should pass without special
  handling.
- `backend/api/app.py` — register the router.

There is no service layer here and none is needed: this is a scoped read with
no fold. Do not invent one for symmetry.

### Backend tests

- `401` no token · `403` non-member · `404` unknown league season · `200` shape
  and ordering. Mirror `tests/api/test_standings_route.py`.
- Periods from another league season are not returned (the tenancy test — seed
  two seasons).
- A season with no periods returns `{"data": []}`, not a 404.

---

## Frontend

### The selector

- `frontend/src/features/standings/periods.ts` — `usePeriods(leagueSeasonId)`,
  same shape as `useStandings`, key `["periods", leagueSeasonId]`.
- A selector on `/leagues/:leagueSeasonId` offering **only `status === "final"`
  periods**, plus a default "Full season" option.

  Non-final periods must not be selectable. `through_period` filters *final*
  periods by ordinal, so choosing an in-progress week 5 when weeks 1–3 are final
  returns week-3 standings under a "Week 5" label — a wrong answer with a
  confident heading. Render them disabled (so the season shape is visible) or
  omit them; disabled is better, and either way say which you chose and why in
  the PR.

- If no period is `final`, do not render the selector. The page keeps its
  existing not-synced state from S1-11b unchanged.

### Wiring `through_period`

`standingsKeys.detail` currently takes only the league id, and the comment
above it already anticipates this bite. **`through_period` must join the query
key** — a key missing a parameter serves one view's data for another, which
here means showing week-3 standings under a week-7 heading after a switch.

Pass it as the `through_period` query param; omit it entirely for "Full
season" (not `0`, not `null`).

### Surface H-01's honesty fields

The standings envelope carries `complete` and `unknown_category_count`, and
nothing renders them. H-01 made the data honest on the wire and deferred the
reader-facing half to here.

When `complete === false`, show a line near the table — not an error, not a
blocking state — saying some categories could not be determined and how many.
Something like *"{n} category results unknown — some source data was missing."*
The existing amber `stale` banner is the visual precedent; reuse its treatment
rather than inventing a second one.

This is charter §10: a computation that ran on partial inputs must say which
inputs were missing. A silent `complete: false` is the same failure the field
was added to end.

### Frontend tests

- Selector renders only final periods; a non-final period is not selectable.
- Selecting a period refetches with `through_period` and the **query key
  changes** — assert the key or assert two distinct fetches, not just that the
  UI updated.
- "Full season" omits the parameter entirely.
- `complete: false` renders the unknown-categories line; `complete: true` does
  not.
- No final periods → no selector, not-synced state unchanged.

---

## A practical note that will confuse you otherwise

**Nothing in the codebase currently writes `matchup_periods.status = 'final'`**
— that is H-07, still open. So against a real synced league the selector may
show every period as `scheduled` and offer nothing selectable, and standings
will show not-synced. That is correct behaviour given the missing producer, not
a bug in this bite.

Seed statuses explicitly in tests. Do not infer finality from dates, and do not
add a fallback that treats a past `end_date` as final — that would be inventing
the finality rule in the read path, which is exactly what H-07 exists to do
properly in one place.

---

## Acceptance criteria

- [ ] `GET .../periods` returns all periods, ordinal-ordered, correctly gated,
      without `provider_period_id` or `finalized_at`.
- [ ] The selector offers only final periods and drives `through_period`.
- [ ] `through_period` is part of the standings query key.
- [ ] `complete: false` is visible to a reader.
- [ ] `pytest && ruff check backend tests && mypy` clean; `frontend/`
      typecheck, lint, test, build clean.
- [ ] `openapi.json` **and** `openapi.d.ts` regenerated — a new endpoint moves
      both, and CI drift-gates them.

## Data model / API impact

One new read endpoint. No schema change, no migration. The standings contract
is unchanged — this bite only starts *rendering* fields H-01 already added.

## Rollback

Additive: a new endpoint plus frontend changes. Reverting the squash commit
restores S1-11b's page.

## Out of scope

`S1-11d` (reaching a league without pasting a UUID), `H-05` through `H-10`,
and anything that writes period finality (`H-07`).

## Notes for review

Claude will check: that all periods are returned but only final ones are
selectable, that `through_period` is in the query key, that no
provider-identifier or always-null field reached the wire, that the tenancy
test seeds two seasons, that no date-based finality fallback was invented, and
that `complete: false` is actually rendered rather than merely typed.
