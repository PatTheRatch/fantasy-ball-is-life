import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { supabase } from '../lib/supabase'
import {
  AuthShell,
  authButtonClass,
  authInputClass,
} from '../components/AuthShell'

/** Step 1 of Supabase's built-in password reset: email a recovery link. */
export function ResetPassword() {
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [sent, setSent] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!supabase) {
      setError('Password reset is not configured in this environment.')
      return
    }
    setSubmitting(true)
    setError(null)
    const { error: resetError } = await supabase.auth.resetPasswordForEmail(
      email,
      { redirectTo: `${window.location.origin}/update-password` },
    )
    setSubmitting(false)
    if (resetError) {
      setError(resetError.message)
      return
    }
    setSent(true)
  }

  return (
    <AuthShell
      title="Reset password"
      subtitle={sent ? undefined : 'We’ll email you a link to set a new password.'}
      footer={
        <Link className="font-semibold text-pg-accent" to="/login">
          Back to sign in
        </Link>
      }
    >
      {sent ? (
        <p className="text-sm text-slate-300">
          If an account exists for {email}, a reset link is on its way.
        </p>
      ) : (
        <form className="space-y-4" onSubmit={(event) => void submit(event)}>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-300">
              Email
            </span>
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              className={authInputClass}
            />
          </label>
          {error && <p className="text-sm text-pg-negative">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className={authButtonClass}
          >
            {submitting ? 'Sending…' : 'Send reset link'}
          </button>
        </form>
      )}
    </AuthShell>
  )
}
