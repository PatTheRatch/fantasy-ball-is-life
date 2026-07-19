import type { CustomPlanSpec, DraftPoolParams } from '../api'

/* Draft Room — docs/specs/DRAFT_ROOM.md. Scoped "data-dense terminal" look
 * (D3): amber accent + tabular numerals, layered on the app's existing dark
 * chrome (Card, pg-* tokens) rather than reskinning the whole product.
 */

export const ACCENT = '#e7a93c'
export const CATS = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'FG%', 'FT%', 'TO'] as const
// Only counting categories are valid optimizer objectives (maximizing a
// percentage or turnovers is undefined) — mirrors draft_strategies.COUNTING_CATS.
export const COUNTING_CATS = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM'] as const
// Static, not league-specific — "favorite NBA team" is independent of ESPN/
// fantasy-league state, so no endpoint round-trip is needed for this dropdown.
export const NBA_TEAMS = [
  'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
  'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
  'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS',
] as const

export const STORAGE_KEY = 'draft-room-v1'
// v2: dropped the pinned games_per_week (backend now owns the default, 3.5 from
// config.GAMES_PER_WEEK — v1 clients pinned 3.0, silently disagreeing with the
// MC-targets spec). Bumping discards stored v1 state on load; done pre-draft on
// purpose so no stale 3.0 survives into a real draft.
export const SCHEMA_VERSION = 2
export const PRESETS_STORAGE_KEY = 'draft-room-presets-v1'

// Starting points for "Build a plan" (below) — the same shapes build_plan_configs'
// recipe uses, at their current percentile-band midpoint (draft_strategies.py,
// STRATEGY_PERCENTILE_BANDS as of 2026-07-10), so a user's blank-slate build
// starts from a sane, already-tuned baseline. Purely a prefill: every field is
// editable afterward, nothing here is enforced server-side.
export const BUILTIN_TEMPLATES: CustomPlanSpec[] = [
  {
    label: 'Balanced',
    constrained_categories: [...CATS],
    percentile: 0.35,
    stat_to_maximize: 'PTS',
    minimum_value_players: 3,
    ban_top_price: false,
  },
  {
    label: 'Stars & scrubs',
    constrained_categories: [...CATS],
    percentile: 0.25,
    stat_to_maximize: 'PTS',
    minimum_value_players: 6,
    ban_top_price: false,
  },
  {
    label: 'Spread value',
    constrained_categories: [...CATS],
    percentile: 0.33,
    stat_to_maximize: 'PTS',
    minimum_value_players: 1,
    ban_top_price: true,
  },
]

export const BLANK_CUSTOM_SPEC: CustomPlanSpec = {
  label: '',
  constrained_categories: [...CATS],
  percentile: 0.5,
  stat_to_maximize: 'PTS',
  minimum_value_players: 3,
  ban_top_price: false,
}

export const DEFAULT_PARAMS: DraftPoolParams = {
  n_plans: 10,
  initial_budget: 200,
  roster_size: 13,
  minimum_game_threshold: 20,
  // games_per_week deliberately unset — the backend owns that default
  // (config.GAMES_PER_WEEK), so one constant governs every surface.
  minimum_value_players: 3,
  value_source: 'bbm',
  exclude_players: [],
  favorite_team: null,
  favorite_team_representation: 1,
  target_players: [],
  target_categories: null,
  base_percentile: null,
  stat_to_maximize: null,
}
