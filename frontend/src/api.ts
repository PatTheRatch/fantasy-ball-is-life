import axios, { type AxiosInstance } from 'axios'

function resolveApiBase(): string {
  const raw = import.meta.env.VITE_API_BASE
  if (raw != null && String(raw).trim() !== '') {
    return String(raw).replace(/\/$/, '')
  }
  // Dev default: Vite proxy `/api` → backend (see vite.config.ts)
  if (import.meta.env.DEV) return '/api'
  return 'http://localhost:8000'
}

/** Base URL: `/api` (proxied in dev) or full URL from `VITE_API_BASE`. */
export const API_BASE = resolveApiBase()

const client: AxiosInstance = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 120_000,
})

function resolveDirectApiBase(): string {
  const raw = import.meta.env.VITE_API_BASE_DIRECT
  if (raw != null && String(raw).trim() !== '') {
    return String(raw).replace(/\/$/, '')
  }
  // Dev default: bypass the Vite proxy and hit FastAPI directly. The proxy is
  // fine for fast endpoints but drops long-running requests (recap
  // generation: ESPN assembly + an LLM call, 10-15s) even with an extended
  // proxy timeout in vite.config.ts, surfacing as a 502. CORS is already
  // configured on the backend for localhost/127.0.0.1 origins.
  if (import.meta.env.DEV) return 'http://127.0.0.1:8000'
  // Prod builds have no Vite proxy either way, so API_BASE is already direct.
  return API_BASE
}

/** Base URL that bypasses the Vite dev proxy — see `resolveDirectApiBase`. */
export const DIRECT_API_BASE = resolveDirectApiBase()

/** Same config as `client`, but talks to FastAPI directly instead of through
 * the Vite dev proxy. Use for requests the proxy can't reliably hold open
 * (currently: recap generation, which runs ESPN assembly + an LLM call). */
const directClient: AxiosInstance = axios.create({
  baseURL: DIRECT_API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 120_000,
})

/** Prefer FastAPI `detail` when present (e.g. validation errors). */
export function formatApiError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    // The base actually used for this request (client or directClient) is more
    // accurate than the module-level API_BASE when both are in play.
    const usedBase = err.config?.baseURL ?? API_BASE
    if (err.response == null) {
      const code = err.code
      if (
        code === 'ERR_NETWORK' ||
        code === 'ECONNREFUSED' ||
        (err.message && /network/i.test(err.message))
      ) {
        return `Cannot reach the API (${usedBase}). Start the backend (e.g. uvicorn backend.api.main:app --reload --port 8000) and reload the page.`
      }
    }
    const st = err.response?.status
    if (st === 502 || st === 503) {
      return `Bad gateway (${st}): the dev server could not reach FastAPI on port 8000, or the request timed out. Start the API (uvicorn backend.api.main:app --reload --port 8000) and try again. If the API is running, try setting VITE_API_BASE=http://127.0.0.1:8000 in frontend/.env to bypass the Vite proxy.`
    }
    const d = err.response?.data as { detail?: unknown } | undefined
    if (d && typeof d === 'object' && d.detail !== undefined) {
      if (typeof d.detail === 'string') return d.detail
      if (Array.isArray(d.detail)) {
        return d.detail
          .map((item) =>
            typeof item === 'object' && item && 'msg' in item
              ? String((item as { msg: unknown }).msg)
              : String(item),
          )
          .join(', ')
      }
    }
  }
  return err instanceof Error ? err.message : String(err)
}

export type JsonRecord = Record<string, unknown>

/* -------------------------------------------------------------------------- */
/* Response / body types (subset aligned with FastAPI `api.py`)               */
/* -------------------------------------------------------------------------- */

export interface HealthResponse {
  status: string
}

export interface LeagueSettings {
  reg_season_count?: number | null
  playoff_team_count?: number | null
  playoff_matchup_period_length?: number | null
  name?: string | null
  team_count?: number | null
  acquisition_budget?: number | null
  faab?: boolean | null
  scoring_type?: string | null
  current_week?: number | null
  [key: string]: unknown
}

export interface MatchupCommentaryRow {
  stat: string
  home_score: number
  away_score: number
  result: string
  confidence_pct?: number | null
}

export interface ProjectedRosterPlayer {
  player_name: string
  pts: number
  reb: number
  ast: number
  stl: number
  blk: number
  '3pm': number
  fg_pct: number
  ft_pct: number
  to: number
  games_left?: number | null
}

