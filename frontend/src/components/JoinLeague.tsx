import { useState } from 'react'
import { Link } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import { useAuth } from '../lib/authContext'

type Team = { id: number; name: string; ownerName: string | null }

/**
 * N-2: Join-a-league flow. Shown on public league pages to signed-in
 * non-members. Picks an unclaimed ESPN team, claims it via the self-join
 * INSERT policy on league_memberships.
 */
export function JoinLeague({
  leagueId,
  leagueSlug,
  teams,
  onJoined,
}: {
  leagueId: string
  leagueSlug: string
  teams: Team[]
  onJoined: () => void
}) {
  const { user } = useAuth()
  const [picking, setPicking] = useState(false)
  const [selected, setSelected] = useState<Team | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [joining, setJoining] = useState(false)

  const unclaimed = teams.filter((t) => !t.ownerName)

  async function claim() {
    if (!selected || !user) return
    setJoining(true)
    setError(null)

    const { error: insertErr } = await supabase!.from('league_memberships').insert({
      league_id: leagueId,
      user_id: user.id,
      role: 'member',
      team_name: selected.name,
    })

    if (insertErr) {
      const msg = insertErr.message.toLowerCase()
      if (msg.includes('duplicate') || msg.includes('unique')) {
        if (msg.includes('team')) {
          setError('That team was just claimed by someone else. Pick another.')
        } else {
          setError('You are already a member of this league.')
        }
      } else {
        setError(insertErr.message)
      }
      setJoining(false)
      return
    }

    onJoined()
  }

  if (!user) {
    return (
      <div className="rounded-pg-lg border border-pg-border bg-pg-card p-5 text-center">
        <p className="text-sm text-slate-400">
          <Link to="/login" className="font-semibold text-pg-accent hover:underline">
            Log in
          </Link>{' '}
          or{' '}
          <Link to="/signup" className="font-semibold text-pg-accent hover:underline">
            sign up
          </Link>{' '}
          to join this league.
        </p>
      </div>
    )
  }

  if (!picking) {
    return (
      <div className="rounded-pg-lg border border-pg-border bg-pg-card p-5 text-center">
        <p className="text-sm text-slate-300">
          This is a public league — anyone can join by claiming a team.
        </p>
        <button
          onClick={() => setPicking(true)}
          className="mt-3 inline-flex items-center gap-2 rounded-lg bg-pg-accent px-5 py-2.5 text-sm font-bold text-white transition-opacity hover:opacity-90"
        >
          Join this league
        </button>
      </div>
    )
  }

  return (
    <div className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
      <h3 className="mb-3 text-sm font-bold uppercase tracking-wider text-slate-400">
        Claim your team
      </h3>
      {unclaimed.length === 0 ? (
        <p className="text-sm text-slate-500">All teams are claimed.</p>
      ) : (
        <>
          <ul className="max-h-48 space-y-1 overflow-y-auto">
            {unclaimed.map((t) => (
              <li key={t.id}>
                <button
                  onClick={() => { setSelected(t); setError(null) }}
                  className={`w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${
                    selected?.id === t.id
                      ? 'bg-pg-accent/20 text-white'
                      : 'text-slate-300 hover:bg-pg-card-hover'
                  }`}
                >
                  {t.name}
                </button>
              </li>
            ))}
          </ul>
          {error && (
            <p className="mt-3 text-sm text-red-400">{error}</p>
          )}
          <button
            onClick={claim}
            disabled={!selected || joining}
            className="mt-4 w-full rounded-lg bg-pg-accent px-4 py-2.5 text-sm font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            {joining ? 'Claiming…' : `Claim as ${selected?.name ?? '…'}`}
          </button>
        </>
      )}
    </div>
  )
}
