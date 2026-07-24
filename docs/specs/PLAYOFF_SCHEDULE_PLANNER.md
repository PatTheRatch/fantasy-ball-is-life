# Feature Spec: Playoff-Weeks Schedule Planner

**Status:** Product direction set by Patrick (owner) 2026-07-24 — pending
Aisha's technical review before implementation (per
`docs/AISHA_OPERATING_MANUAL.md`).
**Author:** Claude Code (implementation engineer)
**Date:** 2026-07-24
**Decision basis:** Fantasy playoffs are won in October: a late-round pick
whose NBA team plays 4 games in your league's playoff weeks quietly beats a
better player with 2. This is pure schedule math on data we already have —
the smallest spec in the current batch, with outsized draft-day value.

---

## 1. User story

> Which NBA teams play the most games during MY league's playoff weeks —
> and which players (on rosters or waivers) benefit? I want this at the
> draft, and again at the trade deadline.

## 2. What it computes

1. **Which weeks are your playoffs.** From league settings already pulled in
   `pull_league_meta` / stored in the settings snapshot: `reg_season_count`
   (`reg_season_weeks`) + `playoff_team_count` + playoff matchup period
   length → playoff matchup periods (e.g. weeks 20–23). Per league, from its
   own ESPN settings — no hardcoding.
2. **Games per NBA team per matchup week.** Join the NBA schedule to the
   league's matchup-week calendar (`get_matchup_weeks(season_year)` — already
   season-keyed) and count each pro team's games in each week. Schedule
   source: `get_pro_schedule()` (espn_api, already used for `num_games_left`)
   for the current season; the `nba_api` ingest (FCP_PROJECTIONS M-1) becomes
   the season-agnostic source once it exists.
3. **Player-level view.** Any player's playoff-weeks games = their NBA
   team's count. Overlay on rosters and the FA pool.

## 3. Surfaces

- **Standalone table** — "Playoff schedule" section on the Season tools page
  (`/leagues/:slug/season`): 30 NBA teams × playoff weeks, games per week +
  total, sortable, best/worst highlighted. Auto-loads (D-P6).
- **Draft Room column** — playoff-games total as a sortable column/badge on
  draft player tables (this is *the* use case: draft-day tiebreaks between
  similar players).
- **Advisor hook (later):** the Streaming Advisor's valuation can weight
  playoff-week games when the season is late — a one-line multiplier once
  both features exist.

## 4. API

`GET /leagues/{slug}/playoff-schedule` →
```json
{
  "playoff_weeks": [20, 21, 22, 23],
  "teams": [
    {"pro_team": "DEN", "games_by_week": {"20": 4, "21": 3, "22": 4, "23": 4}, "total": 15},
    ...
  ]
}
```
Computed on demand, cacheable aggressively (the NBA schedule changes ~never
mid-season; cache daily). Public-read like other league endpoints.

## 5. Phases

| Phase | Scope | Depends on | Done when |
|---|---|---|---|
| **W-1** | Playoff-week derivation + games-per-team computation + endpoint | — | Hermetic tests: playoff weeks derived from settings (incl. odd playoff lengths); counts correct against a fixture schedule; unknown slug 404 |
| **W-2** | Season tools table UI | W-1 | Vitest: renders sorted table, highlights, empty state pre-schedule-release |
| **W-3** | Draft Room playoff-games column | W-1 | Column sorts; shows totals from the same endpoint; no draft-flow regressions |

Genuinely small — W-1 is a day-sized slice.

## 6. Risks & open questions

- **Schedule availability window:** the NBA releases the season schedule in
  August; before that the endpoint returns an honest empty state (UI copy:
  "schedule not yet released"), not an error.
- **ESPN playoff-settings edge cases:** leagues with custom playoff week
  lengths or divisional formats — derive from settings, test odd shapes, and
  surface the derived weeks in the UI so a wrong derivation is visible.
- **Next-season drafts** (drafting in October for weeks that end in April):
  current-season schedule via `get_pro_schedule()` covers it; the nba_api
  source (M-1) removes the espn_api dependency later.
- **Open:** show back-to-backs / off-day density as a tiebreak within equal
  game counts? v1: games count only.

## 7. Out of scope (v1)

- Weekly (non-playoff) schedule-strength planning for streaming — that's the
  Advisor's multi-week planning item, separately deferred.
- Opponent-strength weighting (pace/defense) — pairs with the nba_api
  enrichment later.
- Custom user-selected week ranges (v1 derives playoff weeks; a manual
  override field is a cheap later add).
