import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { getPublishedArchive } from '../api'
import { MatchupsPanel } from '../components/matchup/MatchupsPanel'
import { ScoreboardTools } from '../components/inSeason/ScoreboardTools'
import { WEEK_MAX, WEEK_MIN } from '../lib/matchupWeeks'
import { recapLeagueSlug } from '../lib/supabase'

const RECAP_SEASON = Number(import.meta.env.VITE_RECAP_SEASON ?? 2026)

type TabId = 'matchups' | 'tools'

/**
 * P-7: `/leagues/:slug/matchups/:week` — matchup detail route.
 * Tabs: Matchups (snapshot + charts) · Tools (live/projected + commentary + rankings).
 * All reads auto-load (D-P6).
 */
export function MatchupWeekPage() {
  const { slug, week: weekParam } = useParams<{ slug: string; week: string }>()
  const navigate = useNavigate()
  const effectiveSlug = slug || recapLeagueSlug
  const season = RECAP_SEASON
  const [tab, setTab] = useState<TabId>('matchups')

  const archiveQuery = useQuery({
    queryKey: ['standings-page', 'archive', effectiveSlug, season],
    queryFn: () => getPublishedArchive(effectiveSlug, season),
    retry: false,
  })

  const latestWeek = useMemo(() => {
    const archive = archiveQuery.data
    if (archive && archive.length > 0) return archive[archive.length - 1].week
    return 1
  }, [archiveQuery.data])

  const week = useMemo(() => {
    const parsed = Number(weekParam)
    if (Number.isFinite(parsed) && parsed >= WEEK_MIN && parsed <= WEEK_MAX) {
      return Math.trunc(parsed)
    }
    return latestWeek
  }, [weekParam, latestWeek])

  const bumpWeek = (delta: number) => {
    const next = Math.min(WEEK_MAX, Math.max(WEEK_MIN, week + delta))
    navigate(`/leagues/${effectiveSlug}/matchups/${next}`)
  }

  return (
    <div className="space-y-4 pb-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-white md:text-3xl">
            Matchups
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Week {week} ·{' '}
            <Link
              to={`/leagues/${effectiveSlug}`}
              className="font-semibold text-pg-accent hover:underline"
            >
              League Home
            </Link>
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => bumpWeek(-1)}
            disabled={week <= WEEK_MIN}
            className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-700 text-slate-300 disabled:opacity-40"
            aria-label="Previous week"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
          <span className="min-w-[4.5rem] text-center text-sm font-semibold tabular-nums text-white">
            Week {week}
          </span>
          <button
            type="button"
            onClick={() => bumpWeek(1)}
            disabled={week >= WEEK_MAX}
            className="flex h-10 w-10 items-center justify-center rounded-lg border border-slate-700 text-slate-300 disabled:opacity-40"
            aria-label="Next week"
          >
            <ChevronRight className="h-5 w-5" />
          </button>
        </div>
      </header>

      <div className="flex gap-2 border-b border-slate-800 pb-px">
        {(
          [
            { id: 'matchups' as const, label: 'Matchups' },
            { id: 'tools' as const, label: 'Live & projections' },
          ] as const
        ).map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-semibold transition-colors ${
              tab === t.id
                ? 'border-pg-accent text-white'
                : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'matchups' && (
        <MatchupsPanel slug={effectiveSlug} season={season} week={week} />
      )}
      {tab === 'tools' && <ScoreboardTools week={week} />}
    </div>
  )
}
