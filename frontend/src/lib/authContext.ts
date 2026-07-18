import { createContext, useContext } from 'react'
import type { Session, User } from '@supabase/supabase-js'

/**
 * App-level auth state (P-5). Session handling used to live inside
 * `WeeklyRecapTab`; it now lives in `AuthProvider` and is read through these
 * hooks so any surface (nav, gated routes, publishing desk) shares one session.
 */
export interface AuthState {
  /** Current Supabase session, or null when signed out. */
  session: Session | null
  /** Convenience accessor for `session.user`. */
  user: User | null
  /** True until the initial session lookup resolves. */
  loading: boolean
  /** False when Supabase env vars are absent (offline/dev/CI). */
  configured: boolean
  /** Sign the current user out. No-op when Supabase is unconfigured. */
  signOut: () => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (ctx === null) {
    throw new Error('useAuth must be used within an <AuthProvider>')
  }
  return ctx
}

/** The current session, or null. Spec's canonical accessor (§6). */
export function useSession(): Session | null {
  return useAuth().session
}

/** The current access token, or '' when signed out. */
export function useAccessToken(): string {
  return useAuth().session?.access_token ?? ''
}