export interface MatchupCommentaryBody {
  home_team: string
  away_team: string
  matchup_data: MatchupCommentaryRow[]
  home_roster?: ProjectedRosterPlayer[]
  away_roster?: ProjectedRosterPlayer[]
  projections?: string | null
  is_live?: boolean
}

export interface MatchupCommentaryResponse {
  commentary: string
}

export interface LeagueRecapBody {
  week: number
  league_settings?: JsonRecord
  standings: JsonRecord[]
  power_rankings: JsonRecord[]
  transactions: JsonRecord[]
  scoreboard: JsonRecord[]
  week_dates: { start: string; end: string }
}

export interface LeagueRecapResponse {
  recap: string
}

export interface SeasonCommentaryBody {
  season_stats: JsonRecord[]
  /** Matchup week numbers included in season_stats (same window as GET /season-stats). */
  weeks: number[]
  league_settings: JsonRecord
  /** Optional; must match min(weeks) / max(weeks) if sent. */
  min_week?: number | null
  max_week?: number | null
}

export interface SeasonCommentaryResponse {
  commentary: string
}

export interface DraftPick {
  name: string
  bid: number
}

export interface OptimizeBody {
  exclude_players?: string[] | null
  games_per_week: number
  initial_budget: number
  year?: number | null
  roster_size: number
  minimum_value_players: number
  favorite_team?: string | null
  favorite_team_representation: number
  minimum_game_threshold: number
  value_col: string
  categories?: string[] | null
  percentile: number
  stat_to_maximize: string
  draft_picks: DraftPick[]
}

export interface MultiplePlansBody {
  n_plans?: number
  base_excluded?: string[] | null
  base_percentile?: number
  percentiles_cycle?: number[] | null
  categories?: string[]
  value_col?: string
  year?: number | null
  roster_size?: number
  favorite_team?: string
  minimum_game_threshold?: number
  initial_budget?: number
  sort_primary?: string
  out_prefix?: string
  objective_focus?: string
}

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await client.get<HealthResponse>('/health')
  return data
}

export async function getLeagueMeta(): Promise<JsonRecord> {
  const { data } = await client.get<JsonRecord>('/league/meta')
  return data
}

export async function getLeagueSchedule(
  year?: number,
): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>('/league/my-league/schedule', {
    params: year != null ? { year } : undefined,
  })
  return data
}

export async function getCurrentWeekMatchups(
  year?: number,
): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>(
    '/league/my-league/current-week-matchups',
    { params: year != null ? { year } : undefined },
  )
  return data
}

export async function getPowerRankings(
  weeks: string,
  recentWeeks = 3,
): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>('/power-rankings', {
    params: { weeks, recent_weeks: recentWeeks },
  })
  return data
}

export async function getConfidence(params: {
  projected_value: number
  stat: string
  player_avg: number
}): Promise<JsonRecord> {
  const { data } = await client.get<JsonRecord>('/confidence', { params })
  return data
}

export async function getMatchupConfidence(params: {
  current_matchup_period: number
  projections?: string
  games_played?: number
  total_games?: number
}): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>('/matchup-confidence', {
    params,
  })
  return data
}

export async function postMatchupCommentary(
  body: MatchupCommentaryBody,
): Promise<MatchupCommentaryResponse> {
  const { data } = await client.post<MatchupCommentaryResponse>(
    '/matchup-commentary',
    body,
  )
  return data
}

export async function postLeagueRecap(
  body: LeagueRecapBody,
): Promise<LeagueRecapResponse> {
  const { data } = await client.post<LeagueRecapResponse>('/league-recap', body)
  return data
}

export async function getLeagueTeams(): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>('/league/teams')
  return data
}

export async function getLeagueStandings(): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>('/league/standings')
  return data
}

export async function getLeagueSettings(): Promise<LeagueSettings> {
  const { data } = await client.get<LeagueSettings>('/league/settings')
  return data
}

export async function getSeasonStats(weeks: string): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>('/season-stats', {
    params: { weeks },
  })
  return data
}

export async function postSeasonCommentary(
  body: SeasonCommentaryBody,
): Promise<SeasonCommentaryResponse> {
  const { data } = await client.post<SeasonCommentaryResponse>(
    '/season-commentary',
    body,
  )
  return data
}

export async function getRostersOnDate(
  onDate: string,
): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>(`/rosters/${onDate}`)
  return data
}

