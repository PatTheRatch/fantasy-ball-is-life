/**
 * N-4d: Create-league wizard — two-step flow.
 *
 * Step 1 — Identify: ESPN league ID, season, name, optional cookies.
 *   "Check league" → getLeaguePreview → shows confirmation.
 * Step 2 — Confirm & claim: optional team pick from previewed names,
 *   "Create league" → createLeague → redirect to /leagues/{slug}.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  createLeague,
  formatApiError,
  getLeaguePreview,
  type CreatedLeague,
  type LeaguePreview,
} from '../api'
import { useAccessToken } from '../lib/authContext'

type Step = 'identify' | 'confirm'

interface FormState {
  espn_league_id: string
  season: string
  name: string
  swid: string
  espn_s2: string
  team_name: string
  showCookies: boolean
}

const EMPTY_FORM: FormState = {
  espn_league_id: '',
  season: String(new Date().getFullYear()),
  name: '',
  swid: '',
  espn_s2: '',
  team_name: '',
  showCookies: false,
}

/** Map backend error codes to friendly messages. */
function friendlyError(code: string): string {
  switch (code) {
    case 'private_league':
      return 'This league is private — add your ESPN SWID and ESPN_S2 cookies below.'
    case 'bad_cookies':
      return 'ESPN rejected those cookies. Double-check them and try again.'
    case 'not_found':
      return 'No ESPN league found with that ID and season.'
    case 'espn_unavailable':
      return "Couldn't reach ESPN right now. Try again in a moment."
    case 'league_cap_reached':
      return "You've reached the limit of 2 leagues."
    case 'team_taken':
      return 'That team is already claimed.'
    default:
      return ''
  }
}

