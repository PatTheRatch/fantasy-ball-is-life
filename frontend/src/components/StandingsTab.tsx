import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronUp, ChevronDown } from 'lucide-react'
import { getSnapshot, type JsonRecord } from '../api'

/* ── helpers ─────────────────────────────────────────────────────── */

function norm(s: string) { return (s ?? '').trim().toLowerCase() }

const CATS = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'FG%', 'FT%', 'TO'] as const

function catRankKey(c: string) { return c.toLowerCase().replace('%', '_pct') + '_rank' }

type CatView = 'totals' | 'avg' | 'ranks'

function catVal(stats: Record<string, unknown>, cat: string, view: CatView, weeks: number): string {
  const v = Number(stats[cat] ?? 0)
  const d = Math.max(weeks, 1)
  const isPct = cat === 'FG%' || cat === 'FT%'
  const isTO = cat === 'TO'

  if (view === 'ranks') {
    const rk = Number(stats[catRankKey(cat)] ?? 0)
    return Number.isFinite(rk) ? String(Math.round(rk)) : '—'
  }
  if (view === 'avg') {
    const val = isTO ? Math.abs(v) / d : v / d
    if (isPct) return val.toFixed(3)
    return val.toFixed(1)
  }
  // totals: TO stored negated, display positive; FG%/FT% as decimals
  const val = isTO ? Math.abs(v) : v
  if (isPct) return val.toFixed(3)
  return String(Math.round(val))
}

type SortDir = 'asc' | 'desc'
type SortKey = { col: string; dir: SortDir }

/* ── main component ──────────────────────────────────────────────── */

