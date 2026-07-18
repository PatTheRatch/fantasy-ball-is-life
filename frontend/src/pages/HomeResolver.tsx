import { useQuery } from '@tanstack/react-query'
import { Link, Navigate } from 'react-router-dom'
import { ChevronRight } from 'lucide-react'
import { useAuth } from '../lib/authContext'
import { getMyLeagues, type MyLeague } from '../lib/memberships'
import { recapLeagueSlug } from '../lib/supabase'

function Spinner() {
  return (
    <div className="flex min-h-[200px] items-center justify-center">
      <p className="text-slate-400">Loading…</p>
    </div>
  )
}

function LeaguePicker({ leagues }: { leagues: MyLeague[] }) {
  return (
    <div className="mx-auto max-w-md space-y-4 pt-8">
      <h1 className="text-2xl font-bold text-white">Your leagues</h1>
      <ul className="space-y-2">
        {leagues.map((league) => (
          <li key={league.leagueId}>
            <Link
              to={`/leagues/${league.slug}`}
              className="flex items-center justify-between rounded-pg-lg border border-pg-border bg-pg-card px-4 py-3 transition-colors hover:bg-pg-card-hover"
            >
              <span>
                <span className="block font-semibold text-white">
                  {league.name}
                </span>
                {league.teamName && (
                  <span className="block text-sm text-slate-400">
                    {league.teamName}
                  </span>
                )}
              </span>
              <ChevronRight className="h-4 w-4 text-slate-500" aria-hidden />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * P-6b: logged-in `/` resolver (spec §5). Membership count decides:
 * exactly one league → straight to its League Home; more than one → a
 * minimal league picker. Logged out (or zero/unreadable memberships) →
 * the single-league default slug, until the P-8 landing page exists.
 */
export function HomeResolver() {
  const { session, user, loading } = useAuth()

  const membershipsQuery = useQuery({
    queryKey: ['my-leagues', user?.id],
    queryFn: () => getMyLeagues(user!.id),
    enabled: Boolean(session && user),
    retry: false,
  })

  if (loading) return <Spinner />

  if (!session || !user) {
    return <Navigate to={`/leagues/${recapLeagueSlug}`} replace />
  }

  if (membershipsQuery.isLoading) return <Spinner />

  const leagues = membershipsQuery.data ?? []
  if (leagues.length === 1) {
    return <Navigate to={`/leagues/${leagues[0].slug}`} replace />
  }
  if (leagues.length > 1) {
    return <LeaguePicker leagues={leagues} />
  }
  return <Navigate to={`/leagues/${recapLeagueSlug}`} replace />
}
