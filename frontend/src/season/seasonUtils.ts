import type { JsonRecord } from '../api'

export const ESPN_RED = '#e03131'
export const STICKY_TOP = '60px'

export const STAT_LEADER_COLS = [
  'PTS',
  'REB',
  'AST',
  'STL',
  'BLK',
  '3PM',
  'TO',
  'FG%',
  'FT%',
] as const

export function num(r: JsonRecord, key: string): number {
  const v = r[key]
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : NaN
}

export function str(r: JsonRecord, key: string): string {
  return String(r[key] ?? '')
}

export function formatPctCell(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const pct = n > 0 && n <= 1 ? n * 100 : n
  return `${pct.toFixed(1)}%`
}

export function formatToCell(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return Math.abs(n).toFixed(1)
}

export function formatStatCell(col: string, v: unknown): string {
  if (col === 'FG%' || col === 'FT%') return formatPctCell(v)
  if (col === 'TO') return formatToCell(v)
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n % 1 === 0 ? String(Math.round(n)) : n.toFixed(1)
}

export function buildWeekList(from: number, to: number): number[] {
  const lo = Math.min(from, to)
  const hi = Math.max(from, to)
  const out: number[] = []
  for (let w = lo; w <= hi; w += 1) out.push(w)
  return out
}

export function seasonPhaseBanner(
  currentWeek: number,
  regSeasonCount: number,
): { emoji: string; label: string } {
  const reg = Math.max(1, regSeasonCount || 19)
  const cw = Math.max(1, currentWeek)
  const half = reg * 0.5
  if (cw <= half) {
    return {
      emoji: '📅',
      label: `Early Season — Week ${cw} of ${reg}`,
    }
  }
  if (cw <= reg) {
    return {
      emoji: '📅',
      label: `Mid Season — Week ${cw} of ${reg}`,
    }
  }
  const playoffWeek = Math.max(1, cw - reg)
  return {
    emoji: '🏆',
    label: `Playoffs — Week ${playoffWeek} of playoffs`,
  }
}

export function luckLabel(ratio: number): { emoji: string; text: string } {
  if (ratio >= 1.15) return { emoji: '🍀', text: 'Very Lucky' }
  if (ratio >= 1.0) return { emoji: '😊', text: 'Slightly Lucky' }
  if (ratio >= 0.85) return { emoji: '😤', text: 'Slightly Unlucky' }
  return { emoji: '💀', text: 'Very Unlucky' }
}

export type Medal = 'gold' | 'silver' | 'bronze' | null

export function medalClass(m: Medal): string {
  if (m === 'gold') return 'bg-amber-500/15'
  if (m === 'silver') return 'bg-slate-400/15'
  if (m === 'bronze') return 'bg-amber-800/25'
  return ''
}

export function computeColumnMedals(
  rows: JsonRecord[],
  col: (typeof STAT_LEADER_COLS)[number],
): Map<string, Medal> {
  const map = new Map<string, Medal>()
  const list = rows
    .map((r) => ({
      team: str(r, 'Team'),
      val: num(r, col),
    }))
    .filter((x) => x.team && Number.isFinite(x.val))

  const invert = col === 'TO'
  const sorted = [...list].sort((a, b) => {
    if (invert) return a.val - b.val
    return b.val - a.val
  })

  const medals: Medal[] = ['gold', 'silver', 'bronze']
  for (let i = 0; i < Math.min(3, sorted.length); i += 1) {
    map.set(sorted[i].team, medals[i])
  }
  return map
}

