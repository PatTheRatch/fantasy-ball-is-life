import type { JsonRecord } from '../api'

/** Sum roster `num_games_left` (player-games scheduled in the requested window). */
export function sumNumGamesLeft(rows: JsonRecord[]): number {
  return rows.reduce((acc, r) => {
    const v = Number(r.num_games_left)
    return acc + (Number.isFinite(v) && v > 0 ? v : 0)
  }, 0)
}

/** Clamp a calendar day into [weekStart, weekEnd] for “remaining schedule” requests. */
export function clampDateToWeekWindow(
  isoDay: string,
  weekStart: string,
  weekEnd: string,
): string {
  if (isoDay < weekStart) return weekStart
  if (isoDay > weekEnd) return weekEnd
  return isoDay
}

export const STAT_ORDER = [
  'PTS',
  'REB',
  'AST',
  'STL',
  'BLK',
  '3PM',
  'FG%',
  'FT%',
  'TO',
] as const

export type ProjectionSource = 'bbm' | '15' | '30'

export function mapProjectionSource(
  s: ProjectionSource,
): 'BBM' | '15' | '30' {
  if (s === 'bbm') return 'BBM'
  if (s === '15') return '15'
  return '30'
}

export type MatchupGroup = {
  key: string
  home: string
  away: string
  stats: JsonRecord[]
}

export function groupByMatchup(rows: JsonRecord[]): MatchupGroup[] {
  const map = new Map<string, JsonRecord[]>()
  const order: string[] = []
  for (const r of rows) {
    const h = String(r.home_team ?? '')
    const a = String(r.away_team ?? '')
    const key = `${h}|||${a}`
    if (!map.has(key)) {
      order.push(key)
      map.set(key, [])
    }
    map.get(key)!.push(r)
  }
  return order.map((key) => {
    const [home, away] = key.split('|||')
    return { key, home, away, stats: map.get(key)! }
  })
}

function sortStats(stats: JsonRecord[]): JsonRecord[] {
  const idx = (s: string) => {
    const i = STAT_ORDER.indexOf(s as (typeof STAT_ORDER)[number])
    return i === -1 ? 99 : i
  }
  return [...stats].sort(
    (a, b) => idx(String(a.stat)) - idx(String(b.stat)),
  )
}

export function prepareMatchupGroups(rows: JsonRecord[]): MatchupGroup[] {
  return groupByMatchup(rows).map((g) => ({
    ...g,
    stats: sortStats(g.stats),
  }))
}

/** Projected category record (W-L-T). */
export function projectedRecord(stats: JsonRecord[]): { home: number; away: number } {
  let hw = 0
  let aw = 0
  for (const r of stats) {
    const hr = String(r.projected_home_result ?? '').toUpperCase()
    if (hr === 'W') hw += 1
    else if (hr === 'L') aw += 1
  }
  return { home: hw, away: aw }
}

/** Winner for current/live stats (TO is a natural positive count, fewer is better; all others higher is better). */
export function currentStatWinner(
  stat: string,
  homeRaw: number,
  awayRaw: number,
): { home: 'W' | 'L' | 'T'; away: 'W' | 'L' | 'T' } {
  const h = Number(homeRaw)
  const a = Number(awayRaw)
  if (!Number.isFinite(h) || !Number.isFinite(a)) {
    return { home: 'T', away: 'T' }
  }
  if (stat === 'TO') {
    // Turnovers are a natural positive count; fewer is better.
    if (h < a) return { home: 'W', away: 'L' }
    if (a < h) return { home: 'L', away: 'W' }
    return { home: 'T', away: 'T' }
  }
  if (h > a) return { home: 'W', away: 'L' }
  if (a > h) return { home: 'L', away: 'W' }
  return { home: 'T', away: 'T' }
}

export function enrichCurrentRows(rows: JsonRecord[]): JsonRecord[] {
  return rows.map((r) => {
    const stat = String(r.stat ?? '')
    const h = Number(r.current_home_score)
    const a = Number(r.current_away_score)
    const { home: homeRes, away: awayRes } = currentStatWinner(stat, h, a)
    return {
      ...r,
      _home_res: homeRes,
      _away_res: awayRes,
    }
  })
}

export function currentRecord(stats: JsonRecord[]): { home: number; away: number } {
  let hw = 0
  let aw = 0
  for (const r of stats) {
    const hr = String((r as JsonRecord)._home_res ?? '').toUpperCase()
    if (hr === 'W') hw += 1
    else if (hr === 'L') aw += 1
  }
  return { home: hw, away: aw }
}

export function formatStatValue(stat: string, v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  if (stat === 'FG%' || stat === 'FT%') {
    const pct = n <= 1 && n >= 0 ? n * 100 : n
    return `${pct.toFixed(1)}%`
  }
  return n.toFixed(1)
}

export function pillClass(
  result: string,
): 'bg-emerald-600/90' | 'bg-red-600/80' | 'bg-slate-600/80' {
  const r = result.toUpperCase()
  if (r === 'W') return 'bg-emerald-600/90'
  if (r === 'L') return 'bg-red-600/80'
  return 'bg-slate-600/80'
}

export function rankPillClass(rank: number): string {
  if (rank <= 3) return 'bg-emerald-600/25 text-emerald-300 border-emerald-600/40'
  if (rank <= 7) return 'bg-amber-500/15 text-amber-200 border-amber-500/35'
  return 'bg-red-600/15 text-red-300 border-red-600/35'
}

const RANK_KEYS = [
  'pts_rank',
  'reb_rank',
  'ast_rank',
  'stl_rank',
  'blk_rank',
  '3pm_rank',
  'fg_pct_rank',
  'ft_pct_rank',
  'to_rank',
] as const

export function rankPillEntries(row: JsonRecord): { label: string; rank: number }[] {
  const out: { label: string; rank: number }[] = []
  const labels: Record<string, string> = {
    pts_rank: 'PTS',
    reb_rank: 'REB',
    ast_rank: 'AST',
    stl_rank: 'STL',
    blk_rank: 'BLK',
    '3pm_rank': '3PM',
    fg_pct_rank: 'FG%',
    ft_pct_rank: 'FT%',
    to_rank: 'TO',
  }
  for (const k of RANK_KEYS) {
    const v = row[k]
    const n = typeof v === 'number' ? v : Number(v)
    if (Number.isFinite(n)) {
      out.push({ label: labels[k] ?? k, rank: Math.round(n) })
    }
  }
  return out
}