export async function getTransactions(
  start: string,
  end: string,
): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>('/transactions', {
    params: { start, end },
  })
  return data
}

export async function getMatchups(
  scoringPeriod?: number,
): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>('/matchups', {
    params:
      scoringPeriod != null ? { scoring_period: scoringPeriod } : undefined,
  })
  return data
}

export async function getScoreboardCurrent(
  scoringPeriod?: number,
): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>('/scoreboard/current', {
    params:
      scoringPeriod != null ? { scoring_period: scoringPeriod } : undefined,
  })
  return data
}

export async function getRostersCurrent(params?: {
  week_start_date?: string
  week_end_date?: string
  bbm_path?: string
  current_matchup_period?: number
  projections?: string
}): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>('/rosters/current', {
    params,
  })
  return data
}

export async function postRostersCurrent(
  formData: FormData,
): Promise<JsonRecord[]> {
  const { data } = await client.post<JsonRecord[]>('/rosters/current', formData)
  return data
}

export async function getProjections(): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>('/projections')
  return data
}

export async function postProjections(
  formData: FormData,
): Promise<JsonRecord[]> {
  const { data } = await client.post<JsonRecord[]>('/projections', formData)
  return data
}

export async function postFeedRun(): Promise<JsonRecord> {
  const { data } = await client.post<JsonRecord>('/feed/run')
  return data
}

export async function postOptimizerOptimize(
  body: OptimizeBody,
  bbmFile?: File | null,
): Promise<JsonRecord[]> {
  const fd = new FormData()
  fd.append('data', JSON.stringify(body))
  if (bbmFile) {
    fd.append('bbm_file', bbmFile)
  }
  const { data } = await client.post<JsonRecord[]>('/optimizer/optimize', fd)
  return data
}

export async function postOptimizerMultiplePlans(
  body: MultiplePlansBody,
): Promise<JsonRecord[]> {
  const { data } = await client.post<JsonRecord[]>(
    '/optimizer/multiple-plans',
    body,
  )
  return data
}

/* -------------------------------------------------------------------------- */
/* Draft Room — docs/specs/DRAFT_ROOM.md                                      */
/* -------------------------------------------------------------------------- */

export interface DraftPickEntry {
  player_key: string
  price: number
  team_id: string
  is_user: boolean
}

/** A "make sure I get this player" prep-time favorite — not a real pick, so
 * it doesn't touch the real picks log or budget. Every generated plan is
 * built as if this player is already owned, at expected_price if given, else
 * their own projected $ value. Ignored once the same player is won or lost
 * for real. */
export interface DraftTargetPlayer {
  player_key: string
  expected_price?: number | null
}

export type DraftValueSource = 'bbm' | 'forge'

export interface DraftPoolParams {
  n_plans?: number
  initial_budget?: number
  roster_size?: number
  minimum_game_threshold?: number
  games_per_week?: number
  minimum_value_players?: number
  year?: number | null

  // Who prices each player. "bbm" is the uploaded projections file's own $
  // column. "forge" is Forge Value -- PatriotGames' own projection-derived
  // valuation, scaled to the live league's real team count + this draft's
  // roster size/budget.
  value_source?: DraftValueSource

  // Team construction.
  exclude_players?: string[]
  favorite_team?: string | null
  favorite_team_representation?: number
  target_players?: DraftTargetPlayer[]

  // What to optimize for.
  target_categories?: string[] | null
  base_percentile?: number | null
  stat_to_maximize?: string | null
}

export interface DraftPlanConfig {
  label: string
  shape: string
  constrained_categories: string[]
  percentile: number
  minimum_value_players: number
  stat_to_maximize: string
  ban_top_price: boolean
  punts: string[]
}

/** Per-player row shared by roster entries, next_target, and the value board —
 * D5's locked decision: $ value, position, and all 9 category contributions. */
export interface DraftPlayerRow {
  player_key: string
  max_bid: number
  pos?: string | null
  team?: string | null
  value?: number | null
  pts?: number | null
  reb?: number | null
  ast?: number | null
  stl?: number | null
  blk?: number | null
  tpm?: number | null
  fg_pct?: number | null
  ft_pct?: number | null
  to?: number | null
}

export type DraftPlanHealth = 'alive' | 'broken'

export interface DraftPlanSnapshot {
  plan_id: string
  label: string
  shape: string
  config: DraftPlanConfig
  roster: string[]
  players: DraftPlayerRow[]
  health: DraftPlanHealth
  health_reason: string | null
  next_target: DraftPlayerRow | null
}

