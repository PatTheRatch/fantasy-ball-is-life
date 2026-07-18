import { useState, type FormEvent } from 'react'
import { Link, Navigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../lib/authContext'
import { supabase } from '../lib/supabase'
import {
  AuthShell,
  authButtonClass,
  authInputClass,
} from '../components/AuthShell'

// P-5 §6: public self-serve signup is deferred until the launch decision.
// Until then /signup is invite-only — the form is revealed only when an
// `?invite=` token is present in the URL. The `league_memberships` row that
// grants league access is provisioned separately (see supabase/README).
// Flip VITE_SIGNUP_OPEN=true to open public registration; the page and table
// are ready either way.
const SIGNUP_OPEN =
  String(import.meta.env.VITE_SIGNUP_OPEN ?? '').toLowerCase() === 'true'

export function Signup() {
  const { session, loading } = useAuth()
  const [params] = useSearchParams()
  const hasInvite = (params.get('invite') ?? '').trim() !== ''

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [done, setDone] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!supabase) {
      setError('Sign-up is not configured in this environment.')
      return
    }
    setSubmitting(true)
    setError(null)
    const { error: signUpError } = await supabase.auth.signUp({
      email,
      password,
    })
    setSubmitting(false)
    if (signUpError) {
      setError(signUpError.message)
      return
    }
    setDone(true)
  }

  if (!loading && session) {
    return <Navigate to="/" replace />
  }

  if (!SIGNUP_OPEN && !hasInvite) {
    return (
      <AuthShell
        title="Invite only"
        subtitle="Sign-ups are limited to invited league members."
        footer={
          <Link className="font-semibold text-pg-accent" to="/login">
            Back to sign in
          </Link>
        }
      >
        <p className="text-sm text-slate-300">
          Ask your league admin for an invite link to create an account.
        </p>
      </AuthShell>
    )
  }

  if (done) {
    return (
      <AuthShell
        title="Check your email"
        subtitle="We sent a confirmation link to finish creating your account."
        footer={
          <Link className="font-semibold text-pg-accent" to="/login">
            Back to sign in
          </Link>
        }
      >
        <p className="text-sm text-slate-300">
          Once confirmed, sign in with your email and password.
        </p>
      </AuthShell>
    )
  }

  return (
    <AuthShell
      title="Create your account"
      subtitle="Set a password to join your league."
      footer={
        <>
          Already have an account?{' '}
          <Link className="font-semibold text-pg-accent" to="/login">
            Sign in
          </Link>
        </>
      }
    >
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
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-300">
            Password
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
        <button type="submit" disabled={submitting} className={authButtonClass}>
          {submitting ? 'Creating…' : 'Create account'}
        </button>
      </form>
    </AuthShell>
  )
}
