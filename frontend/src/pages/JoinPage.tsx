import { useEffect, useState } from 'react'
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
  const [redeeming, setRedeeming] = useState(false)

  const token = searchParams.get('invite')

  useEffect(() => {
    if (!token) {
      setError('No invite link found. Ask your league admin for a valid invite.')
      return
    }
    if (loading) return

    if (!session || !user) {
      // Not signed in — redirect to login preserving the token
      navigate(`/login?next=/join?invite=${encodeURIComponent(token)}`, { replace: true })
      return
    }

    // Signed in — redeem
    if (redeeming) return
    setRedeeming(true)

    async function redeem() {
      if (!supabase) return
      const { error: redeemErr } = await supabase.rpc('redeem_league_invite', {
        p_token: token,
      })

      if (redeemErr) {
        setError(redeemErr.message)
        setRedeeming(false)
        return
      }

      // Redirect to the league home
      navigate('/', { replace: true })
    }

    void redeem()
  }, [token, session, user, loading, navigate, redeeming])

  if (!token) {
    return (
      <div className="mx-auto max-w-md pt-16 text-center">
        <p className="text-lg text-red-400">{error}</p>
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
