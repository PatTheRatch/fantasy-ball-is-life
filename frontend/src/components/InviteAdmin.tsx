import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Copy } from 'lucide-react'
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
 * Gated on is_league_admin(league_id) RPC — note the client gate is UX only;
 * the real boundary is RLS ("Admins manage their league invites" and the
 * member DELETE policy), so a bypassed gate still can't read or write.
 *
 * Data goes through react-query rather than useEffect + setState: setting
 * state synchronously inside an effect trips react-hooks/set-state-in-effect
 * and causes cascading renders.
 */
export function InviteAdmin({ leagueId }: { leagueId: string }) {
  const queryClient = useQueryClient()
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  const [copiedId, setCopiedId] = useState<string | null>(null)

  async function copyLink(inviteId: string, url: string) {
    await navigator.clipboard.writeText(url)
    setCopiedId(inviteId)
    setTimeout(() => setCopiedId((current) => (current === inviteId ? null : current)), 1500)
  }

  const adminQuery = useQuery({
    queryKey: ['is-league-admin', leagueId],
    retry: false,
    queryFn: async () => {
      if (!supabase) return false
      const { data } = await supabase.rpc('is_league_admin', {
        target_league_id: leagueId,
      })
      return Boolean(data)
    },
  })

  const isAdmin = adminQuery.data === true

  const invitesQuery = useQuery({
    queryKey: ['league-invites', leagueId],
    enabled: isAdmin,
    retry: false,
    queryFn: async () => {
      if (!supabase) return [] as InviteRow[]
      const { data } = await supabase
        .from('league_invites')
        .select('id,token,email,role,expires_at,created_at,used_at')
        .eq('league_id', leagueId)
        .is('used_at', null)
        .order('created_at', { ascending: false })
      return (data as InviteRow[]) ?? []
    },
  })

  const membersQuery = useQuery({
    queryKey: ['league-members', leagueId],
    enabled: isAdmin,
    retry: false,
    queryFn: async () => {
      if (!supabase) return [] as MemberRow[]
      const { data } = await supabase
        .from('league_memberships')
        .select('user_id,role,team_name,created_at')
        .eq('league_id', leagueId)
        .order('created_at', { ascending: true })
      return (data as MemberRow[]) ?? []
    },
  })

  const invites = invitesQuery.data ?? []
  const members = membersQuery.data ?? []

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
    await queryClient.invalidateQueries({ queryKey: ['league-invites', leagueId] })
  }

  async function revokeInvite(inviteId: string) {
    if (!supabase) return
    await supabase.from('league_invites').delete().eq('id', inviteId)
    await queryClient.invalidateQueries({ queryKey: ['league-invites', leagueId] })
  }

  async function removeMember(userId: string) {
    if (!supabase) return
    await supabase
      .from('league_memberships')
      .delete()
      .eq('league_id', leagueId)
      .eq('user_id', userId)
    await queryClient.invalidateQueries({ queryKey: ['league-members', leagueId] })
  }

  if (adminQuery.isLoading) return null
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
                  onClick={() => copyLink(inv.id, link(inv.token))}
                  className="flex flex-shrink-0 items-center gap-1 text-xs font-semibold text-pg-accent hover:underline"
                >
                  {copiedId === inv.id ? (
                    <>
                      <Check className="h-3 w-3" aria-hidden /> Copied
                    </>
                  ) : (
                    <>
                      <Copy className="h-3 w-3" aria-hidden /> Copy
                    </>
                  )}
                </button>
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