export interface DraftFallbackNext {
  plan_id: string
  label: string
  player_key: string | null
  max_bid: number | null
}

export type DraftValueBoardEntry = DraftPlayerRow

export interface DraftPortfolioResponse {
  plans: DraftPlanSnapshot[]
  fallback_next: DraftFallbackNext | null
  value_board: DraftValueBoardEntry[]
  /** target_players that couldn't be locked in (below the games threshold,
   * excluded, a typo) — degrades gracefully rather than failing the request. */
  skipped_targets?: string[]
}

export interface DraftPlansBody extends DraftPoolParams {
  picks: DraftPickEntry[]
}

/** One hand-tuned plan spec -- the "build your own, save it" flow, as opposed
 * to the fixed 10-plan recipe /draft/plans generates. Every solver knob is
 * set directly instead of picked from a strategy shape. */
export interface CustomPlanSpec {
  label: string
  constrained_categories: string[]
  percentile: number
  stat_to_maximize: string
  minimum_value_players: number
  ban_top_price: boolean
}

export type CustomPlanBody = DraftPoolParams &
  CustomPlanSpec & {
    picks: DraftPickEntry[]
  }

export interface DraftCustomPlanResponse {
  plan: DraftPlanSnapshot
  value_board: DraftValueBoardEntry[]
  skipped_targets?: string[]
}

export interface DraftPickBody extends DraftPoolParams {
  picks: DraftPickEntry[]
  new_pick: DraftPickEntry
  prior_plans: DraftPlanSnapshot[]
}

export interface DraftTriageBody extends DraftPoolParams {
  picks: DraftPickEntry[]
  prior_plans: DraftPlanSnapshot[]
  player_key: string
}

export type DraftTriageReason = 'in_plan' | 'value_target' | 'safe_to_pass'

export interface DraftTriageResponse {
  player_key: string
  relevant: boolean
  in_plans: string[]
  max_bid: number | null
  reason: DraftTriageReason
}

export interface DraftRelaxBody extends DraftPoolParams {
  picks: DraftPickEntry[]
  prior_plans: DraftPlanSnapshot[]
  plan_id?: string | null
}

export interface DraftRelaxProposal extends DraftPlanSnapshot {
  dropped_category: string
  objective_score: number
  relaxed_from_plan_id: string
}

export interface DraftRelaxResponse {
  proposal: DraftRelaxProposal | null
  value_board: DraftValueBoardEntry[]
}

export async function postDraftPlans(
  body: DraftPlansBody,
): Promise<DraftPortfolioResponse> {
  const { data } = await client.post<DraftPortfolioResponse>('/draft/plans', body)
  return data
}

export async function postDraftCustomPlan(
  body: CustomPlanBody,
): Promise<DraftCustomPlanResponse> {
  const { data } = await client.post<DraftCustomPlanResponse>('/draft/plans/custom', body)
  return data
}

export async function postDraftPick(
  body: DraftPickBody,
): Promise<DraftPortfolioResponse> {
  const { data } = await client.post<DraftPortfolioResponse>('/draft/pick', body)
  return data
}

export async function postDraftTriage(
  body: DraftTriageBody,
): Promise<DraftTriageResponse> {
  const { data } = await client.post<DraftTriageResponse>('/draft/triage', body)
  return data
}

export async function postDraftRelax(
  body: DraftRelaxBody,
): Promise<DraftRelaxResponse> {
  const { data } = await client.post<DraftRelaxResponse>('/draft/relax', body)
  return data
}

export interface DraftPlayerResult {
  player_key: string
  pos: string | null
  team: string | null
  value: number | null
}

export async function getDraftPlayers(q: string): Promise<DraftPlayerResult[]> {
  if (q.length < 2) return []
  const { data } = await client.get<DraftPlayerResult[]>('/draft/players', { params: { q } })
  return data
}

export async function getProjectedScoreboard(params?: {
  week_end_date?: string
  current_matchup_period?: number
  projections?: string
}): Promise<JsonRecord[]> {
  const { data } = await client.get<JsonRecord[]>('/projected-scoreboard', {
    params,
  })
  return data
}

