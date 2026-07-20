import { useEffect, useRef, useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import { useAuth } from '../lib/authContext'

/**
 * N-2b: /join?invite=<token> — redeem an invite and land in the league.
 * Signed in → call redeem RPC → redirect to league home.
 * Not signed in → send to /login with a next param so the invite
 * survives the round-trip.
 */
export function JoinPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const { session, user, loading } = useAuth()
  const [error, setError] = useState<string | null>(null)
  // Re-entrancy guard only — never affects render, so a ref (not state)
  // keeps it out of the effect's setState path and its dep array.
  const attemptedRef = useRef(false)

  const token = searchParams.get('invite')

  useEffect(() => {
    // A missing token is derivable from the URL — render it directly below
    // rather than writing state here (react-hooks/set-state-in-effect).
    if (!token) return
    if (loading) return
    if (error) return  // N-2b: don't retry after a failed redeem

    if (!session || !user) {
      // Not signed in — redirect to login preserving the token
      navigate(`/login?next=${encodeURIComponent('/join?invite=' + token)}`, { replace: true })
      return
    }

    // Signed in — redeem exactly once
    if (attemptedRef.current) return
    attemptedRef.current = true

    async function redeem() {
      if (!supabase) return
      const { error: redeemErr } = await supabase.rpc('redeem_league_invite', {
        p_token: token,
      })

      if (redeemErr) {
        // setState here is after an await (not synchronous in the effect
        // body), and attemptedRef stays true so this never retries.
        setError(redeemErr.message)
        return
      }

      // Navigate to the league we just joined
      navigate('/', { replace: true })
    }

    void redeem()
  }, [token, session, user, loading, navigate, error])

  if (!token) {
    return (
      <div className="mx-auto max-w-md pt-16 text-center">
        <p className="text-lg text-red-400">
          No invite link found. Ask your league admin for a valid invite.
        </p>
        <Link to="/" className="mt-4 inline-block text-sm font-semibold text-pg-accent hover:underline">
          Back to Full Court Press
        </Link>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mx-auto max-w-md pt-16 text-center">
        <p className="text-lg text-red-400">{error}</p>
        <Link to="/" className="mt-4 inline-block text-sm font-semibold text-pg-accent hover:underline">
          Back to Full Court Press
        </Link>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-md pt-16 text-center">
      <p className="text-slate-400">Redeeming your invite…</p>
    </div>
  )
}
