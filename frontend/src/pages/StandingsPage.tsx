import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { getPublishedArchive } from '../api'
import { recapLeagueSlug } from '../lib/supabase'
import { StandingsTab } from '../components/StandingsTab'

const RECAP_SEASON = Number(import.meta.env.VITE_RECAP_SEASON ?? 2026)

/**
 * P-6a: Standings promoted from a newsroom tab to its own route
 * (`/leagues/:slug/standings`). Reuses the self-contained `StandingsTab`
 * component; the only extra work is picking a week — standings snapshots are
 * week-scoped, so we resolve the latest published week (mirroring `Recap.tsx`).
 * Auto-loads on mount — no manual "Load" button (D-P6).
 */
export function StandingsPage() {
  const { slug } = useParams<{ slug: string }>()
  const effectiveSlug = slug || recapLeagueSlug
  const season = RECAP_SEASON

  const { data: archive, isLoading } = useQuery({
    queryKey: ['standings-page', 'archive', effectiveSlug, season],
    queryFn: () => getPublishedArchive(effectiveSlug, season),
    retry: false,
  })

  if (isLoading) {
    return (
      <div className="flex min-h-[200px] items-center justify-center">
        <p className="text-slate-400">Loading standings…</p>
      </div>
    )
  }

  // Latest published week, or week 1 if nothing's published yet.
  const week = archive && archive.length > 0 ? archive[archive.length - 1].week : 1

  return (
    <div className="space-y-4 pb-8">
      <h1 className="text-2xl font-bold text-white">Standings</h1>
      <StandingsTab slug={effectiveSlug} season={season} week={week} />
    </div>
  )
}
