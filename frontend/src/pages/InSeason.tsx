import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUp, ChevronDown, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { JsonRecord, MatchupCommentaryBody, ProjectedRosterPlayer } from '../api'
import {
  formatApiError,
  getMatchupConfidence,
  getPowerRankings,
  getRostersCurrent,
  getScoreboardCurrent,
  postMatchupCommentary,
  postProjectedScoreboard,
} from '../api'
import { AiCommentaryCard } from '../components/AiCommentaryCard'
import { ProjectionBadge } from '../components/ProjectionBadge'
import {
  clampDateToWeekWindow,
  currentRecord,
  enrichCurrentRows,
  formatStatValue,
  mapProjectionSource,
  type MatchupGroup,
  type ProjectionSource,
  pillClass,
  prepareMatchupGroups,
  projectedRecord,
  rankPillClass,
  rankPillEntries,
  sumNumGamesLeft,
} from '../lib/inSeasonUtils'
import {
  MATCHUP_WEEKS_2025_26,
  WEEK_MAX,
  WEEK_MIN,
} from '../lib/matchupWeeks'

type WeekLoadFlags = {
  projected: boolean
  current: boolean
  powerRankings: boolean
}

function emptyWeekFlags(): WeekLoadFlags {
  return { projected: false, current: false, powerRankings: false }
}

function mergeWeekFlags(prev?: Partial<WeekLoadFlags>): WeekLoadFlags {
  return { ...emptyWeekFlags(), ...prev }
}

const inSeasonQueryKeys = {
  projected: (week: number, proj: string, fileKey: string) =>
    ['in-season', 'projected', week, proj, fileKey] as const,
  current: (week: number) => ['in-season', 'current', week] as const,
  power: (week: number) => ['in-season', 'power', week] as const,
}

async function fetchProjectedMatchupGroups(
  week: number,
  projectionSource: ProjectionSource,
  bbmFile: File | null,
): Promise<MatchupGroup[]> {
  const weekMeta = MATCHUP_WEEKS_2025_26[week]
  const proj = mapProjectionSource(projectionSource)
  const weekEnd = weekMeta?.end
  const useUpload = projectionSource === 'bbm' && bbmFile
  if (useUpload) {
    const rows = await postProjectedScoreboard(
      {
        current_matchup_period: week,
        projections: proj,
        week_end_date: weekEnd,
      },
      bbmFile,
    )
    return prepareMatchupGroups(rows)
  }
  let gamesPlayed = 0
  let totalGames = 1
  if (weekMeta?.start && weekMeta?.end) {
    const todayStr = new Date().toISOString().slice(0, 10)
    const remStart = clampDateToWeekWindow(
      todayStr,
      weekMeta.start,
      weekMeta.end,
    )
    try {
      const [totalRows, remRows] = await Promise.all([
        getRostersCurrent({
          week_start_date: weekMeta.start,
          week_end_date: weekMeta.end,
          current_matchup_period: week,
          projections: proj,
        }),
        getRostersCurrent({
          week_start_date: remStart,
          week_end_date: weekMeta.end,
          current_matchup_period: week,
          projections: proj,
        }),
      ])
      const totalSum = sumNumGamesLeft(totalRows)
      const remSum = sumNumGamesLeft(remRows)
      const gp = Math.max(0, Math.round(totalSum - remSum))
      const tg = Math.max(1, Math.round(totalSum))
      gamesPlayed = gp
      totalGames = tg
    } catch {
      /* keep defaults */
    }
  }
  const confRows = await getMatchupConfidence({
    current_matchup_period: week,
    projections: proj,
    games_played: gamesPlayed,
    total_games: totalGames,
  })
  return prepareMatchupGroups(confRows)
}

async function fetchCurrentMatchupGroups(
  week: number,
): Promise<MatchupGroup[]> {
  const raw = await getScoreboardCurrent(week)
  return prepareMatchupGroups(enrichCurrentRows(raw))
}

const ESPN_RED = '#e03131'

const STICKY_TOP = '60px'

type ScoreboardView = 'current' | 'projected'

function projectionPillLabel(s: ProjectionSource): string {
  if (s === 'bbm') return 'BBM'
  if (s === '15') return 'Last 15'
  return 'Last 30'
}

