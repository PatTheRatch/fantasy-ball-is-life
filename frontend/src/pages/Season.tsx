import { useMutation, useQuery } from '@tanstack/react-query'
import { ChevronDown } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type { JsonRecord } from '../api'
import {
  formatApiError,
  getLeagueSettings,
  getSeasonStats,
  postSeasonCommentary,
} from '../api'
import { AiCommentaryCard } from '../components/AiCommentaryCard'
import { WEEK_MAX, WEEK_MIN } from '../lib/matchupWeeks'

const ESPN_RED = '#e03131'
const STICKY_TOP = '60px'

const STAT_LEADER_COLS = [
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

function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-md bg-slate-700/50 ${className}`}
      aria-hidden
    />
  )
}

function num(r: JsonRecord, key: string): number {
  const v = r[key]
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : NaN
}

function str(r: JsonRecord, key: string): string {
  return String(r[key] ?? '')
}

function formatPctCell(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  const pct = n > 0 && n <= 1 ? n * 100 : n
  return `${pct.toFixed(1)}%`
}

function formatToCell(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return Math.abs(n).toFixed(1)
}

function formatStatCell(col: string, v: unknown): string {
  if (col === 'FG%' || col === 'FT%') return formatPctCell(v)
  if (col === 'TO') return formatToCell(v)
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n % 1 === 0 ? String(Math.round(n)) : n.toFixed(1)
}

function buildWeekList(from: number, to: number): number[] {
  const lo = Math.min(from, to)
  const hi = Math.max(from, to)
  const out: number[] = []
  for (let w = lo; w <= hi; w += 1) out.push(w)
  return out
}

function seasonPhaseBanner(
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

function luckLabel(ratio: number): { emoji: string; text: string } {
  if (ratio >= 1.15) return { emoji: '🍀', text: 'Very Lucky' }
  if (ratio >= 1.0) return { emoji: '😊', text: 'Slightly Lucky' }
  if (ratio >= 0.85) return { emoji: '😤', text: 'Slightly Unlucky' }
  return { emoji: '💀', text: 'Very Unlucky' }
}

type Medal = 'gold' | 'silver' | 'bronze' | null

function medalClass(m: Medal): string {
  if (m === 'gold') return 'bg-amber-500/15'
  if (m === 'silver') return 'bg-slate-400/15'
  if (m === 'bronze') return 'bg-amber-800/25'
  return ''
}

function computeColumnMedals(
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

export function Season() {
  const settingsQuery = useQuery({
    queryKey: ['league', 'settings'],
    queryFn: getLeagueSettings,
  })

  const settings = settingsQuery.data
  const currentWeek = Math.max(
    1,
    Number(settings?.current_week ?? WEEK_MAX) || 1,
  )
  const regSeasonCount = Math.max(
    1,
    Number(settings?.reg_season_count ?? 19) || 19,
  )
  const playoffTeamCount = Math.max(
    0,
    Number(settings?.playoff_team_count ?? 0) || 0,
  )

  const [fromWeek, setFromWeek] = useState(1)
  const [toWeek, setToWeek] = useState(1)
  const [rangeError, setRangeError] = useState<string | null>(null)

  const settingsWeekInitialized = useRef(false)
  useEffect(() => {
    if (!settingsQuery.isSuccess || !settings) return
    if (settingsWeekInitialized.current) return
    settingsWeekInitialized.current = true
    const cw = Math.max(1, Number(settings.current_week ?? 1) || 1)
    setFromWeek(WEEK_MIN)
    setToWeek(Math.min(WEEK_MAX, cw))
  }, [settingsQuery.isSuccess, settings])

  const [seasonStats, setSeasonStats] = useState<JsonRecord[] | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)
  const [statsError, setStatsError] = useState<string | null>(null)
  const [statsFadeOpacity, setStatsFadeOpacity] = useState(1)

  const phase = useMemo(
    () => seasonPhaseBanner(currentWeek, regSeasonCount),
    [currentWeek, regSeasonCount],
  )

  const standingsRows = useMemo(() => {
    if (!seasonStats?.length) return []
    const rows = [...seasonStats]
    rows.sort((a, b) => num(b, 'Actual Win %') - num(a, 'Actual Win %'))
    return rows.map((r, idx) => ({
      row: r,
      rank: idx + 1,
      team: str(r, 'Team'),
      aw: num(r, 'Actual Win %'),
      w: Math.round(num(r, 'Actual Wins')),
      l: Math.round(num(r, 'Actual Losses')),
      t: Math.round(num(r, 'Actual Ties')),
    }))
  }, [seasonStats])

  const allPlayRows = useMemo(() => {
    if (!seasonStats?.length) return []
    const actualOrder = [...seasonStats].sort(
      (a, b) => num(b, 'Actual Win %') - num(a, 'Actual Win %'),
    )
    const actualRank = new Map<string, number>()
    actualOrder.forEach((r, i) => {
      actualRank.set(str(r, 'Team'), i + 1)
    })

    const sorted = [...seasonStats].sort(
      (a, b) => num(b, 'Total Win %') - num(a, 'Total Win %'),
    )

    return sorted.map((r, idx) => {
      const team = str(r, 'Team')
      const allPlayRank = idx + 1
      const ar = actualRank.get(team) ?? allPlayRank
      const diff = Math.abs(ar - allPlayRank)
      let badge: 'lucky' | 'unlucky' | null = null
      if (diff >= 3) {
        badge = ar < allPlayRank ? 'lucky' : 'unlucky'
      }
      return {
        row: r,
        rank: allPlayRank,
        team,
        aw: num(r, 'Actual Win %'),
        tw: num(r, 'Total Win %'),
        w: Math.round(num(r, 'Actual Wins')),
        l: Math.round(num(r, 'Actual Losses')),
        t: Math.round(num(r, 'Actual Ties')),
        badge,
      }
    })
  }, [seasonStats])

  const luckRows = useMemo(() => {
    if (!seasonStats?.length) return []
    const rows = [...seasonStats]
    rows.sort((a, b) => num(b, 'Win % Ratio') - num(a, 'Win % Ratio'))
    return rows.map((r) => ({
      team: str(r, 'Team'),
      ratio: num(r, 'Win % Ratio'),
    }))
  }, [seasonStats])

  const statMedals = useMemo(() => {
    if (!seasonStats?.length) return new Map<string, Map<string, Medal>>()
    const byTeamCol = new Map<string, Map<string, Medal>>()
    for (const col of STAT_LEADER_COLS) {
      if (!seasonStats.some((r) => col in r)) continue
      const colMedals = computeColumnMedals(seasonStats, col)
      for (const [team, medal] of colMedals) {
        if (!byTeamCol.has(team)) byTeamCol.set(team, new Map())
        byTeamCol.get(team)!.set(col, medal)
      }
    }
    return byTeamCol
  }, [seasonStats])

  const commentaryMut = useMutation({
    mutationFn: () => {
      if (!seasonStats?.length || !settings) {
        throw new Error('Load season stats first.')
      }
      const weekList = buildWeekList(fromWeek, toWeek)
      const lo = Math.min(...weekList)
      const hi = Math.max(...weekList)
      return postSeasonCommentary({
        season_stats: seasonStats,
        weeks: weekList,
        min_week: lo,
        max_week: hi,
        league_settings: settings as unknown as JsonRecord,
      })
    },
  })

  async function loadSeasonStats() {
    setRangeError(null)
    const lo = Math.min(fromWeek, toWeek)
    const hi = Math.max(fromWeek, toWeek)
    if (lo < WEEK_MIN || hi > WEEK_MAX) {
      setRangeError(`Weeks must be between ${WEEK_MIN} and ${WEEK_MAX}.`)
      return
    }
    const weeks = buildWeekList(lo, hi)
    const param = weeks.join(',')
    setStatsLoading(true)
    setStatsFadeOpacity(0)
    try {
      const data = await getSeasonStats(param)
      setSeasonStats(data)
      setStatsError(null)
    } catch (e) {
      setStatsError(formatApiError(e))
    } finally {
      setStatsLoading(false)
      requestAnimationFrame(() => {
        requestAnimationFrame(() => setStatsFadeOpacity(1))
      })
    }
  }

  const [open, setOpen] = useState([true, false, false, false])
  const toggle = (i: number) => {
    setOpen((prev) => {
      const next = [...prev]
      next[i] = !next[i]
      return next
    })
  }

  const teamCount = standingsRows.length

  return (
    <div className="space-y-4 pb-8">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white md:text-3xl">
          Season
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Standings, all-play, stat leaders, luck, and AI commentary for the
          weeks you choose.
        </p>
      </div>

      {settingsQuery.isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-9 w-full max-w-md rounded-full" />
        </div>
      )}
      {settingsQuery.isError && (
        <p className="text-sm text-red-400">
          {formatApiError(settingsQuery.error)}
        </p>
      )}
      {settings && (
        <div
          className="inline-flex max-w-full items-center rounded-full border border-slate-700/90 bg-slate-900/80 px-4 py-2 text-sm font-medium text-slate-100 shadow-sm"
          role="status"
        >
          <span className="mr-2 shrink-0" aria-hidden>
            {phase.emoji}
          </span>
          <span className="truncate">{phase.label}</span>
        </div>
      )}

      <div className="rounded-xl border border-slate-800 bg-slate-950/40 p-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Week range
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            From week
            <input
              type="number"
              min={WEEK_MIN}
              max={WEEK_MAX}
              value={fromWeek}
              onChange={(e) => setFromWeek(Number(e.target.value) || 1)}
              className="min-h-[44px] w-[88px] rounded-lg border border-slate-700 bg-slate-900 px-3 text-sm text-white"
            />
          </label>
          <label className="flex flex-col gap-1 text-xs text-slate-400">
            To week
            <input
              type="number"
              min={WEEK_MIN}
              max={WEEK_MAX}
              value={toWeek}
              onChange={(e) => setToWeek(Number(e.target.value) || 1)}
              className="min-h-[44px] w-[88px] rounded-lg border border-slate-700 bg-slate-900 px-3 text-sm text-white"
            />
          </label>
          <button
            type="button"
            onClick={() => void loadSeasonStats()}
            disabled={statsLoading}
            className="min-h-[44px] rounded-lg px-4 text-sm font-semibold text-white disabled:opacity-50"
            style={{ backgroundColor: ESPN_RED }}
          >
            {statsLoading ? 'Loading…' : 'Load Season Stats'}
          </button>
        </div>
        {rangeError && (
          <p className="mt-2 text-sm text-red-400">{rangeError}</p>
        )}
      </div>

      {statsError && (
        <p className="text-sm text-red-400">{statsError}</p>
      )}

      <div
        className="space-y-4 transition-opacity duration-150 ease-out"
        style={{ opacity: statsFadeOpacity }}
      >
        {/* Card 1 — Standings */}
        <section className="border-t border-slate-800/80 pt-4">
          <button
            type="button"
            onClick={() => toggle(0)}
            className="sticky z-30 -mx-4 flex w-full items-center justify-between gap-2 border-b border-slate-800/80 bg-slate-950/95 px-4 py-2 text-left backdrop-blur-sm md:mx-0 md:px-0"
            style={{ top: STICKY_TOP }}
            aria-expanded={open[0]}
          >
            <h2 className="text-lg font-semibold text-white">
              📊 Standings
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
              {statsLoading && (
                <>
                  <Skeleton className="h-14 w-full" />
                  <Skeleton className="h-14 w-full" />
                </>
              )}
              {!statsLoading &&
                standingsRows.map((s) => {
                  const isPlayoff =
                    playoffTeamCount > 0 && s.rank <= playoffTeamCount
                  const isBottom =
                    teamCount >= 2 && s.rank > teamCount - 2
                  let border = 'border-l-transparent'
                  if (isPlayoff) border = 'border-l-emerald-500/60'
                  else if (isBottom) border = 'border-l-red-500/60'
                  const pct = Number.isFinite(s.aw) ? Math.min(100, Math.max(0, s.aw)) : 0
                  return (
                    <div
                      key={s.team}
                      className={`rounded-xl border border-slate-800 border-l-[3px] bg-slate-950/40 pl-3 pr-3 py-2.5 ${border}`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="w-7 shrink-0 text-lg font-bold tabular-nums text-white">
                          {s.rank}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="truncate font-medium text-slate-100">
                              {s.team}
                            </span>
                            {isPlayoff && (
                              <span className="rounded bg-emerald-500/20 px-1.5 text-[10px] font-bold text-emerald-400">
                                P
                              </span>
                            )}
                            {!isPlayoff && playoffTeamCount > 0 && (
                              <span className="rounded bg-red-500/20 px-1.5 text-[10px] font-bold text-red-400">
                                E
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-slate-500">
                            {s.w}-{s.l}-{s.t}
                          </div>
                        </div>
                        <span className="shrink-0 text-xs tabular-nums text-slate-400">
                          {Number.isFinite(s.aw) ? `${s.aw.toFixed(1)}%` : '—'}
                        </span>
                      </div>
                      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                        <div
                          className="h-full rounded-full bg-pg-accent/80"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
              {!statsLoading && seasonStats && standingsRows.length === 0 && (
                <p className="text-sm text-slate-500">
                  Load season stats to see standings.
                </p>
              )}
            </div>
          )}
        </section>

        {/* Card 2 — All-Play */}
        <section className="border-t border-slate-800/80 pt-4">
          <button
            type="button"
            onClick={() => toggle(1)}
            className="sticky z-30 -mx-4 flex w-full items-center justify-between gap-2 border-b border-slate-800/80 bg-slate-950/95 px-4 py-2 text-left backdrop-blur-sm md:mx-0 md:px-0"
            style={{ top: STICKY_TOP }}
            aria-expanded={open[1]}
          >
            <h2 className="text-lg font-semibold text-white">
              🌐 All-Play Standings
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
              {!statsLoading &&
                allPlayRows.map((s) => {
                  const pct = Number.isFinite(s.aw)
                    ? Math.min(100, Math.max(0, s.aw))
                    : 0
                  return (
                    <div
                      key={s.team}
                      className="rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2.5"
                    >
                      <div className="flex items-center gap-2">
                        <span className="w-7 shrink-0 text-lg font-bold tabular-nums text-white">
                          {s.rank}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <span className="truncate font-medium text-slate-100">
                              {s.team}
                            </span>
                            {s.badge === 'lucky' && (
                              <span className="text-sm" title="Outperforming all-play rank">
                                🍀
                              </span>
                            )}
                            {s.badge === 'unlucky' && (
                              <span className="text-sm" title="Underperforming vs all-play rank">
                                😤
                              </span>
                            )}
                          </div>
                          <div className="text-xs text-slate-500">
                            All-play {Number.isFinite(s.tw) ? `${s.tw.toFixed(1)}%` : '—'}{' '}
                            · {s.w}-{s.l}-{s.t}
                          </div>
                        </div>
                        <span className="shrink-0 text-xs tabular-nums text-slate-400">
                          {Number.isFinite(s.aw) ? `${s.aw.toFixed(1)}%` : '—'}
                        </span>
                      </div>
                      <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                        <div
                          className="h-full rounded-full bg-sky-500/70"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                    </div>
                  )
                })}
              {!statsLoading && seasonStats && allPlayRows.length === 0 && (
                <p className="text-sm text-slate-500">
                  Load season stats for all-play standings.
                </p>
              )}
            </div>
          )}
        </section>

        {/* Card 3 — Stat Leaders */}
        <section className="border-t border-slate-800/80 pt-4">
          <button
            type="button"
            onClick={() => toggle(2)}
            className="sticky z-30 -mx-4 flex w-full items-center justify-between gap-2 border-b border-slate-800/80 bg-slate-950/95 px-4 py-2 text-left backdrop-blur-sm md:mx-0 md:px-0"
            style={{ top: STICKY_TOP }}
            aria-expanded={open[2]}
          >
            <h2 className="text-lg font-semibold text-white">
              🎯 Stat Leaders
            </h2>
            <ChevronDown
              className={`h-5 w-5 shrink-0 text-slate-400 transition-transform duration-200 ${
                open[2] ? 'rotate-180' : ''
              }`}
              aria-hidden
            />
          </button>
          {open[2] && (
            <div className="mt-3 -mx-1 overflow-x-auto pb-1">
              {!statsLoading && seasonStats && seasonStats.length > 0 && (
                <table className="w-max min-w-full border-separate border-spacing-0 text-left text-xs">
                  <thead>
                    <tr className="text-slate-500">
                      <th className="sticky left-0 z-10 bg-slate-950/95 px-2 py-2 font-semibold">
                        Team
                      </th>
                      {STAT_LEADER_COLS.map((col) =>
                        seasonStats.some((r) => col in r) ? (
                          <th
                            key={col}
                            className="whitespace-nowrap px-2 py-2 font-semibold"
                          >
                            {col}
                          </th>
                        ) : null,
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {seasonStats.map((r) => {
                      const team = str(r, 'Team')
                      const rowMedals = statMedals.get(team)
                      return (
                        <tr key={team} className="border-b border-slate-800/80">
                          <td className="sticky left-0 z-10 max-w-[140px] truncate bg-slate-950/95 px-2 py-2 font-medium text-slate-200">
                            {team}
                          </td>
                          {STAT_LEADER_COLS.map((col) => {
                            if (!seasonStats.some((x) => col in x)) return null
                            const medal = rowMedals?.get(col) ?? null
                            const cell = formatStatCell(col, r[col])
                            return (
                              <td
                                key={col}
                                className={`whitespace-nowrap px-2 py-2 tabular-nums text-slate-300 ${medalClass(medal)}`}
                              >
                                {cell}
                              </td>
                            )
                          })}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              )}
              {!statsLoading && (!seasonStats || seasonStats.length === 0) && (
                <p className="text-sm text-slate-500">
                  Load season stats to see category totals.
                </p>
              )}
            </div>
          )}
        </section>

        {/* Card 4 — Luck */}
        <section className="border-t border-slate-800/80 pt-4">
          <button
            type="button"
            onClick={() => toggle(3)}
            className="sticky z-30 -mx-4 flex w-full items-center justify-between gap-2 border-b border-slate-800/80 bg-slate-950/95 px-4 py-2 text-left backdrop-blur-sm md:mx-0 md:px-0"
            style={{ top: STICKY_TOP }}
            aria-expanded={open[3]}
          >
            <h2 className="text-lg font-semibold text-white">
              🍀 Luck Index
            </h2>
            <ChevronDown
              className={`h-5 w-5 shrink-0 text-slate-400 transition-transform duration-200 ${
                open[3] ? 'rotate-180' : ''
              }`}
              aria-hidden
            />
          </button>
          {open[3] && (
            <div className="mt-3 space-y-2">
              {!statsLoading &&
                luckRows.map((row) => {
                  const lbl = Number.isFinite(row.ratio)
                    ? luckLabel(row.ratio)
                    : { emoji: '—', text: '—' }
                  return (
                    <div
                      key={row.team}
                      className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2.5"
                    >
                      <span className="min-w-0 flex-1 truncate font-medium text-slate-100">
                        {row.team}
                      </span>
                      <span className="shrink-0 tabular-nums text-slate-300">
                        {Number.isFinite(row.ratio) ? row.ratio.toFixed(2) : '—'}
                      </span>
                      <span className="w-full text-right text-sm text-slate-400 sm:w-auto">
                        {lbl.emoji} {lbl.text}
                      </span>
                    </div>
                  )
                })}
              {!statsLoading && seasonStats && luckRows.length === 0 && (
                <p className="text-sm text-slate-500">
                  Load season stats for luck index.
                </p>
              )}
            </div>
          )}
        </section>
      </div>

      <section className="border-t border-slate-800/80 pt-4">
        <button
          type="button"
          onClick={() => commentaryMut.mutate()}
          disabled={
            commentaryMut.isPending || !seasonStats?.length || !settings
          }
          className="min-h-[44px] w-full rounded-lg border border-slate-600 bg-slate-800/80 py-2.5 text-sm font-medium text-white disabled:opacity-50"
        >
          {commentaryMut.isPending
            ? 'Generating…'
            : 'Generate Season Commentary'}
        </button>
        {commentaryMut.isError && (
          <p className="mt-2 text-sm text-red-400">
            {formatApiError(commentaryMut.error)}
          </p>
        )}
        {commentaryMut.data?.commentary && (
          <div className="mt-3">
            <AiCommentaryCard text={commentaryMut.data.commentary} />
          </div>
        )}
      </section>
    </div>
  )
}
