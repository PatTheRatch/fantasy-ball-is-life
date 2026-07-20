import { useState, useEffect, useCallback } from 'react'
import { supabase } from '../lib/supabase'

type InviteRow = {
  id: string
  token: string
  email: string | null
  role: string
  expires_at: string | null
  created_at: string
  used_at: string | null
}

type MemberRow = {
  user_id: string
  role: string
  team_name: string | null
  created_at: string
}

/**
 * N-2b: Admin invite management + member list section.
 * Gated on is_league_admin(league_id) RPC.
 */
export function InviteAdmin({ leagueId }: { leagueId: string }) {
  const [isAdmin, setIsAdmin] = useState(false)
  const [invites, setInvites] = useState<InviteRow[]>([])
  const [members, setMembers] = useState<MemberRow[]>([])
  const [loading, setLoading] = useState(true)

  const origin = typeof window !== 'undefined' ? window.location.origin : ''

  const fetchAdmin = useCallback(async () => {
    if (!supabase) return
    const { data } = await supabase.rpc('is_league_admin', { target_league_id: leagueId })
    setIsAdmin(Boolean(data))
    setLoading(false)
  }, [leagueId])

  const fetchInvites = useCallback(async () => {
    if (!supabase || !isAdmin) return
    const { data } = await supabase
      .from('league_invites')
      .select('id,token,email,role,expires_at,created_at,used_at')
      .eq('league_id', leagueId)
      .is('used_at', null)
      .order('created_at', { ascending: false })
    setInvites((data as InviteRow[]) ?? [])
  }, [leagueId, isAdmin])

  const fetchMembers = useCallback(async () => {
    if (!supabase || !isAdmin) return
    const { data } = await supabase
      .from('league_memberships')
      .select('user_id,role,team_name,created_at')
      .eq('league_id', leagueId)
      .order('created_at', { ascending: true })
    setMembers((data as MemberRow[]) ?? [])
  }, [leagueId, isAdmin])

  useEffect(() => { fetchAdmin() }, [fetchAdmin])
  useEffect(() => { if (isAdmin) { fetchInvites(); fetchMembers() } }, [isAdmin, fetchInvites, fetchMembers])

  async function createInvite(role: string, expiresDays: number) {
    if (!supabase || !isAdmin) return
    const token = crypto.randomUUID() + crypto.randomUUID()
    const expiresAt = new Date(Date.now() + expiresDays * 86400000).toISOString()
    const { data: userData } = await supabase.auth.getUser()
    await supabase.from('league_invites').insert({
      league_id: leagueId,
      token,
      role,
      expires_at: expiresAt,
      created_by: userData.user?.id,
    })
    fetchInvites()
  }

  async function revokeInvite(inviteId: string) {
    if (!supabase) return
    await supabase.from('league_invites').delete().eq('id', inviteId)
    fetchInvites()
  }

  async function removeMember(userId: string) {
    if (!supabase) return
    await supabase
      .from('league_memberships')
      .delete()
      .eq('league_id', leagueId)
      .eq('user_id', userId)
    fetchMembers()
  }

  if (loading) return null
  if (!isAdmin) return null

  const link = (token: string) => `${origin}/join?invite=${token}`

  return (
    <div className="space-y-6">
      {/* ── Invites ──────────────────────────────────── */}
      <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
        <h2 className="mb-1 font-semibold text-white">Invite members</h2>
        <p className="mb-3 text-sm text-slate-500">
          Share an invite link — anyone with the link can join.
        </p>
        <div className="flex gap-2">
          <button
            onClick={() => createInvite('member', 7)}
            className="rounded-lg bg-pg-accent px-4 py-2 text-sm font-bold text-white hover:opacity-90"
          >
            New invite (7 days)
          </button>
        </div>
        {invites.length > 0 && (
          <ul className="mt-3 space-y-2">
            {invites.map((inv) => (
              <li key={inv.id} className="flex items-center justify-between gap-2 rounded-md bg-pg-bg px-3 py-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-xs text-slate-300">{link(inv.token)}</p>
                  <p className="text-xs text-slate-500">
                    {inv.role}
                    {inv.expires_at ? ` · expires ${new Date(inv.expires_at).toLocaleDateString()}` : ''}
                  </p>
                </div>
                <button
                  onClick={() => revokeInvite(inv.id)}
                  className="flex-shrink-0 text-xs font-semibold text-red-400 hover:underline"
                >
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* ── Members ──────────────────────────────────── */}
      <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
        <h2 className="mb-1 font-semibold text-white">Members</h2>
        {members.length === 0 ? (
          <p className="text-sm text-slate-500">No members.</p>
        ) : (
          <ul className="mt-2 space-y-1">
            {members.map((m) => (
              <li key={m.user_id} className="flex items-center justify-between gap-2 rounded-md bg-pg-bg px-3 py-2">
                <div>
                  <p className="text-sm text-slate-200">
                    {m.team_name ?? m.user_id.slice(0, 8)}
                    <span className="ml-2 text-xs text-slate-500">{m.role}</span>
                  </p>
                </div>
                <button
                  onClick={() => removeMember(m.user_id)}
                  className="text-xs font-semibold text-red-400 hover:underline"
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
