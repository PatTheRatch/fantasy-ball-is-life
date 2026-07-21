import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, RefreshCw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useLeagueSlug } from '../../lib/useLeagueSlug'
import type { ProjectedRosterPlayer } from '../../api'
import {
  formatApiError,
  getPowerRankings,
  getRostersCurrent,
  postMatchupCommentary,
  putProjectionsActive,
  deleteProjectionsActive,
} from '../../api'
import { AiCommentaryCard } from '../AiCommentaryCard'
import { ProjectionBadge } from '../ProjectionBadge'
import {
  currentRecord,
  mapProjectionSource,
  type ProjectionSource,
  projectedRecord,
  rankPillClass,
  rankPillEntries,
} from '../../lib/inSeasonUtils'
import {
  buildProjectedRosterPlayers,
  currentCommentaryRows,
  fetchCurrentMatchupGroups,
  fetchProjectedMatchupGroups,
  inSeasonQueryKeys,
  projectedCommentaryRows,
} from '../../lib/inSeasonFetch'
import { MATCHUP_WEEKS_2025_26 } from '../../lib/matchupWeeks'
import { MatchupCardsRow } from './MatchupCardsRow'
import { SourcePicker } from './SourcePicker'
import { StatTableCurrent } from './StatTableCurrent'
import { StatTableProjected } from './StatTableProjected'
import { CategoryMarginChart } from '../matchup/CategoryMarginChart'
import { WinProbabilityStrip } from '../matchup/WinProbabilityStrip'

type ScoreboardView = 'current' | 'projected'