function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-md bg-slate-700/50 ${className}`}
      aria-hidden
    />
  )
}

function buildProjectedRosterPlayers(
  rows: JsonRecord[],
  teamName: string,
  proj: ProjectionSource,
): ProjectedRosterPlayer[] {
  const suffix =
    proj === 'bbm' ? 'BBM' : proj === '15' ? 'Last 15' : 'Last 30'
  const projKey = (stat: string) =>
    proj === 'bbm'
      ? `Projected ${stat} BBM`
      : `Projected ${stat} ${suffix}`

  return rows
    .filter((r) => String(r.team_name) === teamName)
    .filter((r) => String(r.injuryStatus ?? '').toUpperCase() !== 'OUT')
    .map((r) => ({
      player_name: String(r.player_name ?? ''),
      pts: Number(r[projKey('PTS')] ?? 0) || 0,
      reb: Number(r[projKey('REB')] ?? 0) || 0,
      ast: Number(r[projKey('AST')] ?? 0) || 0,
      stl: Number(r[projKey('STL')] ?? 0) || 0,
      blk: Number(r[projKey('BLK')] ?? 0) || 0,
      '3pm': Number(r[projKey('3PM')] ?? 0) || 0,
      fg_pct: Number(r[projKey('FGM')] ?? 0) / Math.max(Number(r[projKey('FGA')] ?? 0), 1) || 0,
      ft_pct: Number(r[projKey('FTM')] ?? 0) / Math.max(Number(r[projKey('FTA')] ?? 0), 1) || 0,
      to: Number(r[projKey('TO')] ?? 0) || 0,
      games_left:
        r.num_games_left != null ? Number(r.num_games_left) : undefined,
    }))
}

function projectedCommentaryRows(
  stats: JsonRecord[],
): MatchupCommentaryBody['matchup_data'] {
  return stats.map((s) => {
    const hr = String(s.projected_home_result ?? '').toUpperCase()
    let conf: number | undefined
    const hc = s.home_confidence_pct
    const ac = s.away_confidence_pct
    if (hr === 'W' && hc != null) conf = Number(hc)
    else if (hr === 'L' && ac != null) conf = Number(ac)
    else if (hr === 'T') {
      const a = hc != null ? Number(hc) : NaN
      const b = ac != null ? Number(ac) : NaN
      if (Number.isFinite(a) && Number.isFinite(b)) conf = (a + b) / 2
      else if (Number.isFinite(a)) conf = a
      else if (Number.isFinite(b)) conf = b
    }
    return {
      stat: String(s.stat),
      home_score: Number(s.projected_home_score),
      away_score: Number(s.projected_away_score),
      result: String(s.projected_home_result ?? 'T'),
      confidence_pct: conf,
    }
  })
}

function currentCommentaryRows(
  stats: JsonRecord[],
): MatchupCommentaryBody['matchup_data'] {
  return stats.map((s) => ({
    stat: String(s.stat),
    home_score: Number(s.current_home_score),
    away_score: Number(s.current_away_score),
    result: String((s as JsonRecord)._home_res ?? 'T'),
    confidence_pct: undefined,
  }))
}

function MatchupCardsRow({
  groups,
  selectedKey,
  onSelect,
  recordFn,
}: {
  groups: MatchupGroup[]
  selectedKey: string | null
  onSelect: (key: string) => void
  recordFn: (stats: JsonRecord[]) => { home: number; away: number }
}) {
  if (groups.length === 0) return null
  return (
    <div className="flex gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {groups.map((g) => {
        const rec = recordFn(g.stats)
        const homeW = rec.home > rec.away
        const awayW = rec.away > rec.home
        const tie = rec.home === rec.away
        const active = selectedKey === g.key
        return (
          <button
            key={g.key}
            type="button"
            onClick={() => onSelect(g.key)}
            className={`min-h-[44px] min-w-[160px] shrink-0 rounded-xl border px-3 py-2 text-left transition ${
              active
                ? 'border-[#e03131] bg-slate-800/90'
                : 'border-slate-700/80 bg-slate-900/60'
            }`}
          >
            <div className="text-xs font-medium text-slate-300">
              {g.home} vs {g.away}
            </div>
            <div className="mt-1 text-sm font-semibold tabular-nums text-white">
              <span className={homeW && !tie ? 'text-emerald-400' : ''}>
                {rec.home}
              </span>
              <span className="text-slate-500">-</span>
              <span className={awayW && !tie ? 'text-emerald-400' : ''}>
                {rec.away}
              </span>
            </div>
            {!tie && (
              <div className="mt-0.5 text-xs text-emerald-400/90">
                {homeW ? g.home : g.away}
              </div>
            )}
          </button>
        )
      })}
    </div>
  )
}

function StatTableProjected({
  stats,
}: {
  stats: JsonRecord[]
}) {
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
          {stats.map((r) => {
            const stat = String(r.stat)
            const hr = String(r.projected_home_result ?? '').toUpperCase()
            const ar = String(r.projected_away_result ?? '').toUpperCase()
            const hConf = r.home_confidence_pct
            const aConf = r.away_confidence_pct
            return (
              <tr
                key={stat}
                className="border-b border-slate-800/80 last:border-0"
              >
                <td className="px-2 py-2 font-medium text-slate-200">{stat}</td>
                <td className="px-2 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="tabular-nums text-slate-100">
                      {formatStatValue(stat, r.projected_home_score)}
                    </span>
                    <span
                      className={`inline-flex min-h-[22px] min-w-[22px] items-center justify-center rounded-full px-1.5 text-[10px] font-bold text-white ${pillClass(hr)}`}
                    >
                      {hr}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[10px] text-slate-500">
                    {hConf != null && !Number.isNaN(Number(hConf))
                      ? `${Number(hConf).toFixed(0)}% conf`
                      : '—'}
                  </div>
                </td>
                <td className="px-2 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="tabular-nums text-slate-100">
                      {formatStatValue(stat, r.projected_away_score)}
                    </span>
                    <span
                      className={`inline-flex min-h-[22px] min-w-[22px] items-center justify-center rounded-full px-1.5 text-[10px] font-bold text-white ${pillClass(ar)}`}
                    >
                      {ar}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[10px] text-slate-500">
                    {aConf != null && !Number.isNaN(Number(aConf))
                      ? `${Number(aConf).toFixed(0)}% conf`
                      : '—'}
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

function StatTableCurrent({ stats }: { stats: JsonRecord[] }) {
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
          {stats.map((r) => {
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
                  <div className="mt-0.5 text-[10px] text-slate-500">Live</div>
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
                  <div className="mt-0.5 text-[10px] text-slate-500">Live</div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function InSeason() {
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [week, setWeek] = useState(1)
  const [projectionSource, setProjectionSource] =
    useState<ProjectionSource>('15')
  const [bbmFile, setBbmFile] = useState<File | null>(null)

  const [loadedWeeks, setLoadedWeeks] = useState<
    Record<number, WeekLoadFlags>
  >({})

  const [selectedProjectedKey, setSelectedProjectedKey] = useState<
    string | null
  >(null)
  const [selectedCurrentKey, setSelectedCurrentKey] = useState<string | null>(
    null,
  )
  const [expandedPowerTeam, setExpandedPowerTeam] = useState<string | null>(
    null,
  )
  const [scoreboardView, setScoreboardView] =
    useState<ScoreboardView>('current')
  const [settingsSheetOpen, setSettingsSheetOpen] = useState(false)
  const [powerRankingsExpanded, setPowerRankingsExpanded] = useState(false)
  const [showBackToTop, setShowBackToTop] = useState(false)
  const sheetTouchStartY = useRef(0)
  const [scoreboardFadeOpacity, setScoreboardFadeOpacity] = useState(1)
  const [powerFadeOpacity, setPowerFadeOpacity] = useState(1)
  const scoreboardFadeKeyRef = useRef<string | null>(null)
  const powerFadeKeyRef = useRef<string | null>(null)

  const weekMeta = MATCHUP_WEEKS_2025_26[week]
  const projParam = mapProjectionSource(projectionSource)
  const bbmFileKey = useMemo(
    () => (bbmFile ? `${bbmFile.name}:${bbmFile.size}:${bbmFile.lastModified}` : ''),
    [bbmFile],
  )

  const weeksParam = useMemo(
    () =>
      Array.from({ length: week }, (_, i) => String(i + 1)).join(','),
    [week],
  )

  const projectedQuery = useQuery({
    queryKey: inSeasonQueryKeys.projected(week, projParam, bbmFileKey),
    queryFn: () =>
      fetchProjectedMatchupGroups(week, projectionSource, bbmFile),
    enabled:
      loadedWeeks[week]?.projected === true &&
      scoreboardView === 'projected',
    staleTime: Infinity,
    gcTime: 1000 * 60 * 60 * 24,
  })

  const currentQuery = useQuery({
    queryKey: inSeasonQueryKeys.current(week),
    queryFn: () => fetchCurrentMatchupGroups(week),
    enabled:
      loadedWeeks[week]?.current === true && scoreboardView === 'current',
    staleTime: Infinity,
    gcTime: 1000 * 60 * 60 * 24,
  })

  const powerQuery = useQuery({
    queryKey: inSeasonQueryKeys.power(week),
    queryFn: () => getPowerRankings(weeksParam, 3),
    // Do not gate on powerRankingsExpanded — only on loaded flag — so the fetch
    // runs as soon as the user taps Load (see disabled-query isPending pitfall below).
    enabled: loadedWeeks[week]?.powerRankings === true,
    staleTime: Infinity,
    gcTime: 1000 * 60 * 60 * 24,
  })

  const prevProjectionSource = useRef(projectionSource)
  const prevBbmFile = useRef<File | null>(bbmFile)
  useEffect(() => {
    const srcChanged = prevProjectionSource.current !== projectionSource
    const fileChanged = prevBbmFile.current !== bbmFile
    prevProjectionSource.current = projectionSource
    prevBbmFile.current = bbmFile
    if (!srcChanged && !fileChanged) return
    setLoadedWeeks((prev) => ({
      ...prev,
      [week]: mergeWeekFlags({ ...prev[week], projected: false }),
    }))
  }, [projectionSource, bbmFile, week])

  useEffect(() => {
    const k = `${week}-${scoreboardView}`
    if (scoreboardFadeKeyRef.current === null) {
      scoreboardFadeKeyRef.current = k
      return
    }
    if (scoreboardFadeKeyRef.current !== k) {
      scoreboardFadeKeyRef.current = k
      setScoreboardFadeOpacity(0)
      const id = requestAnimationFrame(() => {
        requestAnimationFrame(() => setScoreboardFadeOpacity(1))
      })
      return () => cancelAnimationFrame(id)
    }
  }, [week, scoreboardView])

  useEffect(() => {
    if (powerFadeKeyRef.current === null) {
      powerFadeKeyRef.current = String(week)
      return
    }
    if (powerFadeKeyRef.current !== String(week)) {
      powerFadeKeyRef.current = String(week)
      setPowerFadeOpacity(0)
      const id = requestAnimationFrame(() => {
        requestAnimationFrame(() => setPowerFadeOpacity(1))
      })
      return () => cancelAnimationFrame(id)
    }
  }, [week])

  useEffect(() => {
    const groups = projectedQuery.data ?? []
    if (!groups.length) {
      setSelectedProjectedKey(null)
      return
    }
    setSelectedProjectedKey((k) => {
      if (k && groups.some((g) => g.key === k)) return k
      return groups[0].key
    })
  }, [projectedQuery.data])

  useEffect(() => {
    const groups = currentQuery.data ?? []
    if (!groups.length) {
      setSelectedCurrentKey(null)
      return
    }
    setSelectedCurrentKey((k) => {
      if (k && groups.some((g) => g.key === k)) return k
      return groups[0].key
    })
  }, [currentQuery.data])

  const projectedGroups = projectedQuery.data ?? []
  const currentGroups = currentQuery.data ?? []

  const selectedProjected = projectedGroups.find(
    (g) => g.key === selectedProjectedKey,
  )
  const selectedCurrent = currentGroups.find(
    (g) => g.key === selectedCurrentKey,
  )

  const markLoaded = useCallback(
    (section: keyof WeekLoadFlags) => {
      setLoadedWeeks((prev) => ({
        ...prev,
        [week]: mergeWeekFlags({ ...prev[week], [section]: true }),
      }))
    },
    [week],
  )

  const refreshProjected = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: inSeasonQueryKeys.projected(week, projParam, bbmFileKey),
    })
  }, [queryClient, week, projParam, bbmFileKey])

  const refreshCurrent = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: inSeasonQueryKeys.current(week),
    })
  }, [queryClient, week])

  const refreshPower = useCallback(() => {
    void queryClient.invalidateQueries({
      queryKey: inSeasonQueryKeys.power(week),
    })
  }, [queryClient, week])

  const powerLoaded = loadedWeeks[week]?.powerRankings === true

  const commentaryProj = useMutation({
    mutationFn: async () => {
      if (!selectedProjected) throw new Error('Select a matchup')
      const meta = weekMeta
      const proj = mapProjectionSource(projectionSource)
      let homeR: ProjectedRosterPlayer[] = []
      let awayR: ProjectedRosterPlayer[] = []
      try {
        const rosters = await getRostersCurrent({
          week_start_date: meta?.start,
          week_end_date: meta?.end,
          current_matchup_period: week,
          projections: proj,
        })
        homeR = buildProjectedRosterPlayers(
          rosters,
          selectedProjected.home,
          projectionSource,
        )
        awayR = buildProjectedRosterPlayers(
          rosters,
          selectedProjected.away,
          projectionSource,
        )
      } catch {
        /* optional rosters */
      }
      return postMatchupCommentary({
        home_team: selectedProjected.home,
        away_team: selectedProjected.away,
        matchup_data: projectedCommentaryRows(selectedProjected.stats),
        home_roster: homeR,
        away_roster: awayR,
        projections: proj,
        is_live: false,
      })
    },
  })

  const commentaryCur = useMutation({
    mutationFn: async () => {
      if (!selectedCurrent) throw new Error('Select a matchup')
      return postMatchupCommentary({
        home_team: selectedCurrent.home,
        away_team: selectedCurrent.away,
        matchup_data: currentCommentaryRows(selectedCurrent.stats),
        home_roster: [],
        away_roster: [],
        projections: undefined,
        is_live: true,
      })
    },
  })

  useEffect(() => {
    commentaryProj.reset()
    commentaryCur.reset()
  }, [scoreboardView])

  useEffect(() => {
    if (!settingsSheetOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSettingsSheetOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [settingsSheetOpen])

  useEffect(() => {
    const onScroll = () => setShowBackToTop(window.scrollY > 300)
    window.addEventListener('scroll', onScroll, { passive: true })
    onScroll()
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    if (!settingsSheetOpen) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
    }
  }, [settingsSheetOpen])

  const bumpWeek = useCallback(
    (d: number) => {
      setWeek((w) => Math.min(WEEK_MAX, Math.max(WEEK_MIN, w + d)))
    },
    [],
  )

  const onPickFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    setBbmFile(f ?? null)
    e.target.value = ''
  }

  const loadActiveScoreboard = () => {
    if (scoreboardView === 'projected') markLoaded('projected')
    else markLoaded('current')
  }

  const projLoaded = loadedWeeks[week]?.projected === true
  const currLoaded = loadedWeeks[week]?.current === true

  const scoreboardPending =
    scoreboardView === 'projected'
      ? projectedQuery.isPending && projLoaded
      : currentQuery.isPending && currLoaded

  return (
    <div className="space-y-4 overflow-x-hidden pb-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white md:text-3xl">
          In-Season
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Toggle between live box scores and full-week projections. Power rankings
          below.
        </p>
        {scoreboardView === 'projected' && (
          <div className="mt-2">
            <ProjectionBadge horizon="week" />
          </div>
        )}
      </div>

      {/* Compact settings — full controls in bottom sheet */}
      <button
        type="button"
        onClick={() => setSettingsSheetOpen(true)}
        className="flex min-h-[44px] w-full max-w-md items-center justify-center gap-2 rounded-full border border-slate-700 bg-slate-900/80 px-4 py-2.5 text-sm font-medium text-slate-100 shadow-sm"
        aria-haspopup="dialog"
        aria-expanded={settingsSheetOpen}
      >
        <span className="truncate">
          Week {week} ·{' '}
          {scoreboardView === 'current'
            ? 'Live'
            : projectionPillLabel(projectionSource)}
        </span>
        <span className="shrink-0 text-base leading-none" aria-hidden>
          ⚙️
        </span>
      </button>

      {settingsSheetOpen && (
        <div className="fixed inset-0 z-[60] flex items-end justify-center md:items-center md:justify-center md:p-4">
          <button
            type="button"
            tabIndex={-1}
            className="absolute inset-0 bg-black/55 backdrop-blur-[2px]"
            aria-label="Close settings"
            onClick={() => setSettingsSheetOpen(false)}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="inseason-settings-title"
            className="relative z-10 flex max-h-[min(90dvh,560px)] w-full max-w-lg flex-col rounded-t-2xl border border-slate-700 bg-slate-900 shadow-2xl md:max-h-[85vh] md:rounded-2xl"
            style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
            onTouchStart={(e) => {
              sheetTouchStartY.current = e.touches[0].clientY
            }}
            onTouchEnd={(e) => {
              const y = e.changedTouches[0].clientY
              if (y - sheetTouchStartY.current > 72) setSettingsSheetOpen(false)
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex shrink-0 cursor-grab justify-center pt-3 pb-1 active:cursor-grabbing">
              <div className="h-1.5 w-12 rounded-full bg-slate-600" aria-hidden />
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
              <h2
                id="inseason-settings-title"
                className="mb-4 text-center text-base font-semibold text-white"
              >
                Matchup settings
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
              <div
                className="mt-4 grid w-full grid-cols-2 gap-0 overflow-hidden rounded-lg border border-slate-700 bg-slate-950/80 p-0.5"
                role="radiogroup"
                aria-label="Scoreboard type"
              >
                <button
                  type="button"
                  role="radio"
                  aria-checked={scoreboardView === 'current'}
                  onClick={() => setScoreboardView('current')}
                  className={`min-h-[44px] rounded-md text-sm font-semibold transition ${
                    scoreboardView === 'current'
                      ? 'text-white shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                  style={
                    scoreboardView === 'current'
                      ? { backgroundColor: ESPN_RED }
                      : undefined
                  }
                >
                  Current
                </button>
                <button
                  type="button"
                  role="radio"
                  aria-checked={scoreboardView === 'projected'}
                  onClick={() => setScoreboardView('projected')}
                  className={`min-h-[44px] rounded-md text-sm font-semibold transition ${
                    scoreboardView === 'projected'
                      ? 'text-white shadow-sm'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                  style={
                    scoreboardView === 'projected'
                      ? { backgroundColor: ESPN_RED }
                      : undefined
                  }
                >
                  Projected
                </button>
              </div>
              {scoreboardView === 'projected' && (
                <div className="mt-4 grid gap-3">
                  <div
                    className="inline-flex min-h-[44px] w-full flex-wrap justify-center rounded-lg border border-slate-700 bg-slate-950/80 p-0.5"
                    role="group"
                    aria-label="Projection source"
                  >
                    {(
                      [
                        ['bbm', 'BBM File'],
                        ['15', 'Last 15'],
                        ['30', 'Last 30'],
                      ] as const
                    ).map(([k, label]) => {
                      const active = projectionSource === k
                      return (
                        <button
                          key={k}
                          type="button"
                          onClick={() => setProjectionSource(k)}
                          className={`min-h-[40px] shrink px-2.5 text-xs font-semibold sm:px-3 ${
                            active
                              ? 'rounded-md text-white'
                              : 'rounded-md text-slate-400 hover:text-slate-200'
                          }`}
                          style={
                            active
                              ? { backgroundColor: ESPN_RED, color: '#fff' }
                              : undefined
                          }
                        >
                          {label}
                        </button>
                      )
                    })}
                  </div>
                  {projectionSource === 'bbm' && (
                    <div className="flex min-h-[44px] justify-center">
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept=".xls,.xlsx,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        className="hidden"
                        onChange={onPickFile}
                      />
                      <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        className="min-h-[44px] max-w-full truncate rounded-lg border border-slate-600 bg-slate-800 px-4 text-sm font-medium text-slate-100"
                      >
                        {bbmFile
                          ? bbmFile.name.slice(0, 18) +
                            (bbmFile.name.length > 18 ? '…' : '')
                          : 'Upload BBM'}
                      </button>
                    </div>
                  )}
                </div>
              )}
              <button
                type="button"
                onClick={() => setSettingsSheetOpen(false)}
                className="mt-6 w-full min-h-[44px] rounded-lg border border-slate-600 bg-slate-800 py-2.5 text-sm font-semibold text-white"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Single scoreboard panel */}
      <section className="space-y-3 border-t border-slate-800/80 pt-4">
        <div
          className="sticky z-30 -mx-4 border-b border-slate-800/80 bg-slate-950/95 px-4 py-2 backdrop-blur-sm md:mx-0 md:px-0"
          style={{ top: STICKY_TOP }}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-white">
                {scoreboardView === 'current'
                  ? 'Current Matchup'
                  : 'Projected Scoreboard'}
              </h2>
              <p className="mt-0.5 text-xs text-slate-500">
                {scoreboardView === 'current'
                  ? 'ESPN category totals for this week — no projections.'
                  : 'Season-to-date plus projected rest of week. Confidence rises as the schedule completes (100% when all games are done).'}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {scoreboardView === 'projected' && projLoaded && (
                <button
                  type="button"
                  onClick={() => refreshProjected()}
                  className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-600 bg-slate-800/80 text-slate-200"
                  aria-label="Refresh projected scoreboard"
                >
                  <RefreshCw className="h-4 w-4" strokeWidth={2} />
                </button>
              )}
              {scoreboardView === 'current' && currLoaded && (
                <button
                  type="button"
                  onClick={() => refreshCurrent()}
                  className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-600 bg-slate-800/80 text-slate-200"
                  aria-label="Refresh current matchup"
                >
                  <RefreshCw className="h-4 w-4" strokeWidth={2} />
                </button>
              )}
              {((scoreboardView === 'projected' && !projLoaded) ||
                (scoreboardView === 'current' && !currLoaded)) && (
                <button
                  type="button"
                  onClick={loadActiveScoreboard}
                  disabled={scoreboardPending}
                  className="min-h-[44px] min-w-[88px] rounded-lg font-medium text-white disabled:opacity-50"
                  style={{ backgroundColor: ESPN_RED }}
                >
                  Load
                </button>
              )}
            </div>
          </div>
        </div>

        <div
          className="transition-opacity duration-150 ease-out"
          style={{ opacity: scoreboardFadeOpacity }}
        >
        {scoreboardPending && (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        )}

        {scoreboardView === 'projected' && projLoaded && projectedQuery.isError && (
          <p className="text-sm text-red-400">
            {formatApiError(projectedQuery.error)}
          </p>
        )}
        {scoreboardView === 'current' && currLoaded && currentQuery.isError && (
          <p className="text-sm text-red-400">
            {formatApiError(currentQuery.error)}
          </p>
        )}

        {scoreboardView === 'projected' &&
          projLoaded &&
          projectedQuery.isSuccess &&
          projectedGroups.length > 0 && (
            <>
              <MatchupCardsRow
                groups={projectedGroups}
                selectedKey={selectedProjectedKey}
                onSelect={setSelectedProjectedKey}
                recordFn={projectedRecord}
              />
              {selectedProjected && (
                <div className="space-y-3">
                  <StatTableProjected stats={selectedProjected.stats} />
                  {projectionSource === 'bbm' && bbmFile && (
                    <p className="text-[11px] text-slate-500">
                      Confidence uses server projections; BBM file affects
                      category scores only.
                    </p>
                  )}
                  <button
                    type="button"
                    onClick={() => commentaryProj.mutate()}
                    disabled={commentaryProj.isPending}
                    className="min-h-[44px] w-full rounded-lg border border-slate-600 bg-slate-800/80 py-2.5 text-sm font-medium text-white disabled:opacity-50"
                  >
                    Get AI Commentary
                  </button>
                  {commentaryProj.isPending && (
                    <Skeleton className="h-20 w-full" />
                  )}
                  {commentaryProj.isError && (
                    <p className="text-sm text-red-400">
                      {formatApiError(commentaryProj.error)}
                    </p>
                  )}
                  {commentaryProj.data?.commentary && (
                    <AiCommentaryCard text={commentaryProj.data.commentary} />
                  )}
                </div>
              )}
            </>
          )}
        {scoreboardView === 'projected' &&
          projLoaded &&
          projectedQuery.isSuccess &&
          projectedGroups.length === 0 && (
            <p className="text-sm text-slate-500">No matchups for this week.</p>
          )}

        {scoreboardView === 'current' &&
          currLoaded &&
          currentQuery.isSuccess &&
          currentGroups.length > 0 && (
            <>
              <MatchupCardsRow
                groups={currentGroups}
                selectedKey={selectedCurrentKey}
                onSelect={setSelectedCurrentKey}
                recordFn={currentRecord}
              />
              {selectedCurrent && (
                <div className="space-y-3">
                  <StatTableCurrent stats={selectedCurrent.stats} />
                  <button
                    type="button"
                    onClick={() => commentaryCur.mutate()}
                    disabled={commentaryCur.isPending}
                    className="min-h-[44px] w-full rounded-lg border border-slate-600 bg-slate-800/80 py-2.5 text-sm font-medium text-white disabled:opacity-50"
                  >
                    Get AI Commentary
                  </button>
                  {commentaryCur.isPending && (
                    <Skeleton className="h-20 w-full" />
                  )}
                  {commentaryCur.isError && (
                    <p className="text-sm text-red-400">
                      {formatApiError(commentaryCur.error)}
                    </p>
                  )}
                  {commentaryCur.data?.commentary && (
                    <AiCommentaryCard text={commentaryCur.data.commentary} />
                  )}
                </div>
              )}
            </>
          )}
        {scoreboardView === 'current' &&
          currLoaded &&
          currentQuery.isSuccess &&
          currentGroups.length === 0 && (
            <p className="text-sm text-slate-500">No live scoreboard data.</p>
          )}
        </div>
      </section>

      {/* Power rankings */}
      <section className="border-t border-slate-800/80 pt-4">
        <button
          type="button"
          onClick={() => setPowerRankingsExpanded((v) => !v)}
          className="sticky z-30 -mx-4 flex w-full items-center justify-between gap-2 border-b border-slate-800/80 bg-slate-950/95 px-4 py-2 text-left backdrop-blur-sm md:mx-0 md:px-0"
          style={{ top: STICKY_TOP }}
          aria-expanded={powerRankingsExpanded}
        >
          <h2 className="text-lg font-semibold text-white">Power Rankings</h2>
          <ChevronDown
            className={`h-5 w-5 shrink-0 text-slate-400 transition-transform duration-200 ${
              powerRankingsExpanded ? 'rotate-180' : ''
            }`}
            aria-hidden
          />
        </button>
        {powerRankingsExpanded && (
          <div
            className="mt-3 space-y-3 transition-opacity duration-150 ease-out"
            style={{ opacity: powerFadeOpacity }}
          >
            <div className="flex justify-end gap-2">
              {powerLoaded && (
                <button
                  type="button"
                  onClick={() => refreshPower()}
                  className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-600 bg-slate-800/80 text-slate-200"
                  aria-label="Refresh power rankings"
                >
                  <RefreshCw className="h-4 w-4" strokeWidth={2} />
                </button>
              )}
              {!powerLoaded && (
                <button
                  type="button"
                  onClick={() => markLoaded('powerRankings')}
                  className="min-h-[44px] min-w-[88px] rounded-lg font-medium text-white"
                  style={{ backgroundColor: ESPN_RED }}
                >
                  Load
                </button>
              )}
            </div>
            {powerLoaded && powerQuery.isPending && (
              <div className="space-y-2">
                <Skeleton className="h-14 w-full" />
                <Skeleton className="h-14 w-full" />
                <Skeleton className="h-14 w-full" />
              </div>
            )}
            {powerLoaded && powerQuery.isError && (
              <p className="text-sm text-red-400">
                {formatApiError(powerQuery.error)}
              </p>
            )}
            {powerLoaded &&
              powerQuery.isSuccess &&
              (powerQuery.data ?? []).map((row) => {
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
                        {ch > 0 ? `▲${ch}` : ch < 0 ? `▼${Math.abs(ch)}` : '—'}
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
          </div>
        )}
      </section>

      {showBackToTop && (
        <button
          type="button"
          onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
          className="fixed bottom-24 right-4 z-[55] flex h-11 w-11 items-center justify-center rounded-full border border-slate-600 bg-slate-800/95 text-slate-100 shadow-lg md:bottom-8"
          aria-label="Back to top"
        >
          <ArrowUp className="h-5 w-5" strokeWidth={2} />
        </button>
      )}
    </div>
  )
}
