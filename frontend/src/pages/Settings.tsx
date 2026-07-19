import { useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getPublishedArchive, getSnapshot } from '../api'
import { useAuth } from '../lib/authContext'
import { claimTeam, getMyLeagues, type MyLeague } from '../lib/memberships'
import { supabase } from '../lib/supabase'
import { InviteAdmin } from '../components/InviteAdmin'

const RECAP_SEASON = Number(import.meta.env.VITE_RECAP_SEASON ?? 2026)

/**
 * P-6b: claim "which team is mine" per league (spec §8). League Home uses the
 * claim to pin your matchup. Team options come from the latest snapshot's
 * standings; the claim writes `league_memberships.team_name` (the only
 * member-writable column — see migration 20260718070000).
 */
function TeamClaim({ league, userId }: { league: MyLeague; userId: string }) {
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string>(league.teamName ?? '')
  const [status, setStatus] = useState<{
    kind: 'error' | 'ok'
    message: string
  } | null>(null)
  const [saving, setSaving] = useState(false)

  const teamsQuery = useQuery({
    queryKey: ['settings', 'teams', league.slug],
    queryFn: async () => {
      const archive = await getPublishedArchive(league.slug, RECAP_SEASON)
      const week = archive.length > 0 ? archive[archive.length - 1].week : 1
      const { snapshot } = await getSnapshot(league.slug, RECAP_SEASON, week)
      const standings = (snapshot as Record<string, unknown>).standings
      if (!Array.isArray(standings)) return []
      return [
        ...new Set(
          standings
            .map((s) => String((s as Record<string, unknown>).team_name ?? ''))
            .filter(Boolean),
        ),
      ]
    },
    retry: false,
  })

  const save = async () => {
    setSaving(true)
    setStatus(null)
    try {
      await claimTeam(league.leagueId, userId, selected || null)
      await queryClient.invalidateQueries({ queryKey: ['my-leagues'] })
      setStatus({ kind: 'ok', message: 'Team claimed.' })
    } catch (error) {
      setStatus({
        kind: 'error',
        message: error instanceof Error ? error.message : 'Could not save.',
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-400">{league.name}</p>
      {teamsQuery.isLoading ? (
        <p className="text-sm text-slate-500">Loading teams…</p>
      ) : (
        <div className="flex flex-wrap gap-3">
          <select
            value={selected}
            onChange={(event) => setSelected(event.target.value)}
            className="min-h-11 flex-1 rounded-lg border border-pg-border bg-pg-bg px-3 text-sm text-white outline-none focus:border-pg-accent"
          >
            <option value="">— No team claimed —</option>
            {(teamsQuery.data ?? []).map((team) => (
              <option key={team} value={team}>
                {team}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={saving}
            onClick={() => void save()}
            className="min-h-11 rounded-lg bg-pg-accent px-4 text-sm font-bold text-white disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}
      {status && (
        <p
          className={`text-sm ${
            status.kind === 'error' ? 'text-pg-negative' : 'text-pg-positive'
          }`}
        >
          {status.message}
        </p>
      )}
    </div>
  )
}

function InviteAdminSection() {
  const { user } = useAuth()
  const membershipsQuery = useQuery({
    queryKey: ['my-leagues', user?.id],
    queryFn: () => getMyLeagues(user!.id),
    enabled: Boolean(user),
    retry: false,
  })

  if (membershipsQuery.isLoading || !membershipsQuery.data) return null

  return (
    <>
      {membershipsQuery.data.map((m) => (
        <InviteAdmin key={m.leagueId} leagueId={m.leagueId} />
      ))}
    </>
  )
}

function MyTeamSection() {
  const { user } = useAuth()
  const membershipsQuery = useQuery({
    queryKey: ['my-leagues', user?.id],
    queryFn: () => getMyLeagues(user!.id),
    enabled: Boolean(user),
    retry: false,
  })

  return (
    <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
      <h2 className="mb-1 font-semibold text-white">My team</h2>
      <p className="mb-4 text-sm text-slate-500">
        Claim your fantasy team so League Home can pin your matchup.
      </p>
      {membershipsQuery.isLoading ? (
        <p className="text-sm text-slate-500">Loading…</p>
      ) : (membershipsQuery.data ?? []).length === 0 ? (
        <p className="text-sm text-slate-500">
          No league membership found for your account — ask your league admin
          to add you.
        </p>
      ) : (
        <div className="space-y-5">
          {membershipsQuery.data!.map((league) => (
            <TeamClaim key={league.leagueId} league={league} userId={user!.id} />
          ))}
        </div>
      )}
    </section>
  )
}

/**
 * Account settings (P-5). Reached from the profile menu; gated by RequireAuth.
 * Lets a signed-in user change their password directly (they already hold a
 * session, so no email round-trip) and sign out.
 */
export function Settings() {
  const { user, signOut } = useAuth()
  const [password, setPassword] = useState('')
  const [status, setStatus] = useState<{
    kind: 'error' | 'ok'
    message: string
  } | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const changePassword = async (event: FormEvent) => {
    event.preventDefault()
    if (!supabase) return
    setSubmitting(true)
    setStatus(null)
    const { error } = await supabase.auth.updateUser({ password })
    setSubmitting(false)
    if (error) {
      setStatus({ kind: 'error', message: error.message })
      return
    }
    setPassword('')
    setStatus({ kind: 'ok', message: 'Password updated.' })
  }

  return (
    <div className="mx-auto max-w-lg space-y-6">
      <h1 className="text-2xl font-bold text-white">Account</h1>

      <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
        <p className="text-sm text-slate-400">Signed in as</p>
        <p className="font-medium text-white">{user?.email}</p>
      </section>

      <MyTeamSection />

      <InviteAdminSection />

      <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
        <h2 className="mb-4 font-semibold text-white">Change password</h2>
        <form
          className="space-y-3"
          onSubmit={(event) => void changePassword(event)}
        >
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            placeholder="New password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="min-h-11 w-full rounded-lg border border-pg-border bg-pg-bg px-3 text-sm text-white outline-none focus:border-pg-accent"
          />
          {status && (
            <p
              className={`text-sm ${
                status.kind === 'error'
                  ? 'text-pg-negative'
                  : 'text-pg-positive'
              }`}
            >
              {status.message}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="min-h-11 rounded-lg bg-pg-accent px-4 text-sm font-bold text-white disabled:opacity-50"
          >
            {submitting ? 'Saving…' : 'Update password'}
          </button>
        </form>
      </section>

      <button
        type="button"
        onClick={() => void signOut()}
        className="text-sm font-semibold text-slate-400 transition-colors hover:text-white"
      >
        Sign out
      </button>
    </div>
  )
}
