import { useState, type FormEvent } from 'react'
import { useAuth } from '../lib/authContext'
import { supabase } from '../lib/supabase'

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
