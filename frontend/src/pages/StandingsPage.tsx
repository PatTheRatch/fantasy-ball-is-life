import { useQuery } from '@tanstack/react-query'
import { getRecapsCurrent } from '../api'
import { useLeagueSlug } from '../lib/useLeagueSlug'
import { StandingsTab } from '../components/StandingsTab'

/**
 * P-6a: Standings promoted from a newsroom tab to its own route
 * (`/leagues/:slug/standings`). Reuses the self-contained `StandingsTab`
 * component; the only extra work is picking a week — standings snapshots are
 * week-scoped, so we resolve the latest published week (mirroring `Recap.tsx`).
 * Auto-loads on mount — no manual "Load" button (D-P6).
 * N-3: slug comes from the route; season from the league's `espn_season`.
 */
export function StandingsPage() {
  const slug = useLeagueSlug()

  const { data: current, isLoading } = useQuery({
    queryKey: ['recaps-current', slug],
    queryFn: () => getRecapsCurrent(slug),
    retry: false,
  })

  if (isLoading) {
    return (
      <div className="flex min-h-[200px] items-center justify-center">
        <p className="text-slate-400">Loading standings…</p>
      </div>
    )
  }

  if (!current) {
    return (
      <div className="flex min-h-[200px] items-center justify-center">
        <p className="text-slate-400">Couldn’t load this league.</p>
      </div>
    )
  }

  // Latest published week, or week 1 if nothing's published yet.
  const { season, archive } = current
  const week = archive.length > 0 ? archive[archive.length - 1].week : 1

  return (
    <div className="space-y-4 pb-8">
      <h1 className="text-2xl font-bold text-white">Standings</h1>
      <StandingsTab slug={slug} season={season} week={week} />
    </div>
  )
}
