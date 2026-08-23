# H-04a · Bind league repositories to a scope

**Status:** NEXT (assigned) · **Depends on:** nothing · **PR into:** `v2`
**Branch:** `fix/h-04a-league-season-scope`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md) §Slice 1 hardening
**Source:** [`research/REDTEAM_TRIAGE.md`](../v2/research/REDTEAM_TRIAGE.md) §9
**Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

> H-04 is split. **This is the repository half.** The route-policy half — making
> `@declare_policy` enforce rather than label — is **H-04b** and lands next.
> They are independent; keep them in separate PRs.

---

## Why this is ahead of S1-11c

S1-11c adds `GET /api/v1/leagues/{league_season_id}/periods` and the read path
behind it. **No periods repository exists yet.** If S1-11c lands first, it adds
another unscoped repository and another `LEAGUE_SCOPED` route with no structural
enforcement, and this bite has to retrofit both. Fixing the foundation first
means S1-11c is written against it.

## The bug, and why it is more interesting than "the base sits unused"

Charter D26 says repositories touching league or manager data **cannot be
constructed without a scope object**. `repos/base.py` delivers exactly that
machinery, and its docstring is emphatic: *"tenancy is structural, not a
convention."*

But `LeagueScopedRepository` has **zero users**. `LeagueSeasonRepository` and
`MatchupRepository` — the two repositories that actually read league data —
take a bare `Session` (`repos/matchups.py:32,94`), and `get_standings_service`
constructs both with no scope at all (`api/deps.py:105-110`).

The reason is not laziness, and it matters for the fix. `LeagueScopedRepository`
hardcodes `scope_column = "league_id"` and filters on `self.scope.league_id`.
Every real league table landed in S1-06 keyed on **`league_season_id`** —
`Matchup`, `MatchupPeriod`, `FantasyTeamSeason`, `LeagueSeasonCategory`. The
base does not fit the tables it was built for. Its own docstring admits the
gap: *"no league-scoped table exists yet; its first real table lands in S1-06."*
S1-06 landed them and nothing came back to connect the two.

`tests/repos/test_scope_enforcement.py` proves the mechanism against a
throwaway `ScopedLeagueRow` model created solely for the test. The machinery
works. Nothing real is bound to it.

**There is no live hole** — the standings route is gated by
`require_league_member`. What is missing is the structure that makes the next
route safe by construction, which is the entire content of D26.

## The fix

**Add a season-level scope alongside the league-level one. Do not replace it.**

`LeagueScope(league_id)` keeps a legitimate future home: `fantasy_teams` is
keyed on `league_id` (`models/fantasy.py:199`) because a franchise outlives any
one season. Deleting it would remove the right tool for cross-season franchise
history. It stays unused for now, and that is fine — say so in its docstring so
the next reader does not repeat this investigation.

1. `backend/repos/scope.py` — add `LeagueSeasonScope(league_season_id: UUID)`,
   frozen, mirroring the existing dataclasses.
2. `backend/repos/base.py` — add `LeagueSeasonScopedRepository`, mirroring
   `LeagueScopedRepository`: scope required positionally, `scope_column`
   defaulting to `"league_season_id"`, `scoped_select` filtering on it, and no
   unscoped query path. Update `LeagueScopedRepository`'s docstring to say why
   it is still here and unused.
3. `backend/repos/matchups.py` — both repositories take
   `(scope: LeagueSeasonScope, session: Session)` and route every read through
   `scoped_select`. Drop the now-redundant `league_season_id` parameters from
   their methods: the scope carries it, and a method that takes it again invites
   passing one that disagrees with the scope.
4. `backend/services/standings_read.py` — the service receives already-scoped
   repositories. `StandingsReadService.standings(league_season_id, ...)` should
   no longer take `league_season_id`; it comes from the scope. Keep
   `through_period`.
5. `backend/api/deps.py` — `get_standings_service` depends on
   `require_league_member`, builds a `LeagueSeasonScope` from the
   `league_season_id` it returns, and constructs both repositories with it. This
   is the line that makes the guarantee real: the service **cannot** be wired
   without having passed the membership gate.
6. `backend/api/routers/standings.py` — the route keeps its
   `require_league_member` dependency for the 401/404/403 ordering; the service
   call loses its id argument.

### Three things that will bite you

**`LeagueSeasonRepository.get()` scopes on `id`, not `league_season_id`.** It
fetches the `LeagueSeason` row itself. Override `scope_column = "id"` on that
repository, exactly as `UserRepository` already does for the `users` table.
Better: have `get()` take no argument at all and return the scope's season.

**`MatchupCategoryResult` has no league column.** It carries only `matchup_id`
(`models/fantasy.py:350`), so `category_results_for` cannot be scope-filtered
directly. **Join through `matchups`** and apply the scope there. Do not leave it
unscoped on the reasoning that its ids came from a scoped query — that is
exactly the "discipline, not structure" this bite exists to end.

**`require_league_member` is the one legitimate cross-scope read, and it must
stay unscoped.** It establishes the scope, so it cannot be scoped by the thing
it produces — a scoped repository there would be circular. It currently
constructs `LeagueSeasonRepository(session)` for its existence check
(`deps.py:99`); once that requires a scope, do the existence check directly with
`session.get(LeagueSeason, league_season_id)` and comment it as the deliberate
exception. `LeagueMembershipRepository` also stays unscoped: answering "is this
user a member" is inherently a cross-scope question.

## Tests

- `tests/repos/test_scope_enforcement.py` — extend the existing generic proof to
  the new base with a throwaway season-keyed model: construction without a scope
  is a `TypeError`, and a cross-tenant read returns nothing.
- **The structural test that is the point of the bite:** constructing
  `MatchupRepository` or `LeagueSeasonRepository` without a scope fails. Assert
  it directly — this is the assertion that would have caught the gap.
- A repository scoped to season A returns nothing for season B's matchups, and
  the same for `category_results_for` **through the join** (seed two seasons;
  this is the test that catches leaving that method unscoped).
- Existing standings tests keep passing with the new construction shape. If a
  test only compiled because the id was passed explicitly, that is a signal the
  scope is not actually applied — check, don't just fix the call site.
- `tests/api/test_standings_route.py` — 401/404/403/200 ordering unchanged.

## Acceptance criteria

- [ ] Neither league repository can be constructed without a scope.
- [ ] Every read on them is scope-filtered, `category_results_for` included.
- [ ] `get_standings_service` cannot be wired without passing the membership gate.
- [ ] `require_league_member` is the single, commented cross-scope exception.
- [ ] `pytest && ruff check backend tests && mypy` clean; no API contract change,
      so `openapi.json` must **not** move — if it does, something leaked into the
      response model.

## Data model / API impact

None. Internal construction only; the wire contract is unchanged.

## Rollback

Code-only; the squash commit reverts cleanly.

## Out of scope

- **The route-policy half — H-04b.** `@declare_policy` still only sets an
  attribute and the matrix test still only checks presence. Do not start it here.
- Database-level constraints (`H-05`), the periods endpoint (`S1-11c`),
  all-play (`H-09`), link correction (`H-10`).

## Notes for review

Claude will check: that `scoped_select` is genuinely the only read path on the
new base, that `category_results_for` is scoped via a join rather than trusted,
that `require_league_member` is the *only* unscoped construction and is
commented as such, and that the cross-tenant tests would fail if the scope
filter were removed — a test that passes with the filter deleted is not a test
of tenancy.
