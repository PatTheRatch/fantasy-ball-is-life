import { useQuery } from '@tanstack/react-query'
import { Link, Navigate } from 'react-router-dom'
import { ArrowRight, ChevronRight } from 'lucide-react'
import { useAuth } from '../lib/authContext'
import { getMyLeagues, type MyLeague } from '../lib/memberships'
import { recapLeagueSlug } from '../lib/supabase'
import { Landing } from './Landing'

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
 * N-1: signed-in, zero-membership lobby.
 * Explains the join path but actual self-join ships in N-2.
 */
function Lobby() {
  const demoPath = `/leagues/${recapLeagueSlug}`
  return (
    <div className="mx-auto max-w-md space-y-4 pt-8">
      <h1 className="text-2xl font-bold text-white">Welcome to Full Court Press</h1>
      <p className="text-slate-400">
        You're signed in, but not in a league yet.
      </p>
      <div className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
        <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400">
          Join your league
        </h2>
        <p className="mt-2 text-sm text-slate-300">
          Get your league's link from a leaguemate, or an invite from your admin.
          Self-join is coming soon — for now, an admin adds you directly.
        </p>
        <Link
          to={demoPath}
          className="mt-3 inline-flex items-center gap-2 text-sm font-semibold text-pg-accent hover:underline"
        >
          Browse the demo league <ArrowRight className="h-3 w-3" aria-hidden />
        </Link>
      </div>
      <Link
        to="/leagues/new"
        className="rounded-pg-lg border border-pg-border bg-pg-card p-5 block hover:border-pg-accent/50 transition-colors group"
      >
        <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300 group-hover:text-white">
          Set up a new league
        </h2>
        <p className="mt-2 text-sm text-slate-400">
          Create a league by linking your ESPN fantasy league — two clicks, one form.
        </p>
      </Link>
    </div>
  )
}

/**
 * N-1: Home resolver (spec N-1). Four states:
 * - logged-out → Landing page
 * - signed-in, zero memberships → Lobby
 * - signed-in, 1 league → straight to League Home
 * - signed-in, >1 league → picker
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

  // ── Logged out → Landing ──────────────────────────────────────
  if (!session || !user) {
    return <Landing />
  }

  if (membershipsQuery.isLoading) return <Spinner />

  const leagues = membershipsQuery.data ?? []

  // ── Zero memberships → Lobby ───────────────────────────────────
  if (leagues.length === 0) {
    return <Lobby />
  }

  // ── One league → straight in ───────────────────────────────────
  if (leagues.length === 1) {
    return <Navigate to={`/leagues/${leagues[0].slug}`} replace />
  }

  // ── Multiple leagues → picker ──────────────────────────────────
  return <LeaguePicker leagues={leagues} />
}
