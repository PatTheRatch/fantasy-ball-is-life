import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getSnapshot, type JsonRecord } from '../api'
import {
  StateBlock,
  inferStateBlock,
  TableRoot,
  TableHead,
  TableBody,
  SortableTh,
  Th,
  Td,
  Tr,
  MovementBadge,
} from '../ui'

/* ── helpers ─────────────────────────────────────────────────────── */

function norm(s: string) {
  return (s ?? '').trim().toLowerCase()
}

const CATS = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'FG%', 'FT%', 'TO'] as const

function catRankKey(c: string) {
  return c.toLowerCase().replace('%', '_pct') + '_rank'
}

type CatView = 'totals' | 'avg' | 'ranks'

function catVal(
  stats: Record<string, unknown>,
  cat: string,
  view: CatView,
  weeks: number,
): string {
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
  const val = isTO ? Math.abs(v) : v
  if (isPct) return val.toFixed(3)
  return String(Math.round(val))
}

import type { SortDir } from '../ui'

type SortKey = { col: string; dir: SortDir }

/* ── main component ──────────────────────────────────────────────── */

export function StandingsTab({
  slug,
  season,
  week,
}: {
  slug: string
  season: number
  week: number
}) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['recap', 'snapshot', slug, season, week],
    queryFn: () => getSnapshot(slug, season, week),
    retry: false,
  })

  const [catView, setCatView] = useState<CatView>('totals')
  const [sort, setSort] = useState<SortKey>({ col: 'rank', dir: 'asc' })

  // All hooks before early returns
  const snap = data?.snapshot as Record<string, unknown> | undefined
  const standings = (snap?.standings ?? []) as Record<string, unknown>[]
  const stats = (snap?.season_stats ?? []) as Record<string, unknown>[]
  const rankings = (snap?.power_rankings ?? []) as Record<string, unknown>[]

  const txnCounts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const t of (snap?.transactions ?? []) as Record<string, unknown>[]) {
      if (t.action_type !== 'ADD') continue
      const tn = norm(String(t.team_name ?? ''))
      if (tn) m[tn] = (m[tn] || 0) + 1
    }
    return m
  }, [snap?.transactions])

  const tradeCounts = useMemo(() => {
    const m: Record<string, number> = {}
    for (const t of (snap?.transactions ?? []) as Record<string, unknown>[]) {
      if (t.action_type !== 'TRADE') continue
      const tn = norm(String(t.team_name ?? ''))
      if (tn) m[tn] = (m[tn] || 0) + 1
    }
    return m
  }, [snap?.transactions])

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

  const sorted: Record<string, unknown>[] = useMemo(() => {
    const dir = sort.dir === 'asc' ? 1 : -1
    const get = (r: Record<string, unknown>, col: string): number => {
      const st = r._stats as JsonRecord
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
      if (col === 'trades') return tradeCounts[r._tn as string] ?? 0
      return Number(st[col] ?? 0)
    }
    return [...rows].sort((a, b) => {
      const va = get(a, sort.col)
      const vb = get(b, sort.col)
      return (va - vb) * dir
    })
  }, [rows, sort, txnCounts, tradeCounts])

  const weeksPlayed = Math.max(Number(snap?.week ?? week), 1)

  const handleSort = (col: string) => {
    setSort((s) =>
      s.col === col
        ? { col, dir: s.dir === 'asc' ? 'desc' : 'asc' }
        : { col, dir: 'desc' },
    )
  }

  // ── State block rendering ──────────────────────────────────────

  const stateBlock = inferStateBlock({
    isLoading,
    isError,
    error,
    data: snap,
    isEmpty: (d) => !d || (Array.isArray((d as Record<string, unknown>)?.standings) && ((d as Record<string, unknown>).standings as unknown[]).length === 0),
  })

  if (stateBlock.show) {
    return <StateBlock {...stateBlock} />
  }

  // ── Render ──────────────────────────────────────────────────────

  return (
    <div className="space-y-4 pb-8">
      <p className="text-xs text-slate-500">
        Click column headers to sort. Category stats toggle between totals, per-week averages, and league ranks.
      </p>

      {/* Category view toggle */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500">Category stats:</span>
        {(['totals', 'avg', 'ranks'] as CatView[]).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setCatView(v)}
            className={`rounded-md px-2 py-0.5 text-xs font-medium transition ${
              catView === v
                ? 'bg-pg-accent/20 text-red-300'
                : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            {v === 'totals' ? 'Totals' : v === 'avg' ? 'Per-Week Avg' : 'Ranks'}
          </button>
        ))}
      </div>

      <TableRoot variant="dense">
        <TableHead>
          <Th sticky stickyLeft="0px" className="text-left">#</Th>
          <Th sticky stickyLeft="32px" className="text-left text-slate-300">Team</Th>
          <SortableTh col="wins" sort={sort} onSort={handleSort}>W</SortableTh>
          <SortableTh col="losses" sort={sort} onSort={handleSort}>L</SortableTh>
          <SortableTh col="winPct" sort={sort} onSort={handleSort}>Win%</SortableTh>
          <Th>Playoffs</Th>
          {CATS.map((c) => (
            <SortableTh key={c} col={c} sort={sort} onSort={handleSort}>{c}</SortableTh>
          ))}
          <SortableTh col="allplayPct" sort={sort} onSort={handleSort}>All-Play%</SortableTh>
          <SortableTh col="luckRatio" sort={sort} onSort={handleSort}>Luck</SortableTh>
          <SortableTh col="powerRank" sort={sort} onSort={handleSort}>PR</SortableTh>
          <SortableTh col="movement" sort={sort} onSort={handleSort}>±</SortableTh>
          <SortableTh col="transactions" sort={sort} onSort={handleSort}>Moves</SortableTh>
          <SortableTh col="trades" sort={sort} onSort={handleSort}>Trades</SortableTh>
        </TableHead>
        <TableBody>
          {sorted.map((r, i) => {
            const wins = Math.round(Number(r.wins ?? 0))
            const losses = Math.round(Number(r.losses ?? 0))
            const wp = Number(r.win_pct ?? 0)
            const rankCh = Number((r._rank as JsonRecord).rank_change ?? 0)
            const inP = r.in_playoffs === true
            const st = r._stats as JsonRecord
            const pr = r._rank as JsonRecord
            return (
              <Tr key={i}>
                <Td sticky stickyLeft="0px" className="text-slate-400">
                  {String(r.standing ?? '—')}
                </Td>
                <Td sticky stickyLeft="32px" className="font-medium text-white">
                  <div className="flex items-center gap-1.5">
                    {inP && <span className="text-[10px] text-amber-400">★</span>}
                    {String(r.team_name ?? r.team ?? '')}
                  </div>
                </Td>
                <Td>{wins}</Td>
                <Td>{losses}</Td>
                <Td>{wp.toFixed(1)}%</Td>
                <Td className="text-slate-500">{inP ? 'In' : '—'}</Td>
                {CATS.map((c) => (
                  <Td key={c}>{catVal(st, c, catView, weeksPlayed)}</Td>
                ))}
                <Td>{Number(pr.allplay_win_pct ?? 0).toFixed(1)}%</Td>
                <Td>{Number(pr['Win % Ratio'] ?? 0).toFixed(2)}</Td>
                <Td>{String(pr.rank ?? '—')}</Td>
                <Td>
                  <MovementBadge change={rankCh} />
                </Td>
                <Td>{txnCounts[r._tn as string] ?? 0}</Td>
                <Td>{tradeCounts[r._tn as string] ?? 0}</Td>
              </Tr>
            )
          })}
        </TableBody>
      </TableRoot>
    </div>
  )
}
