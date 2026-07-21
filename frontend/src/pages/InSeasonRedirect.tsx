import { Navigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getRecapsCurrent } from '../api'
import { useLeagueSlug } from '../lib/useLeagueSlug'

/**
 * Matchups resolver — mounted at `/leagues/:slug/matchups` (N-3) and the
 * flat legacy `/in-season` (default league via `useLeagueSlug` fallback).
 * Picks the league's configured season and latest published week
 * server-side, then redirects to the concrete week route.
 */
export function InSeasonRedirect() {
  const slug = useLeagueSlug()
  const currentQuery = useQuery({
    queryKey: ['recaps-current', slug],
    queryFn: () => getRecapsCurrent(slug),
    retry: false,
  })
  const archive = currentQuery.data?.archive
  const week = archive && archive.length > 0 ? archive[archive.length - 1].week : 1

  if (currentQuery.isLoading) {
    return <p className="text-slate-400">Loading matchups…</p>
  }

  return <Navigate to={`/leagues/${slug}/matchups/${week}`} replace />
}
