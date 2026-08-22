# S1-11b · League page (standings)

**Status:** NEXT (assigned) · **Depends on:** S1-11a (merged, `0ff1059`) · **PR into:** `v2`
**Branch:** `feat/s1-11b-league-page`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md) · **Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

---

## User story

A league member opens `/leagues/:leagueSeasonId` and sees their league's
standings — the ranked table folded from final matchup periods — with honest
loading, error, empty, and not-yet-synced states. This is the first shared
league surface in V2 and the page the vertical slice exists to prove.

## What this bite is

Frontend only. One route, one query hook, one page component, tests. The
backend read path (S1-10b) and the frontend foundation (S1-11a) are both
merged; this bite connects them.

**No backend changes.** `GET /api/v1/leagues/{league_season_id}/standings` is
already in the committed `frontend/openapi.json` snapshot (and therefore in the
generated `openapi.d.ts`). Do **not** regenerate the client — if you think you
need to, stop and ask, because it means something upstream drifted.

## The contract you are consuming

`GET /api/v1/leagues/{league_season_id}/standings` — policy `LEAGUE_SCOPED`,
optional `?through_period=<int ≥1>` query param (unused in this bite; the
selector is S1-11c). Responses:

- `200` → `{ data: StandingRowOut[], as_of: date | null, freshness: "final", stale: boolean }`
  - `data` rows, already ranked: `{ rank, team_id, team_name, team_abbreviation (nullable), wins, losses, ties, win_pct, played }`
  - `as_of` is the max `end_date` of the folded periods; **`null` means the
    season has never had a final period synced** — not an error.
- `401` no/bad token · `403` authenticated but not a member · `404` league
  season does not exist (existence is checked before membership, so 404 and
  403 are both possible and mean different things) · `422` bad UUID.

## Files

Create:

- `frontend/src/features/standings/queries.ts` — `standingsKeys` +
  `useStandings(leagueSeasonId)`. Follow `features/me/queries.ts` exactly:
  key is `["standings", leagueSeasonId]` (the comment in `me/queries.ts`
  already promises this shape — include `through_period` in the key **when
  S1-11c adds it**, not now). Call
  `api.GET("/api/v1/leagues/{league_season_id}/standings", { params: { path: { league_season_id } } })`.
  `retry: false` (401/403/404 won't succeed on retry).
  On `error`, throw so react-query surfaces `isError` — but preserve the
  status: the page copy differs for 403/404 vs everything else. Simplest:
  throw an `Error` subclass carrying `status`, or return the error status in
  the thrown message via a small typed helper. Your call; keep it small.
- `frontend/src/features/standings/LeaguePage.tsx` — the page.
- `frontend/src/features/standings/LeaguePage.test.tsx` — tests (see below).

Modify:

- `frontend/src/app/router.tsx` — add
  `{ path: "leagues/:leagueSeasonId", element: <LeaguePage /> }` under the
  existing `Layout` route. The route-param name is `leagueSeasonId`
  (camelCase in the router, snake_case only at the API boundary).

Do not touch anything else. In particular: no changes to `openapi.json`,
`openapi.d.ts`, `client.ts`, `auth.ts`, or the backend.

## Page behaviour (the actual point of this bite)

Read `frontend/src/shared/ui/StateMessage.tsx` first — its comment defines the
vocabulary this page must use. Mapping:

| Condition | Render |
|---|---|
| request in flight | `StateMessage kind="loading"` |
| 403 or 404 | `StateMessage kind="error"` with copy that does not leak which — e.g. "This league doesn't exist or you're not a member." (The API already ordered 404-before-403 correctly; the UI should not undo that by printing "forbidden" for one and "missing" for the other.) |
| any other error | `StateMessage kind="error"`, generic copy |
| `200`, `as_of === null` | `StateMessage kind="not-synced"` — e.g. "This league hasn't synced a completed week yet." **Not** the empty state, not an error. |
| `200`, `as_of !== null`, `data.length === 0` | `StateMessage kind="empty"` |
| `200`, rows present | the table |
| `stale === true` | a banner *above* the table ("Showing data as of {as_of}"), table still renders. The read path currently always sends `stale: false`; render it anyway — the vocabulary comment in `StateMessage.tsx` says stale is a banner over real numbers, and live freshness will arrive in a later bite. |

The table, inside the existing `Card`:

- Columns: **#** (rank), **Team** (`team_name`, with `team_abbreviation` shown
  when present — dimmed, after the name), **W**, **L**, **T**, **Pct**, **GP**
  (`played`).
- `win_pct` formatted basketball-style: three decimals, no leading zero —
  `.667`, `1.000`. Write a tiny local `formatWinPct` in the page file; do not
  create a shared util for one caller.
- Rows in the order the API returns them — **do not re-sort client-side.**
  Rank is a server fact (the domain fold owns tie-breaking); the UI displays
  it.
- Below the table, a quiet footer line: "Final through {as_of}" (the envelope's
  `as_of`, formatted as a date). This is the freshness surface until 11c's
  selector replaces it.
- A plain `<table>` with Tailwind classes in the style of the existing shell
  (gray-50/white, border-gray-200) is exactly right. No table library.

## Tests

Mirror `MePage.test.tsx` mechanics: `vi.mock` the generated client, render
under a `QueryClientProvider` with retries off, wrap in a router (the page
reads `useParams`, so use `createMemoryRouter` or `MemoryRouter` with an
initial entry of `/leagues/<uuid>`).

Cover, at minimum:

1. **Contract pin** — `api.GET` called with
   `"/api/v1/leagues/{league_season_id}/standings"` and the path param taken
   from the URL.
2. **Rows render in server order** with formatted `win_pct` (give the mock
   rows ranks 1..3 and assert the rendered order and a `.667`-style string).
3. **`as_of: null` → not-synced state**, and it is *not* the error state.
4. **Empty `data` with non-null `as_of` → empty state.**
5. **Error → alert role** (the 403/404 copy variant is worth one assertion if
   your error-status plumbing distinguishes it; if not, the generic alert
   suffices and say so in the PR).

## Acceptance criteria

- [ ] `/leagues/:leagueSeasonId` renders the standings table for a member of
      a synced league (manually verifiable against a local backend with the
      dev token shim — see `frontend/README.md`).
- [ ] All state mappings in the table above behave as specified.
- [ ] No client-side re-sorting; no regenerated client artifacts in the diff.
- [ ] `npm run typecheck && npm run lint && npm run test && npm run build`
      all green in `frontend/`.
- [ ] CI green (including both drift gates — which your diff must not touch).

## Data model / API impact

None. Read-only consumer of an existing endpoint.

## Rollback

Frontend-only route addition; reverting the squash commit removes the page
cleanly. No migrations, no contract changes.

## Out of scope (resist these)

- Period selector / `through_period` wiring — **S1-11c**.
- `GET /me/leagues` or any way to *discover* the league-season UUID — **S1-11d**.
  Reaching the page by pasting an ID is acceptable for this bite.
- Nav links in the `Layout` header, breadcrumbs, league name in the header
  (the standings endpoint doesn't return the league's name; getting it is a
  later bite, don't add an endpoint for it).
- Supabase login flow (the dev token shim stands).

## Notes for review

Claude will check: state-vocabulary compliance (especially not-synced vs
empty), the contract pin in tests, no client-side sorting, win_pct formatting,
and that the diff touches only the four files named above plus the router.
