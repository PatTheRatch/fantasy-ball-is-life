import { useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Session } from '@supabase/supabase-js'
import { supabase } from './supabase'
import { AuthContext, type AuthState } from './authContext'

/**
 * Provides the app-level Supabase session (P-5). Mounted once in `main.tsx`
 * around the router. Subscribes to `onAuthStateChange` so sign-in, sign-out,
 * token refresh, and password-recovery redirects all propagate everywhere.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null)
  // Nothing to load when Supabase isn't configured — settle immediately so
  // gated routes don't hang on a loading spinner forever.
  const [loading, setLoading] = useState<boolean>(supabase !== null)

  useEffect(() => {
    if (!supabase) return
    let active = true

    void supabase.auth.getSession().then(({ data }) => {
      if (!active) return
      setSession(data.session)
      setLoading(false)
    })

    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession)
      setLoading(false)
    })

    return () => {
      active = false
      data.subscription.unsubscribe()
    }
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      session,
      user: session?.user ?? null,
      loading,
      configured: supabase !== null,
      signOut: async () => {
        await supabase?.auth.signOut()
      },
    }),
    [session, loading],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
