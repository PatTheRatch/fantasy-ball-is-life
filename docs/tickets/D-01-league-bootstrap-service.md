# D-01 · League bootstrap service

**Status:** NEXT (assigned) · **Depends on:** S1-06, S1-07, S1-08, H-03 · **PR into:** `v2`
**Branch:** `feat/d-01-league-bootstrap`
**Backlog:** [`docs/v2/BACKLOG.md`](../v2/BACKLOG.md) §Demo path
**Process:** [`CONTRIBUTING.md`](../../CONTRIBUTING.md)

---

## Why this exists

The read path is finished and proven. **The write path does not exist** — not
the endpoints, and not the services behind them. Nothing in `backend/` has ever
created a `league`, a `league_season`, a `fantasy_team_season`, or a
`matchup_period`. Every row that has existed in this database came from a test
fixture.

S1-06 landed the schema. S1-07 landed an adapter that fetches settings, teams
and periods. **Nobody joined them.** This bite is that join, and it is the first
of three that put Patrick's real league on screen.

This is a service, not an endpoint. Onboarding UI is a later decision; D-03's
CLI is the caller for now.

## The three adapter gaps

`ESPNAdapter` cannot currently supply three things this service needs. Extend
it — the DTOs are the contract, and provider objects still must not escape the
package.

**1 · League name.** `LeagueSettingsDTO` has no name field, and `leagues.name`
is `NOT NULL`. Add it. Note `leagues.slug` also has a
`slug = lower(slug)` check constraint — derive a slug from the name and
guarantee lowercase; do not let the provider's casing reach it.

**2 · Scoring categories.** `LeagueSettingsDTO` carries no categories, and
without `league_season_categories` rows the matchup sync computes nothing —
`scoring_categories()` returns an empty list and every matchup gets zero
category results. ESPN exposes these in settings (`scoringItems`); map them to
the `categories` rows seeded by `0004_seed_categories` by key.

**Charter D11 is binding here: the count is whatever the season declares.** Do
not fall back to `NINE_CAT` when the mapping comes up short. If a provider
category does not map to a seeded `Category`, that is a real condition — record
it and fail the run as `partial`, exactly as an unresolved player would.
`NINE_CAT` is a test/seed convenience and must not become a runtime default.

**3 · Team owners.** `TeamDTO` carries no owner information, and this is the
one that silently breaks the whole demo — see below.

## The membership chain, which is the trap in this bite

`require_league_member` gates every league route through:

```
users → manager_user_links → managers
      → fantasy_team_season_managers → fantasy_team_seasons
```

**Nothing creates any of the middle rows.** So without this, the bootstrap
succeeds, the data is correct, the standings fold works — and Patrick gets a
**403 on his own league**, because no `manager` exists and nothing links one to
his user.

So D-01 must create the manager side: for each team's owners, a `managers` row
and a `fantasy_team_season_managers` row (`role='owner'`, both dates null for
the common case; `role='co_manager'` for additional owners — charter D9).

**Create managers unclaimed — do not link them to users here.** Charter D13 and
`schema/01-identity.md` are explicit that a manager exists without a user, and
that an unclaimed manager simply has no `manager_user_links` row: *"That is a
valid, expected state."* Most historical owners will never have an account.
Linking a real person to a manager is a deliberate, auditable act, and it lands
in **D-03** as an explicit claim step.

Match owners to existing managers by the provider's owner id within this
provider, not by display name. A name is not an identity — that is the whole
lesson of S1-09.

## What the service does

`LeagueBootstrapService.bootstrap(connection, provider_league_id, season_year)`:

1. `fetch_settings` → `leagues` (get-or-create by provider identity) +
   `league_seasons` + `league_season_categories`.
2. `fetch_teams` → `fantasy_teams` (the franchise) + `fantasy_team_seasons` +
   `managers` + `fantasy_team_season_managers`.
3. `fetch_periods` → `matchup_periods`.