export function StandingsTab({ slug, season, week }: { slug: string; season: number; week: number }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['recap', 'snapshot', slug, season, week],
    queryFn: () => getSnapshot(slug, season, week),
    retry: false,
  })

  const [catView, setCatView] = useState<CatView>('totals')
  const [sort, setSort] = useState<SortKey>({ col: 'rank', dir: 'asc' })

  // All hooks MUST be called unconditionally (before early returns)
  const snap = data?.snapshot as Record<string, unknown> | undefined
  const standings = (snap?.standings ?? []) as Record<string, unknown>[]
  const stats = (snap?.season_stats ?? []) as Record<string, unknown>[]
  const rankings = (snap?.power_rankings ?? []) as Record<string, unknown>[]

  const txnCounts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const t of (snap?.transactions ?? []) as Record<string, unknown>[]) {
      const tn = norm(String(t.team_name ?? ''))
      if (tn) m[tn] = (m[tn] || 0) + 1
    }
    return m
  }, [snap?.transactions])

  // Join by normalized team name
  const rows: Record<string, unknown>[] = useMemo(() => {
    const statsMap: Record<string, Record<string, unknown>> = {}
    for (const r of stats) {
      const t = norm(String(r.Team ?? r.team ?? ''))
      if (t) statsMap[t] = r
    }
    const rankMap: Record<string, Record<string, unknown>> = {}
    for (const r of rankings) {
      const t = norm(String(r.team ?? ''))
      if (t) rankMap[t] = r
    }
    return standings.map((s) => {
      const tn = norm(String(s.team_name ?? s.team ?? ''))
      const st: JsonRecord = statsMap[tn] ?? {}
      const rk: JsonRecord = rankMap[tn] ?? {}
      return { ...s, _tn: tn, _stats: st, _rank: rk }
    })
  }, [standings, stats, rankings])

  // Sort
  const sorted: Record<string, unknown>[] = useMemo(() => {
    const dir = sort.dir === 'asc' ? 1 : -1
    const get = (r: Record<string, unknown>, col: string): number => {
      const stats = r._stats as JsonRecord
      const pr = r._rank as JsonRecord
      if (col === 'rank') return Number(r.standing ?? 99)
      if (col === 'wins') return Number(r.wins ?? 0)
      if (col === 'losses') return Number(r.losses ?? 0)
      if (col === 'winPct') return Number(r.win_pct ?? 0) / 100
      if (col === 'allplayPct') return Number(pr.allplay_win_pct ?? 0) / 100
      if (col === 'luckRatio') return Number(pr['Win % Ratio'] ?? 1)
      if (col === 'powerRank') return Number(pr.rank ?? 99)
      if (col === 'movement') return -(Number(pr.rank_change ?? 0))
      if (col === 'transactions') return txnCounts[r._tn as string] ?? 0
      return Number(stats[col] ?? 0)
    }
    return [...rows].sort((a, b) => {
      const va = get(a, sort.col)
      const vb = get(b, sort.col)
      return (va - vb) * dir
    })
  }, [rows, sort, txnCounts])

  const weeksPlayed = Math.max(Number(snap?.week ?? week), 1)

  const handleSort = (col: string) => {
    setSort(s => s.col === col ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { col, dir: 'desc' })
  }

  const SortIcon = ({ col }: { col: string }) => {
    if (sort.col !== col) return null
    return sort.dir === 'asc' ? <ChevronUp className="inline h-3 w-3" /> : <ChevronDown className="inline h-3 w-3" />
  }

  const Th = ({ col, children }: { col: string; children: React.ReactNode }) => (
    <th
      className="cursor-pointer select-none whitespace-nowrap px-2 py-1.5 text-left text-[11px] font-medium text-slate-400 hover:text-white"
      onClick={() => handleSort(col)}
    >
      {children} <SortIcon col={col} />
    </th>
  )

  // Early returns — all hooks above this line
  if (isLoading) return <p className="text-slate-400">Loading standings…</p>
  if (error) {
    const s = (error as { response?: { status: number } })?.response?.status
    if (s === 404) return <p className="text-slate-500">No standings for this week.</p>
    return <p className="text-red-400">Could not load standings.</p>
  }
  if (!snap) return <p className="text-slate-500">No standings for this week.</p>
  if (!standings.length) return <p className="text-slate-500">No standings for this week.</p>

  /* ── render ────────────────────────────────────────────────────── */

  return (
    <div className="space-y-4 pb-8">
      <p className="text-xs text-slate-600">Click column headers to sort. Category stats toggle between totals, per-week averages, and league ranks.</p>

      {/* Category view toggle */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">Category stats:</span>
        {(['totals', 'avg', 'ranks'] as CatView[]).map(v => (
          <button
            key={v}
            type="button"
            onClick={() => setCatView(v)}
            className={`rounded px-2 py-0.5 text-xs font-medium transition ${
              catView === v ? 'bg-red-600/20 text-red-300' : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            {v === 'totals' ? 'Totals' : v === 'avg' ? 'Per-Week Avg' : 'Ranks'}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-xl border border-slate-700/60">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="border-b border-slate-700">
              {/* Overview */}
              <th className="sticky left-0 z-10 bg-slate-900 px-2 py-1.5 text-left text-[11px] font-medium text-slate-400">#</th>
              <th className="sticky left-[32px] z-10 bg-slate-900 px-2 py-1.5 text-left text-[11px] font-medium text-slate-300">Team</th>
              <Th col="wins">W</Th>
              <Th col="losses">L</Th>
              <Th col="winPct">Win%</Th>
              <th className="px-2 py-1.5 text-left text-[11px] font-medium text-slate-400">Playoffs</th>
              {/* Category Stats */}
              {CATS.map(c => <Th key={c} col={c}>{c}</Th>)}
              {/* Advanced */}
              <Th col="allplayPct">All-Play%</Th>
              <Th col="luckRatio">Luck</Th>
              <Th col="powerRank">PR</Th>
              <Th col="movement">±</Th>
              {/* Activity */}
              <Th col="transactions">Moves</Th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => {
              const wins = Math.round(Number(r.wins ?? 0))
              const losses = Math.round(Number(r.losses ?? 0))
              const wp = Number(r.win_pct ?? 0)
              const rankCh = Number((r._rank as JsonRecord).rank_change ?? 0)
              const inP = r.in_playoffs === true
              const stats = r._stats as JsonRecord
              const pr = r._rank as JsonRecord
              return (
                <tr key={i} className="border-b border-slate-800/50 hover:bg-slate-800/30">
                  <td className="sticky left-0 z-10 bg-slate-900 px-2 py-2 tabular-nums text-slate-400">{r.standing ?? '—'}</td>
                  <td className="sticky left-[32px] z-10 bg-slate-900 px-2 py-2 font-medium text-white">
                    <div className="flex items-center gap-1.5">
                      {inP ? <span className="text-[10px] text-amber-400">★</span> : null}
                      {String(r.team_name ?? r.team ?? '')}
                    </div>
                  </td>
                  <td className="px-2 py-2 tabular-nums text-slate-300">{wins}</td>
                  <td className="px-2 py-2 tabular-nums text-slate-300">{losses}</td>
                  <td className="px-2 py-2 tabular-nums text-slate-300">{wp.toFixed(1)}%</td>
                  <td className="px-2 py-2 text-slate-500">{inP ? 'In' : '—'}</td>
                  {CATS.map(c => (
                    <td key={c} className="px-2 py-2 tabular-nums text-slate-300">
                      {catVal(stats, c, catView, weeksPlayed)}
                    </td>
                  ))}
                  <td className="px-2 py-2 tabular-nums text-slate-300">
                    {Number(pr.allplay_win_pct ?? 0).toFixed(1)}%
                  </td>
                  <td className="px-2 py-2 tabular-nums text-slate-300">
                    {Number(pr['Win % Ratio'] ?? 0).toFixed(2)}
                  </td>
                  <td className="px-2 py-2 tabular-nums text-slate-300">
                    {String(pr.rank ?? '—')}
                  </td>
                  <td className="px-2 py-2 tabular-nums">
                    {rankCh > 0 ? (
                      <span className="text-emerald-400">▲{rankCh}</span>
                    ) : rankCh < 0 ? (
                      <span className="text-red-400">▼{Math.abs(rankCh)}</span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="px-2 py-2 tabular-nums text-slate-300">
                    {txnCounts[r._tn as string] ?? 0}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
