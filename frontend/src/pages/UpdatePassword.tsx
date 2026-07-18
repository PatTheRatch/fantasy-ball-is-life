import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/authContext'
import { supabase } from '../lib/supabase'
import {
  AuthShell,
  authButtonClass,
  authInputClass,
} from '../components/AuthShell'

/**
 * Step 2 of Supabase's built-in password reset. The recovery link lands here;
 * `detectSessionInUrl` establishes a recovery session, then the user sets a
 * new password via `updateUser`.
 */
export function UpdatePassword() {
  const navigate = useNavigate()
  const { session, loading } = useAuth()
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!supabase) {
      setError('Password update is not configured in this environment.')
      return
    }
    setSubmitting(true)
    setError(null)
    const { error: updateError } = await supabase.auth.updateUser({ password })
    setSubmitting(false)
    if (updateError) {
      setError(updateError.message)
      return
    }
    navigate('/', { replace: true })
  }

  return (
    <AuthShell
      title="Set a new password"
      footer={
        <Link className="font-semibold text-pg-accent" to="/login">
          Back to sign in
        </Link>
      }
    >
      {!loading && !session ? (
        <p className="text-sm text-slate-300">
          This reset link is invalid or has expired. Request a new one from the{' '}
          <Link className="font-semibold text-pg-accent" to="/reset-password">
            reset page
          </Link>
          .
        </p>
      ) : (
        <form className="space-y-4" onSubmit={(event) => void submit(event)}>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-300">
              New password
            </span>
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className={authInputClass}
            />
          </label>
          {error && <p className="text-sm text-pg-negative">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className={authButtonClass}
          >
            {submitting ? 'Saving…' : 'Update password'}
          </button>
        </form>
      )}
    </AuthShell>
  )
}