**Wrap the whole thing in `ingestion.run_scope(...)`** (H-03's context manager).
This is a provider ingest like any other: raw payloads recorded before
interpretation, lineage stamped on the canonical rows, and a terminal run status
guaranteed. Do not hand-roll the run lifecycle — H-03 exists precisely so this
bite does not.

### Four rules that are not obvious

**Idempotent by natural key.** This will be re-run constantly during the demo
work. A second run over unchanged data must produce zero new rows, not
duplicates. Get-or-create on: league by `(provider_key, provider_league_id)`,
league_season by `(league_id, nba_season_id)`, team_season by
`(league_season_id, provider_team_id)` — the unique constraints already exist,
so lean on them.

**Skip periods with no derivable dates.** `MatchupPeriodDTO.start_date` and
`end_date` are nullable when a period has no games yet, and its docstring is
explicit: *"the ingestion pipeline must skip or reject an underivable period,
never invent a date range."* `matchup_periods` has both `NOT NULL`. Skip them
and count what you skipped into the run stats — a future period is a normal
condition, not an error.

**Do not set `status='final'` on any period.** H-05a added
`(status='final') = (finalized_at IS NOT NULL)`, and finality is D-02's job.
Bootstrap writes periods as `scheduled`. A period is not final because its dates
have passed — inventing that rule here is exactly what D-02 exists to do
properly in one place.

**One season per call.** `fantasy_teams` is the franchise and outlives a
season, but matching franchises *across* seasons needs a rule we do not have
(ESPN reassigns team ids). For now, one franchise per team per bootstrap, and
if a later season needs to reuse a franchise, that is a real design question —
raise it, do not guess.

## Files

- `backend/providers/espn/adapter.py` + `backend/domain/dto.py` — the three
  additions (league name, scoring categories, owners). Additive to existing
  DTOs.
- `backend/services/league_bootstrap.py` — new.
- `backend/repos/` — get-or-create repositories for the tables above. These are
  **ingestion-side, cross-tenant by nature** (they create the league that a
  scope would be built from), so they do not take a `LeagueSeasonScope` — same
  reasoning as `require_league_member` in H-04a. Comment it, and keep them out
  of the read path.

If the adapter extensions and the persistence together grow past a reviewable
size, that boundary is the natural split — say so rather than pushing one huge
PR.

## Tests

- Bootstrap from a fixture creates league, season, categories, teams, periods,
  managers, and team-season-manager rows.
- **Re-running produces zero new rows** (the idempotency test — assert counts
  before and after).
- A period with null dates is skipped and counted, not invented and not fatal.
- No period is written `final`.
- A provider category with no matching seeded `Category` fails the run
  `partial` rather than silently dropping or defaulting to nine.
- Co-managed team → one `owner` and one `co_manager` row.
- Managers are created with **no** `manager_user_links` row.
- **The one that proves the point:** after bootstrap, a user linked to one of
  the created managers passes `is_member` for that league season — and a user
  linked to nothing does not. This is the assertion that catches the 403 before
  it wastes a demo.
- Run lifecycle: an adapter failure mid-bootstrap leaves the run `failed`, not
  `running` (H-03's guarantee, exercised here).

## Acceptance criteria

- [ ] A league, its season, categories, teams, periods and managers are created
      from adapter output alone.
- [ ] Re-running changes nothing.
- [ ] Managers are unclaimed; membership works once a link exists.
- [ ] No period is `final`; no category defaults to nine.
- [ ] `pytest && ruff check backend tests && mypy` clean; migrations unchanged.
- [ ] No API change — `openapi.json` must not move.

## Data model / API impact

No schema change and no migration — every table already exists. No wire change.

## Rollback

New service plus additive adapter fields; the squash commit reverts cleanly.

## Out of scope

- **Claiming a manager for a real user** — D-03.
- **Period finality** — D-02 (H-07).
- **Any HTTP endpoint or onboarding UI.** This is a service; D-03's CLI calls it.
- `H-05b`, `H-05c`, `H-06`, `S1-11d`.

## Notes for review

Claude will check: that managers are created but not linked, that the
`is_member` test exists and would fail without the manager rows, that
`NINE_CAT` appears nowhere in the runtime path, that no period is written
`final`, that re-running is proven zero-write by counts rather than asserted in
prose, and that `run_scope` wraps the whole operation rather than the run being
hand-rolled.
