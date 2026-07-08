import { useQuery } from '@tanstack/react-query'
import { ChevronDown, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { JsonRecord } from '../api'
import {
  formatApiError,
  getLeagueSettings,
  getLeagueStandings,
  getPowerRankings,
  getScoreboardCurrent,
  getTransactions,
  postLeagueRecap,
} from '../api'
import { AiCommentaryCard } from '../components/AiCommentaryCard'
import {
  enrichCurrentRows,
  formatStatValue,
  pillClass,
  prepareMatchupGroups,
  rankPillClass,
  rankPillEntries,
  currentRecord,
} from '../lib/inSeasonUtils'
import {
  MATCHUP_WEEKS_2025_26,
  WEEK_MAX,
  WEEK_MIN,
} from '../lib/matchupWeeks'

const ESPN_RED = '#e03131'
const STICKY_TOP = '60px'
const CACHE_STORAGE_KEY = 'pg-recap-cache-v1'

type WeekRecapBundle = {
  standings: JsonRecord[]
  powerRankings: JsonRecord[]
  transactions: JsonRecord[]
  scoreboard: JsonRecord[]
  weekDates: { start: string; end: string }
  recap: string
}

function loadCacheFromStorage(): Record<number, WeekRecapBundle> {
  if (typeof sessionStorage === 'undefined') return {}
  try {
    const raw = sessionStorage.getItem(CACHE_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, unknown>
    const out: Record<number, WeekRecapBundle> = {}
    for (const [k, v] of Object.entries(parsed)) {
      const w = Number(k)
      if (Number.isFinite(w) && v && typeof v === 'object') {
        out[w] = v as WeekRecapBundle
      }
    }
    return out
  } catch {
    return {}
  }
}

function persistCache(cache: Record<number, WeekRecapBundle>) {
  try {
    sessionStorage.setItem(CACHE_STORAGE_KEY, JSON.stringify(cache))
  } catch {
    /* ignore quota */
  }
}

function buildWeeksCsv(n: number): string {
  return Array.from({ length: n }, (_, i) => String(i + 1)).join(',')
}

function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-md bg-slate-700/50 ${className}`}
      aria-hidden
    />
  )
}

function RecapMatchupStatTable({ stats }: { stats: JsonRecord[] }) {
  const rows = enrichCurrentRows(stats)
  return (
    <div className="overflow-x-hidden rounded-lg border border-slate-700/60">
      <table className="w-full table-fixed text-left text-xs">
        <thead>
          <tr className="border-b border-slate-700/60 text-slate-400">
            <th className="w-[28%] px-2 py-2 font-medium">Stat</th>
            <th className="w-[36%] px-2 py-2 font-medium">Home</th>
            <th className="w-[36%] px-2 py-2 font-medium">Away</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const stat = String(r.stat)
            const hr = String((r as JsonRecord)._home_res ?? '').toUpperCase()
            const ar = String((r as JsonRecord)._away_res ?? '').toUpperCase()
            return (
              <tr
                key={stat}
                className="border-b border-slate-800/80 last:border-0"
              >
                <td className="px-2 py-2 font-medium text-slate-200">{stat}</td>
                <td className="px-2 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="tabular-nums text-slate-100">
                      {formatStatValue(stat, r.current_home_score)}
                    </span>
                    <span
                      className={`inline-flex min-h-[22px] min-w-[22px] items-center justify-center rounded-full px-1.5 text-[10px] font-bold text-white ${pillClass(hr)}`}
                    >
                      {hr}
                    </span>
                  </div>
                </td>
                <td className="px-2 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="tabular-nums text-slate-100">
                      {formatStatValue(stat, r.current_away_score)}
                    </span>
                    <span
                      className={`inline-flex min-h-[22px] min-w-[22px] items-center justify-center rounded-full px-1.5 text-[10px] font-bold text-white ${pillClass(ar)}`}
                    >
                      {ar}
                    </span>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

type TxLine = { team: string; kind: 'Added' | 'Dropped' | 'Traded'; player: string }

function normalizePlayerList(v: unknown): string[] {
  if (v == null) return []
  if (Array.isArray(v)) return v.map((x) => String(x)).filter(Boolean)
  if (typeof v === 'string') return v ? [v] : []
  return []
}

function flattenTransactions(rows: JsonRecord[]): TxLine[] {
  const lines: TxLine[] = []
  for (const r of rows) {
    const team = String(r.team_name ?? '')
    const adds = normalizePlayerList(r.added_players)
    const drops = normalizePlayerList(r.dropped_players)
    const isTrade = adds.length > 0 && drops.length > 0
    if (isTrade) {
      for (const p of [...adds, ...drops]) {
        lines.push({ team, kind: 'Traded', player: p })
      }
    } else {
      for (const p of adds) lines.push({ team, kind: 'Added', player: p })
      for (const p of drops) lines.push({ team, kind: 'Dropped', player: p })
    }
  }
  return lines
}

function groupByTeam<T extends { team: string }>(items: T[]): Map<string, T[]> {
  const m = new Map<string, T[]>()
  for (const it of items) {
    const t = it.team || '—'
    if (!m.has(t)) m.set(t, [])
    m.get(t)!.push(it)
  }
  return m
}

export function Recap() {
  const settingsQuery = useQuery({
    queryKey: ['league', 'settings'],
    queryFn: getLeagueSettings,
  })

  const [week, setWeek] = useState(1)
  const [sheetOpen, setSheetOpen] = useState(false)
  const [cache, setCache] = useState<Record<number, WeekRecapBundle>>(() =>
    loadCacheFromStorage(),
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [fadeOpacity, setFadeOpacity] = useState(1)
  const sheetTouchStartY = useRef(0)

  const initializedWeek = useRef(false)
  useEffect(() => {
    if (!settingsQuery.isSuccess || !settingsQuery.data) return
    if (initializedWeek.current) return
    initializedWeek.current = true
    const cw = Math.max(
      1,
      Number(settingsQuery.data.current_week ?? 1) || 1,
    )
    setWeek(Math.min(WEEK_MAX, Math.max(WEEK_MIN, cw - 1)))
  }, [settingsQuery.isSuccess, settingsQuery.data])

  const bumpWeek = useCallback((d: number) => {
    setWeek((w) => Math.min(WEEK_MAX, Math.max(WEEK_MIN, w + d)))
  }, [])

  const weekMeta = MATCHUP_WEEKS_2025_26[week]

  const bundle = cache[week]

  const matchupGroups = useMemo(() => {
    if (!bundle?.scoreboard?.length) return []
    // Must enrich before grouping so currentRecord() sees _home_res / _away_res (same as InSeason).
    return prepareMatchupGroups(enrichCurrentRows(bundle.scoreboard))
  }, [bundle?.scoreboard])

  const txLines = useMemo(
    () => (bundle ? flattenTransactions(bundle.transactions) : []),
    [bundle],
  )

  const txByTeam = useMemo(() => groupByTeam(txLines), [txLines])

  const [open, setOpen] = useState([false, false, false])
  const toggle = (i: number) => {
    setOpen((prev) => {
      const n = [...prev]
      n[i] = !n[i]
      return n
    })
  }

  const [expandedMatchup, setExpandedMatchup] = useState<string | null>(null)
  const [expandedPowerTeam, setExpandedPowerTeam] = useState<string | null>(null)

  const runGenerate = useCallback(async () => {
    const w = week
    if (!weekMeta?.start || !weekMeta?.end) {
      setError('Week dates are not configured for this week.')
      return
    }
    setError(null)
    setLoading(true)
    setFadeOpacity(0)
    const settings = settingsQuery.data
    if (!settings) {
      setError('League settings not loaded.')
      setLoading(false)
      setFadeOpacity(1)
      return
    }
    try {
      const weeksParam = buildWeeksCsv(w)
      const [standings, powerRankings, transactions, scoreboard] =
        await Promise.all([
          getLeagueStandings(),
          getPowerRankings(weeksParam, 3),
          getTransactions(weekMeta.start, weekMeta.end),
          getScoreboardCurrent(w),
        ])

      const recapRes = await postLeagueRecap({
        week: w,
        league_settings: settings as unknown as JsonRecord,
        standings,
        power_rankings: powerRankings,
        transactions,
        scoreboard,
        week_dates: { start: weekMeta.start, end: weekMeta.end },
      })

      const next: WeekRecapBundle = {
        standings,
        powerRankings,
        transactions,
        scoreboard,
        weekDates: { start: weekMeta.start, end: weekMeta.end },
        recap: recapRes.recap,
      }
      setCache((prev) => {
        const merged = { ...prev, [w]: next }
        persistCache(merged)
        return merged
      })
    } catch (e) {
      setError(formatApiError(e))
    } finally {
      setLoading(false)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setFadeOpacity(1))
      })
    }
  }, [week, weekMeta, settingsQuery.data])

  const onRefresh = () => {
    setCache((prev) => {
      const next = { ...prev }
      delete next[week]
      persistCache(next)
      return next
    })
    void runGenerate()
  }

  useEffect(() => {
    if (!sheetOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSheetOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [sheetOpen])

  useEffect(() => {
    if (!sheetOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [sheetOpen])

  useEffect(() => {
    setExpandedMatchup(null)
    setExpandedPowerTeam(null)
  }, [week])

  const hasCachedWeek = Boolean(cache[week]?.recap)

  return (
    <div className="space-y-4 overflow-x-hidden pb-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight text-white md:text-3xl">
            Weekly Recap
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            AI newsletter, week results, power ranks, and transactions for the
            week you choose.
          </p>
        </div>
        <button
          type="button"
          onClick={() => onRefresh()}
          disabled={loading}
          className="mt-1 flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-slate-600 bg-slate-800/80 text-slate-200 disabled:opacity-50"
          aria-label="Refresh recap for this week"
        >
          <RefreshCw className="h-4 w-4" strokeWidth={2} />
        </button>
      </div>

      {settingsQuery.isLoading && (
        <Skeleton className="h-11 w-full max-w-md rounded-full" />
      )}
      {settingsQuery.isError && (
        <p className="text-sm text-red-400">
          {formatApiError(settingsQuery.error)}
        </p>
      )}

      <button
        type="button"
        onClick={() => setSheetOpen(true)}
        className="flex min-h-[44px] w-full max-w-md items-center justify-center gap-2 rounded-full border border-slate-700 bg-slate-900/80 px-4 py-2.5 text-sm font-medium text-slate-100 shadow-sm"
        aria-haspopup="dialog"
        aria-expanded={sheetOpen}
      >
        <span className="truncate">Week {week}</span>
        <span className="shrink-0 text-base leading-none" aria-hidden>
          ⚙️
        </span>
      </button>

      {sheetOpen && (
        <div className="fixed inset-0 z-[60] flex items-end justify-center md:items-center md:justify-center md:p-4">
          <button
            type="button"
            tabIndex={-1}
            className="absolute inset-0 bg-black/55 backdrop-blur-[2px]"
            aria-label="Close week picker"
            onClick={() => setSheetOpen(false)}
          />
          <div
            role="dialog"
            aria-modal="true"
            className="relative z-10 flex max-h-[min(90dvh,560px)] w-full max-w-lg flex-col rounded-t-2xl border border-slate-700 bg-slate-900 shadow-2xl md:max-h-[85vh] md:rounded-2xl"
            style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
            onTouchStart={(e) => {
              sheetTouchStartY.current = e.touches[0].clientY
            }}
            onTouchEnd={(e) => {
              const y = e.changedTouches[0].clientY
              if (y - sheetTouchStartY.current > 72) setSheetOpen(false)
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex shrink-0 cursor-grab justify-center pt-3 pb-1 active:cursor-grabbing">
              <div className="h-1.5 w-12 rounded-full bg-slate-600" aria-hidden />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
              <h2 className="mb-4 text-center text-base font-semibold text-white">
                Select week
              </h2>
              <div className="flex min-h-[44px] items-center justify-center gap-2">
                <button
                  type="button"
                  onClick={() => bumpWeek(-1)}
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-slate-700 bg-slate-950 text-lg text-slate-200"
                  aria-label="Previous week"
                >
                  ‹
                </button>
                <span className="min-w-[4.5rem] text-center text-sm font-semibold tabular-nums text-white">
                  Week {week}
                </span>
                <button
                  type="button"
                  onClick={() => bumpWeek(1)}
                  className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg border border-slate-700 bg-slate-950 text-lg text-slate-200"
                  aria-label="Next week"
                >
                  ›
                </button>
              </div>
              <div className="mt-4 grid max-h-[40vh] grid-cols-4 gap-2 overflow-y-auto sm:grid-cols-6">
                {Array.from({ length: WEEK_MAX }, (_, i) => i + 1).map((w) => (
                  <button
                    key={w}
                    type="button"
                    onClick={() => {
                      setWeek(w)
                      setSheetOpen(false)
                    }}
                    className={`min-h-[40px] rounded-lg border text-sm font-semibold ${
                      w === week
                        ? 'border-transparent text-white'
                        : 'border-slate-700 text-slate-300 hover:bg-slate-800/80'
                    }`}
                    style={
                      w === week ? { backgroundColor: ESPN_RED } : undefined
                    }
                  >
                    {w}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setSheetOpen(false)}
                className="mt-6 w-full min-h-[44px] rounded-lg border border-slate-600 bg-slate-800 py-2.5 text-sm font-semibold text-white"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      <button
        type="button"
        onClick={() => void runGenerate()}
        disabled={loading || !settingsQuery.isSuccess}
        className="min-h-[44px] w-full max-w-md rounded-lg px-4 text-sm font-semibold text-white disabled:opacity-50"
        style={{ backgroundColor: ESPN_RED }}
      >
        {loading ? 'Working…' : hasCachedWeek ? 'Regenerate Recap' : 'Generate Recap'}
      </button>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {loading && (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full rounded-xl" />
          <Skeleton className="h-20 w-full rounded-xl" />
          <Skeleton className="h-20 w-full rounded-xl" />
          <Skeleton className="h-20 w-full rounded-xl" />
        </div>
      )}

      <div
        className="space-y-4 transition-opacity duration-150 ease-out"
        style={{ opacity: fadeOpacity }}
      >
        {bundle?.recap && !loading && (
          <AiCommentaryCard text={bundle.recap} />
        )}

        {bundle && !loading && (
          <>
            <section className="border-t border-slate-800/80 pt-4">
              <button
                type="button"
                onClick={() => toggle(0)}
                className="sticky z-30 -mx-4 flex w-full items-center justify-between gap-2 border-b border-slate-800/80 bg-slate-950/95 px-4 py-2 text-left backdrop-blur-sm md:mx-0 md:px-0"
                style={{ top: STICKY_TOP }}
                aria-expanded={open[0]}
              >
                <h2 className="text-lg font-semibold text-white">
                  📋 Week Results
                </h2>
                <ChevronDown
                  className={`h-5 w-5 shrink-0 text-slate-400 transition-transform duration-200 ${
                    open[0] ? 'rotate-180' : ''
                  }`}
                  aria-hidden
                />
              </button>
              {open[0] && (
                <div className="mt-3 space-y-2">
                  {matchupGroups.map((g) => {
                    const rec = currentRecord(g.stats)
                    const scoreStr = `${rec.home}-${rec.away}`
                    const homeWins = rec.home > rec.away
                    const awayWins = rec.away > rec.home
                    const winner =
                      homeWins && !awayWins
                        ? g.home
                        : awayWins && !homeWins
                          ? g.away
                          : 'Tie'
                    const expanded = expandedMatchup === g.key
                    return (
                      <div
                        key={g.key}
                        className="rounded-xl border border-slate-800 bg-slate-950/40"
                      >
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedMatchup(expanded ? null : g.key)
                          }
                          className="flex w-full min-h-[44px] flex-col gap-1 px-3 py-2 text-left sm:flex-row sm:items-center sm:justify-between"
                        >
                          <div className="min-w-0">
                            <span className="truncate font-medium text-slate-100">
                              {g.home} <span className="text-slate-500">vs</span>{' '}
                              {g.away}
                            </span>
                            <div className="text-xs text-slate-500">
                              {scoreStr}
                            </div>
                          </div>
                          <span
                            className={`shrink-0 text-sm font-semibold ${
                              winner === 'Tie'
                                ? 'text-slate-400'
                                : 'text-emerald-400'
                            }`}
                          >
                            {winner === 'Tie' ? 'Tie' : `${winner} wins`}
                          </span>
                        </button>
                        {expanded && (
                          <div className="border-t border-slate-800 px-3 py-2">
                            <RecapMatchupStatTable stats={g.stats} />
                          </div>
                        )}
                      </div>
                    )
                  })}
                  {matchupGroups.length === 0 && (
                    <p className="text-sm text-slate-500">
                      No scoreboard rows for this week.
                    </p>
                  )}
                </div>
              )}
            </section>

            <section className="border-t border-slate-800/80 pt-4">
              <button
                type="button"
                onClick={() => toggle(1)}
                className="sticky z-30 -mx-4 flex w-full items-center justify-between gap-2 border-b border-slate-800/80 bg-slate-950/95 px-4 py-2 text-left backdrop-blur-sm md:mx-0 md:px-0"
                style={{ top: STICKY_TOP }}
                aria-expanded={open[1]}
              >
                <h2 className="text-lg font-semibold text-white">
                  📈 Power Rankings
                </h2>
                <ChevronDown
                  className={`h-5 w-5 shrink-0 text-slate-400 transition-transform duration-200 ${
                    open[1] ? 'rotate-180' : ''
                  }`}
                  aria-hidden
                />
              </button>
              {open[1] && (
                <div className="mt-3 space-y-2">
                  {(bundle.powerRankings ?? []).map((row) => {
                    const team = String(row.team ?? '')
                    const rank = Number(row.rank)
                    const comp = Number(row.composite_score)
                    const ch = Number(row.rank_change ?? 0)
                    const expanded = expandedPowerTeam === team
                    const pills = rankPillEntries(row)
                    return (
                      <div
                        key={team}
                        className="rounded-xl border border-slate-800 bg-slate-950/40"
                      >
                        <button
                          type="button"
                          onClick={() =>
                            setExpandedPowerTeam(expanded ? null : team)
                          }
                          className="flex min-h-[44px] w-full items-center gap-3 px-3 py-2 text-left"
                        >
                          <span className="w-8 text-2xl font-bold tabular-nums text-white">
                            {rank}
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="truncate font-medium text-slate-100">
                              {team}
                            </div>
                            <div className="text-xs text-slate-500">
                              Composite{' '}
                              <span className="tabular-nums text-slate-300">
                                {Number.isFinite(comp) ? comp.toFixed(3) : '—'}
                              </span>
                            </div>
                          </div>
                          <span
                            className={`shrink-0 text-sm font-semibold ${
                              ch > 0
                                ? 'text-emerald-400'
                                : ch < 0
                                  ? 'text-red-400'
                                  : 'text-slate-500'
                            }`}
                          >
                            {ch > 0
                              ? `▲${ch}`
                              : ch < 0
                                ? `▼${Math.abs(ch)}`
                                : '—'}
                          </span>
                        </button>
                        {expanded && pills.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 border-t border-slate-800 px-3 py-2">
                            {pills.map((p) => (
                              <span
                                key={p.label}
                                className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${rankPillClass(p.rank)}`}
                              >
                                {p.label} #{p.rank}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    )
                  })}
                  {(!bundle.powerRankings || bundle.powerRankings.length === 0) && (
                    <p className="text-sm text-slate-500">
                      No power rankings for this window.
                    </p>
                  )}
                </div>
              )}
            </section>

            <section className="border-t border-slate-800/80 pt-4">
              <button
                type="button"
                onClick={() => toggle(2)}
                className="sticky z-30 -mx-4 flex w-full items-center justify-between gap-2 border-b border-slate-800/80 bg-slate-950/95 px-4 py-2 text-left backdrop-blur-sm md:mx-0 md:px-0"
                style={{ top: STICKY_TOP }}
                aria-expanded={open[2]}
              >
                <h2 className="text-lg font-semibold text-white">
                  🔄 Transactions
                </h2>
                <ChevronDown
                  className={`h-5 w-5 shrink-0 text-slate-400 transition-transform duration-200 ${
                    open[2] ? 'rotate-180' : ''
                  }`}
                  aria-hidden
                />
              </button>
              {open[2] && (
                <div className="mt-3 space-y-4">
                  {Array.from(txByTeam.entries())
                    .sort((a, b) => a[0].localeCompare(b[0]))
                    .map(([team, lines]) => (
                    <div key={team}>
                      <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                        {team}
                      </div>
                      <ul className="space-y-2">
                        {lines.map((line, idx) => (
                          <li
                            key={`${team}-${idx}-${line.player}`}
                            className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-800 bg-slate-950/30 px-3 py-2 text-sm"
                          >
                            <span
                              className={`rounded px-2 py-0.5 text-[11px] font-bold uppercase ${
                                line.kind === 'Added'
                                  ? 'bg-emerald-500/20 text-emerald-400'
                                  : line.kind === 'Dropped'
                                    ? 'bg-red-500/20 text-red-400'
                                    : 'bg-amber-500/20 text-amber-300'
                              }`}
                            >
                              {line.kind}
                            </span>
                            <span className="text-slate-200">{line.player}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                  {txLines.length === 0 && (
                    <p className="text-sm text-slate-500">
                      No transactions in this date range.
                    </p>
                  )}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  )
}
