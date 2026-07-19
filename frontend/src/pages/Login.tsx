import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../lib/authContext'
import { supabase } from '../lib/supabase'
import {
  AuthShell,
  authButtonClass,
  authInputClass,
} from '../components/AuthShell'

interface LocationState {
  from?: string
}

export function Login() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const { session, loading, configured } = useAuth()
  // Default to '/' (not a hardcoded page) so "home" stays defined in one place
  // — the router's index redirect. RequireAuth supplies an explicit `from`.
  // N-2b: /join?invite= redirects here with ?next= — honor it.
  const from = searchParams.get('next') ?? (location.state as LocationState | null)?.from ?? '/'

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!supabase) {
      setError('Sign-in is not configured in this environment.')
      return
    }
    setSubmitting(true)
    setError(null)
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email,
      password,
    })
    setSubmitting(false)
    if (signInError) {
      setError(signInError.message)
      return
    }
    navigate(from, { replace: true })
  }

  // Already signed in — bounce to the intended destination.
  if (!loading && session) {
    return <Navigate to={from} replace />
  }

  return (
    <AuthShell
      title="Sign in"
      subtitle="Access your league's tools and publishing desk."
      footer={
        <>
          Need access?{' '}
          <Link className="font-semibold text-pg-accent" to="/signup">
            Request an account
          </Link>
        </>
      }
    >
      <form className="space-y-4" onSubmit={(event) => void submit(event)}>
        {!configured && (
          <p className="rounded-lg border border-pg-warning/40 bg-pg-warning/10 p-3 text-sm text-pg-warning">
            Supabase is not configured — sign-in is unavailable here.
          </p>
        )}
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
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className={authInputClass}
          />
        </label>
        {error && <p className="text-sm text-pg-negative">{error}</p>}
        <button type="submit" disabled={submitting} className={authButtonClass}>
          {submitting ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="text-center">
          <Link
            to="/reset-password"
            className="text-sm text-slate-400 hover:text-slate-200"
          >
            Forgot password?
          </Link>
        </p>
      </form>
    </AuthShell>
  )
}