export function CreateLeagueWizard() {
  const token = useAccessToken()
  const navigate = useNavigate()

  const [step, setStep] = useState<Step>('identify')
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [loading, setLoading] = useState(false)
  const [preview, setPreview] = useState<LeaguePreview | null>(null)
  const [error, setError] = useState<string | null>(null)

  const set = (field: keyof FormState, value: string | boolean) =>
    setForm((f) => ({ ...f, [field]: value }))

  function clearError() {
    setError(null)
  }

  // ── Step 1: Identify ──────────────────────────────────────────────────

  async function checkLeague(e: React.FormEvent) {
    e.preventDefault()
    clearError()

    const id = Number(form.espn_league_id)
    const season = Number(form.season)
    if (!id || !season || !form.name.trim()) {
      setError('Please fill in the league ID, season, and a name.')
      return
    }

    setLoading(true)
    try {
      const result = await getLeaguePreview(token, {
        espn_league_id: id,
        season,
        swid: form.showCookies ? form.swid || undefined : undefined,
        espn_s2: form.showCookies ? form.espn_s2 || undefined : undefined,
      })
      setPreview(result)
      setStep('confirm')
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: { code?: string; message?: string } } } })
        ?.response?.data?.detail
      const code = detail?.code ?? ''
      const mapped = friendlyError(code)
      if (mapped) {
        setError(mapped)
        if (code === 'private_league') {
          setForm((f) => ({ ...f, showCookies: true }))
        }
      } else {
        setError(detail?.message ?? formatApiError(err))
      }
    } finally {
      setLoading(false)
    }
  }

  // ── Step 2: Confirm & create ──────────────────────────────────────────

  async function doCreate(e: React.FormEvent) {
    e.preventDefault()
    clearError()
    setLoading(true)

    try {
      const created: CreatedLeague = await createLeague(token, {
        espn_league_id: Number(form.espn_league_id),
        season: Number(form.season),
        name: form.name.trim(),
        swid: form.showCookies ? form.swid || undefined : undefined,
        espn_s2: form.showCookies ? form.espn_s2 || undefined : undefined,
        team_name: form.team_name || undefined,
      })
      navigate(`/leagues/${created.slug}`, { replace: true })
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: { code?: string; message?: string } } } })
        ?.response?.data?.detail
      const code = detail?.code ?? ''
      const mapped = friendlyError(code)
      setError(mapped || detail?.message || formatApiError(err))
      setLoading(false)
    }
  }

  function backToIdentify() {
    setStep('identify')
    setPreview(null)
    clearError()
  }

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div className="mx-auto max-w-md space-y-6 pt-8">
      <h1 className="text-2xl font-bold text-white">Create a league</h1>

      {step === 'identify' && (
        <form onSubmit={checkLeague} className="space-y-4">
          <div className="rounded-pg-lg border border-pg-border bg-pg-card p-5 space-y-4">
            <label className="block">
              <span className="text-sm font-semibold text-slate-300">ESPN League ID</span>
              <input
                type="number"
                value={form.espn_league_id}
                onChange={(e) => { set('espn_league_id', e.target.value); clearError() }}
                className="mt-1.5 w-full rounded-lg border border-pg-border bg-pg-bg px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-pg-accent focus:outline-none"
                placeholder="e.g. 1234567"
                required
              />
            </label>

            <label className="block">
              <span className="text-sm font-semibold text-slate-300">Season</span>
              <input
                type="number"
                value={form.season}
                onChange={(e) => { set('season', e.target.value); clearError() }}
                className="mt-1.5 w-full rounded-lg border border-pg-border bg-pg-bg px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-pg-accent focus:outline-none"
                required
              />
            </label>

            <label className="block">
              <span className="text-sm font-semibold text-slate-300">League name</span>
              <input
                type="text"
                value={form.name}
                onChange={(e) => { set('name', e.target.value); clearError() }}
                className="mt-1.5 w-full rounded-lg border border-pg-border bg-pg-bg px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-pg-accent focus:outline-none"
                placeholder="My Fantasy League"
                required
              />
            </label>

            {/* Private league cookie fields */}
            <button
              type="button"
              onClick={() => set('showCookies', !form.showCookies)}
              className="text-xs text-pg-accent hover:underline"
            >
              {form.showCookies ? '−' : '+'} Private league? (add ESPN cookies)
            </button>

            {form.showCookies && (
              <div className="space-y-3 border-l-2 border-pg-accent/30 pl-3">
                <p className="text-xs text-slate-500">
                  Find these in your browser's cookies for ESPN.com. Leave blank for public leagues.
                </p>
                <label className="block">
                  <span className="text-xs font-semibold text-slate-400">SWID</span>
                  <input
                    type="text"
                    value={form.swid}
                    onChange={(e) => { set('swid', e.target.value); clearError() }}
                    className="mt-1 w-full rounded-lg border border-pg-border bg-pg-bg px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-pg-accent focus:outline-none"
                    placeholder="{…}"
                  />
                </label>
                <label className="block">
                  <span className="text-xs font-semibold text-slate-400">ESPN S2</span>
                  <input
                    type="text"
                    value={form.espn_s2}
                    onChange={(e) => { set('espn_s2', e.target.value); clearError() }}
                    className="mt-1 w-full rounded-lg border border-pg-border bg-pg-bg px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-pg-accent focus:outline-none"
                    placeholder="AEA…"
                  />
                </label>
              </div>
            )}

            {error && (
              <p className="rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-400">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full rounded-lg bg-pg-accent px-4 py-2.5 text-sm font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              {loading ? 'Checking…' : 'Check league'}
            </button>
          </div>
        </form>
      )}

      {step === 'confirm' && preview && (
        <form onSubmit={doCreate} className="space-y-4">
          <div className="rounded-pg-lg border border-pg-border bg-pg-card p-5 space-y-3">
            <div>
              <span className="text-xs font-bold uppercase tracking-wider text-slate-500">League found</span>
              <h2 className="text-lg font-bold text-white">{preview.name}</h2>
              <p className="text-sm text-slate-400">
                {preview.teams} teams · {preview.scoring_type} · {preview.season}
              </p>
            </div>

            <p className="text-sm text-slate-300">Is this your league?</p>
          </div>

          {/* Team picker (optional) */}
          {preview.team_names.length > 0 && (
            <div className="rounded-pg-lg border border-pg-border bg-pg-card p-5 space-y-3">
              <span className="text-xs font-bold uppercase tracking-wider text-slate-500">
                Which team is yours? <span className="font-normal normal-case tracking-normal text-slate-600">(optional)</span>
              </span>
              <select
                value={form.team_name}
                onChange={(e) => { set('team_name', e.target.value); clearError() }}
                className="w-full rounded-lg border border-pg-border bg-pg-bg px-3 py-2 text-sm text-white focus:border-pg-accent focus:outline-none"
              >
                <option value="">Skip for now</option>
                {preview.team_names.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </div>
          )}

          {error && (
            <p className="rounded-md bg-red-500/10 px-3 py-2 text-sm text-red-400">{error}</p>
          )}

          <div className="flex gap-3">
            <button
              type="button"
              onClick={backToIdentify}
              className="rounded-lg border border-pg-border px-4 py-2.5 text-sm font-semibold text-slate-300 hover:bg-pg-card-hover"
            >
              Back
            </button>
            <button
              type="submit"
              disabled={loading}
              className="flex-1 rounded-lg bg-pg-accent px-4 py-2.5 text-sm font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              {loading ? 'Creating…' : 'Create league'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