/** Multipart POST — optional BBM file when projections is BBM. */
export async function postProjectedScoreboard(
  payload: {
    current_matchup_period: number
    projections: string
    week_end_date?: string
  },
  bbmFile?: File | null,
): Promise<JsonRecord[]> {
  const fd = new FormData()
  fd.append('data', JSON.stringify(payload))
  if (bbmFile) {
    fd.append('bbm_file', bbmFile)
  }
  const { data } = await client.post<JsonRecord[]>('/projected-scoreboard', fd)
  return data
}

export interface RecapDataQuality {
  ready: boolean
  warnings: string[]
  checks: Record<string, boolean>
  transaction_quality: string
}

export interface RecapGeneratedContent {
  headline: string
  dek: string
  lead_story: string[]
  matchup_takeaways: Array<{
    matchup_id: string
    text: string
    evidence_ids: string[]
  }>
  ranking_explanations: Array<{
    team_id: string
    text: string
    evidence_ids: string[]
  }>
  award_explanations: Array<{
    award_id: string
    text: string
    evidence_ids: string[]
  }>
  whatsapp_summary: string
  whatsapp_full: string
}

export interface RecapSnapshot {
  schema_version: string
  league: JsonRecord
  season: number
  week: number
  week_dates: { start: string; end: string }
  matchups: JsonRecord[]
  standings: JsonRecord[]
  power_rankings: JsonRecord[]
  transactions: JsonRecord[]
  season_stats: JsonRecord[]
  award_candidates: JsonRecord[]
  data_quality: RecapDataQuality
}

export interface RecapEdition {
  id: string
  league_id: string
  season: number
  week: number
  version: number
  status: 'draft' | 'published' | 'superseded'
  structured_content_json: RecapGeneratedContent
  data_warnings_json: string[]
  created_at: string
  published_at?: string | null
  snapshot?: RecapSnapshot
  league_week_snapshots?: JsonRecord
}

export interface RecapHistoryItem {
  id: string
  version: number
  status: RecapEdition['status']
  data_warnings_json: string[]
  created_at: string
  published_at?: string | null
}

function bearer(token: string) {
  return { Authorization: `Bearer ${token}` }
}

// Recap endpoints use `directClient` (bypasses the Vite dev proxy) — see
// `resolveDirectApiBase` above. `getPublishedRecap` is a fast read, but kept
// on the same client as the others for one consistent base per feature.

export async function getPublishedRecap(
  slug: string,
  season: number,
  week: number,
): Promise<{ league: JsonRecord; edition: RecapEdition }> {
  const { data } = await directClient.get(`/leagues/${slug}/recaps/${season}/${week}`)
  return data
}

export async function getRecapReadiness(
  slug: string,
  season: number,
  week: number,
  weekStart: string,
  weekEnd: string,
  token: string,
): Promise<RecapSnapshot> {
  const { data } = await directClient.get(
    `/leagues/${slug}/recaps/${season}/${week}/readiness`,
    {
      params: { week_start: weekStart, week_end: weekEnd },
      headers: bearer(token),
    },
  )
  return data
}

export async function generateRecapDraft(
  slug: string,
  season: number,
  week: number,
  weekStart: string,
  weekEnd: string,
  generateAnyway: boolean,
  token: string,
): Promise<RecapEdition> {
  const { data } = await directClient.post(
    `/leagues/${slug}/recaps/${season}/${week}/generate`,
    {
      week_start: weekStart,
      week_end: weekEnd,
      generate_anyway: generateAnyway,
    },
    { headers: bearer(token) },
  )
  return data
}

export async function getRecapHistory(
  slug: string,
  season: number,
  week: number,
  token: string,
): Promise<RecapHistoryItem[]> {
  const { data } = await directClient.get(
    `/leagues/${slug}/recaps/${season}/${week}/history`,
    { headers: bearer(token) },
  )
  return data
}

export async function publishRecapEdition(
  slug: string,
  season: number,
  week: number,
  editionId: string,
  token: string,
): Promise<RecapEdition> {
  const { data } = await directClient.post(
    `/leagues/${slug}/recaps/${season}/${week}/publish`,
    { edition_id: editionId },
    { headers: bearer(token) },
  )
  return data
}

export async function rollbackRecapEdition(
  slug: string,
  season: number,
  week: number,
  editionId: string,
  token: string,
): Promise<RecapEdition> {
  const { data } = await directClient.post(
    `/leagues/${slug}/recaps/${season}/${week}/rollback`,
    { edition_id: editionId },
    { headers: bearer(token) },
  )
  return data
}

export { client as apiClient }