function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded-md bg-slate-700/50 ${className}`} aria-hidden />
  )
}

function projectionPillLabel(s: ProjectionSource): string {
  if (s === 'bbm') return 'BBM'
  if (s === '15') return 'Last 15'
  return 'Last 30'
}

/**
 * Live + projected scoreboard tools + power rankings (auto-load, D-P6).
 * Extracted from the InSeason monolith for P-7.
 */
export function ScoreboardTools({ week }: { slug: string; week: number }) {
  const queryClient = useQueryClient()
  const [projectionSource, setProjectionSource] = useState<ProjectionSource>('15')
  const [bbmFile, setBbmFile] = useState<File | null>(null)
  const [selectedProjectedKey, setSelectedProjectedKey] = useState<string | null>(null)
  const [selectedCurrentKey, setSelectedCurrentKey] = useState<string | null>(null)
  const [expandedPowerTeam, setExpandedPowerTeam] = useState<string | null>(null)
  const [scoreboardView, setScoreboardView] = useState<ScoreboardView>('current')
  const [settingsOpen, setSettingsOpen] = useState(false)

  const weekMeta = MATCHUP_WEEKS_2025_26[week]
  const projParam = mapProjectionSource(projectionSource)
  const bbmFileKey = useMemo(
    () => (bbmFile ? `${bbmFile.name}:${bbmFile.size}:${bbmFile.lastModified}` : ''),
    [bbmFile],
  )
  const slug = useLeagueSlug()
  const weeksParam = useMemo(
    () => Array.from({ length: week }, (_, i) => String(i + 1)).join(','),
    [week],
  )

  const projectedQuery = useQuery({
    queryKey: inSeasonQueryKeys.projected(week, projParam, bbmFileKey),
    queryFn: () => fetchProjectedMatchupGroups(slug, week, projectionSource, bbmFile),
    enabled: scoreboardView === 'projected',
    staleTime: 60_000,
  })

  const currentQuery = useQuery({
    queryKey: inSeasonQueryKeys.current(week),
    queryFn: () => fetchCurrentMatchupGroups(slug, week),
    enabled: scoreboardView === 'current',
    staleTime: 60_000,
  })

  const powerQuery = useQuery({
    queryKey: inSeasonQueryKeys.power(week),
    queryFn: () => getPowerRankings(slug, weeksParam, 3),
    staleTime: 60_000,
  })

  const projectedGroups = projectedQuery.data ?? []
  const currentGroups = currentQuery.data ?? []

  const selectedProjectedKeyResolved =
    selectedProjectedKey && projectedGroups.some((g) => g.key === selectedProjectedKey)
      ? selectedProjectedKey
      : (projectedGroups[0]?.key ?? null)
  const selectedCurrentKeyResolved =
    selectedCurrentKey && currentGroups.some((g) => g.key === selectedCurrentKey)
      ? selectedCurrentKey
      : (currentGroups[0]?.key ?? null)

  const selectedProjected = projectedGroups.find((g) => g.key === selectedProjectedKeyResolved)
  const selectedCurrent = currentGroups.find((g) => g.key === selectedCurrentKeyResolved)

  const commentaryProj = useMutation({
    mutationFn: async () => {
      if (!selectedProjected) throw new Error('Select a matchup')
      const proj = mapProjectionSource(projectionSource)
      let homeR: ProjectedRosterPlayer[] = []
      let awayR: ProjectedRosterPlayer[] = []
      try {
        const rosters = await getRostersCurrent(slug, {
          week_start_date: weekMeta?.start,
          week_end_date: weekMeta?.end,
          current_matchup_period: week,
          projections: proj,
        })
        homeR = buildProjectedRosterPlayers(rosters, selectedProjected.home, projectionSource)
        awayR = buildProjectedRosterPlayers(rosters, selectedProjected.away, projectionSource)
      } catch {
        /* optional */
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

  const scoreboardPending =
    scoreboardView === 'projected' ? projectedQuery.isPending : currentQuery.isPending

  const projectedChartCats = (selectedProjected?.stats ?? []).map((s) => ({
    ...s,
    home_value: s.projected_home_score,
    away_value: s.projected_away_score,
    winner:
      String(s.projected_home_result ?? '').toUpperCase() === 'W'
        ? 'home'
        : String(s.projected_home_result ?? '').toUpperCase() === 'L'
          ? 'away'
          : String(s.projected_home_result ?? '').toUpperCase() === 'T'
            ? 'tie'
            : '',
  }))

  const currentChartCats = (selectedCurrent?.stats ?? []).map((s) => ({
    ...s,
    home_value: s.current_home_score,
    away_value: s.current_away_score,
    winner:
      String((s as Record<string, unknown>)._home_res ?? '') === 'W'
        ? 'home'
        : String((s as Record<string, unknown>)._home_res ?? '') === 'L'
          ? 'away'
          : 'tie',
  }))

  return (
    <div className="space-y-4">
      <button
        type="button"
        onClick={() => setSettingsOpen(true)}
        className="flex min-h-[44px] w-full max-w-md items-center justify-center gap-2 rounded-full border border-slate-700 bg-slate-900/80 px-4 py-2.5 text-sm font-medium text-slate-100"
      >
        <span className="truncate">
          {scoreboardView === 'current' ? 'Live' : projectionPillLabel(projectionSource)} tools
        </span>
        <span aria-hidden>⚙️</span>
      </button>

      {settingsOpen && (
        <div className="fixed inset-0 z-[60] flex items-end justify-center md:items-center md:p-4">
          <button
            type="button"
            className="absolute inset-0 bg-black/55"
            aria-label="Close settings"
            onClick={() => setSettingsOpen(false)}
          />
          <div
            role="dialog"
            aria-modal="true"
            className="relative z-10 max-h-[85vh] w-full max-w-md overflow-y-auto rounded-t-2xl border border-slate-700 bg-slate-900 p-5 md:rounded-2xl"
          >
            <h2 className="text-lg font-semibold text-white">Matchup tools</h2>
            <div className="mt-4 space-y-3">
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">View</p>
              <div className="flex gap-2">
                {(['current', 'projected'] as const).map((v) => (
                  <button
                    key={v}
                    type="button"
                    onClick={() => {
                      setScoreboardView(v)
                      commentaryProj.reset()
                      commentaryCur.reset()
                    }}
                    className={`min-h-[40px] flex-1 rounded-lg border px-3 text-sm font-semibold ${
                      scoreboardView === v
                        ? 'border-red-500/50 bg-red-500/10 text-white'
                        : 'border-slate-700 text-slate-400'
                    }`}
                  >
                    {v === 'current' ? 'Live' : 'Projected'}
                  </button>
                ))}
              </div>
              {scoreboardView === 'projected' && (
                <>
                  <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
                    Projection source
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {(['15', '30', 'bbm'] as const).map((s) => (
                      <button
                        key={s}
                        type="button"
                        onClick={() => setProjectionSource(s)}
                        className={`rounded-lg border px-3 py-2 text-sm ${
                          projectionSource === s
                            ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300'
                            : 'border-slate-700 text-slate-400'
                        }`}
                      >
                        {projectionPillLabel(s)}
                      </button>
                    ))}
                  </div>
                  {projectionSource === 'bbm' && (
                    <input
                      type="file"
                      accept=".csv,.xlsx,.xls"
                      onChange={(e) => {
                        setBbmFile(e.target.files?.[0] ?? null)
                        e.target.value = ''
                      }}
                      className="block w-full text-sm text-slate-400"
                    />
                  )}
                  <SourcePicker
                    onActivate={async (setId) => {
                      await putProjectionsActive(setId)
                      void queryClient.invalidateQueries({ queryKey: ['in-season', 'projected'] })
                    }}
                    onClear={async () => {
                      await deleteProjectionsActive('week')
                      void queryClient.invalidateQueries({ queryKey: ['in-season', 'projected'] })
                    }}
                  />
                </>
              )}
              <button
                type="button"
                onClick={() => setSettingsOpen(false)}
                className="mt-4 w-full min-h-[44px] rounded-lg border border-slate-600 bg-slate-800 py-2.5 text-sm font-semibold text-white"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}

      <section className="space-y-3 border-t border-slate-800/80 pt-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold text-white">
              {scoreboardView === 'current' ? 'Current Matchup' : 'Projected Scoreboard'}
            </h2>
            {scoreboardView === 'projected' && (
              <div className="mt-1">
                <ProjectionBadge horizon="week" />
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={() =>
              void queryClient.invalidateQueries({
                queryKey:
                  scoreboardView === 'projected'
                    ? inSeasonQueryKeys.projected(week, projParam, bbmFileKey)
                    : inSeasonQueryKeys.current(week),
              })
            }
            className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-600 bg-slate-800/80 text-slate-200"
            aria-label="Refresh scoreboard"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>

        {scoreboardPending && (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-32 w-full" />
          </div>
        )}

        {scoreboardView === 'projected' && projectedQuery.isError && (
          <p className="text-sm text-red-400">{formatApiError(projectedQuery.error)}</p>
        )}
        {scoreboardView === 'current' && currentQuery.isError && (
          <p className="text-sm text-red-400">{formatApiError(currentQuery.error)}</p>
        )}

        {scoreboardView === 'projected' && projectedQuery.isSuccess && projectedGroups.length > 0 && (
          <>
            <MatchupCardsRow
              groups={projectedGroups}
              selectedKey={selectedProjectedKeyResolved}
              onSelect={setSelectedProjectedKey}
              recordFn={projectedRecord}
            />
            {selectedProjected && (
              <div className="space-y-3">
                <WinProbabilityStrip
                  homeTeam={selectedProjected.home}
                  awayTeam={selectedProjected.away}
                  categories={projectedChartCats}
                  mode="projected"
                />
                <CategoryMarginChart categories={projectedChartCats} />
                <StatTableProjected stats={selectedProjected.stats} />
                <button
                  type="button"
                  onClick={() => commentaryProj.mutate()}
                  disabled={commentaryProj.isPending}
                  className="min-h-[44px] w-full rounded-lg border border-slate-600 bg-slate-800/80 py-2.5 text-sm font-medium text-white disabled:opacity-50"
                >
                  Get AI Commentary
                </button>
                {commentaryProj.isPending && <Skeleton className="h-20 w-full" />}
                {commentaryProj.isError && (
                  <p className="text-sm text-red-400">{formatApiError(commentaryProj.error)}</p>
                )}
                {commentaryProj.data?.commentary && (
                  <AiCommentaryCard text={commentaryProj.data.commentary} />
                )}
              </div>
            )}
          </>
        )}
        {scoreboardView === 'projected' &&
          projectedQuery.isSuccess &&
          projectedGroups.length === 0 && (
            <p className="text-sm text-slate-500">No matchups for this week.</p>
          )}

        {scoreboardView === 'current' && currentQuery.isSuccess && currentGroups.length > 0 && (
          <>
            <MatchupCardsRow
              groups={currentGroups}
              selectedKey={selectedCurrentKeyResolved}
              onSelect={setSelectedCurrentKey}
              recordFn={currentRecord}
            />
            {selectedCurrent && (
              <div className="space-y-3">
                <WinProbabilityStrip
                  homeTeam={selectedCurrent.home}
                  awayTeam={selectedCurrent.away}
                  categories={currentChartCats}
                  mode="live"
                />
                <CategoryMarginChart categories={currentChartCats} />
                <StatTableCurrent stats={selectedCurrent.stats} />
                <button
                  type="button"
                  onClick={() => commentaryCur.mutate()}
                  disabled={commentaryCur.isPending}
                  className="min-h-[44px] w-full rounded-lg border border-slate-600 bg-slate-800/80 py-2.5 text-sm font-medium text-white disabled:opacity-50"
                >
                  Get AI Commentary
                </button>
                {commentaryCur.isPending && <Skeleton className="h-20 w-full" />}
                {commentaryCur.isError && (
                  <p className="text-sm text-red-400">{formatApiError(commentaryCur.error)}</p>
                )}
                {commentaryCur.data?.commentary && (
                  <AiCommentaryCard text={commentaryCur.data.commentary} />
                )}
              </div>
            )}
          </>
        )}
        {scoreboardView === 'current' &&
          currentQuery.isSuccess &&
          currentGroups.length === 0 && (
            <p className="text-sm text-slate-500">No live scoreboard data.</p>
          )}
      </section>

      <section className="border-t border-slate-800/80 pt-4">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">Power Rankings</h2>
          <button
            type="button"
            onClick={() =>
              void queryClient.invalidateQueries({ queryKey: inSeasonQueryKeys.power(week) })
            }
            className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-600 bg-slate-800/80 text-slate-200"
            aria-label="Refresh power rankings"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>
        {powerQuery.isPending && (
          <div className="space-y-2">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        )}
        {powerQuery.isError && (
          <p className="text-sm text-red-400">{formatApiError(powerQuery.error)}</p>
        )}
        {powerQuery.isSuccess &&
          (powerQuery.data ?? []).map((row) => {
            const team = String(row.team ?? '')
            const rank = Number(row.rank)
            const comp = Number(row.composite_score)
            const ch = Number(row.rank_change ?? 0)
            const expanded = expandedPowerTeam === team
            const pills = rankPillEntries(row)
            return (
              <div key={team} className="mb-2 rounded-xl border border-slate-800 bg-slate-950/40">
                <button
                  type="button"
                  onClick={() => setExpandedPowerTeam(expanded ? null : team)}
                  className="flex min-h-[44px] w-full items-center gap-3 px-3 py-2 text-left"
                >
                  <span className="w-8 text-2xl font-bold tabular-nums text-white">{rank}</span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium text-slate-100">{team}</div>
                    <div className="text-xs text-slate-500">
                      Composite{' '}
                      <span className="tabular-nums text-slate-300">
                        {Number.isFinite(comp) ? comp.toFixed(3) : '—'}
                      </span>
                    </div>
                  </div>
                  <span
                    className={`shrink-0 text-sm font-semibold ${
                      ch > 0 ? 'text-emerald-400' : ch < 0 ? 'text-red-400' : 'text-slate-500'
                    }`}
                  >
                    {ch > 0 ? `▲${ch}` : ch < 0 ? `▼${Math.abs(ch)}` : '—'}
                  </span>
                  <ChevronDown
                    className={`h-4 w-4 text-slate-500 transition-transform ${expanded ? 'rotate-180' : ''}`}
                  />
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
      </section>
    </div>
  )
}
