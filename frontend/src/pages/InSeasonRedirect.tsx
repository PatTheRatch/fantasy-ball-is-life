import { Navigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getPublishedArchive } from '../api'
import { recapLeagueSlug } from '../lib/supabase'

const RECAP_SEASON = Number(import.meta.env.VITE_RECAP_SEASON ?? 2026)

/** Flat `/in-season` → league-scoped matchups route (P-7). */
export function InSeasonRedirect() {
  const archiveQuery = useQuery({
    queryKey: ['standings-page', 'archive', recapLeagueSlug, RECAP_SEASON],
    queryFn: () => getPublishedArchive(recapLeagueSlug, RECAP_SEASON),
    retry: false,
  })
  const week =
    archiveQuery.data && archiveQuery.data.length > 0
      ? archiveQuery.data[archiveQuery.data.length - 1].week
      : 1

  if (archiveQuery.isLoading) {
    return <p className="text-slate-400">Loading matchups…</p>
  }

  return <Navigate to={`/leagues/${recapLeagueSlug}/matchups/${week}`} replace />
}
