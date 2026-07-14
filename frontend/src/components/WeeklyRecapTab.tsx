import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { Session } from '@supabase/supabase-js'
import { Copy, LockKeyhole, RefreshCw, Send } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  formatApiError,
  generateRecapDraft,
  getPublishedRecap,
  getRecapEdition,
  getRecapHistory,
  getRecapReadiness,
  publishRecapEdition,
  rollbackRecapEdition,
  type JsonRecord,
  type RecapEdition,
  type RecapGeneratedContent,
} from '../api'
import { MATCHUP_WEEKS_2025_26 } from '../lib/matchupWeeks'
import { supabase } from '../lib/supabase'
import { MatchupVoices } from './MatchupVoices'

function CopyButton({
  label,
  value,
}: {
  label: string
  value: string
}) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    await navigator.clipboard.writeText(value)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1800)
  }
  return (
    <button
      type="button"
      onClick={() => void copy()}
      className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-slate-600 bg-slate-800 px-4 text-sm font-semibold text-white"
    >
      <Copy className="h-4 w-4" />
      {copied ? 'Copied' : label}
    </button>
  )
}

function Narrative({ content }: { content: RecapGeneratedContent }) {
  return (
    <article className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/65">
      <div className="border-b border-slate-800 bg-gradient-to-br from-red-950/50 to-slate-950 px-5 py-8 md:px-8">
        <p className="mb-3 text-xs font-bold uppercase tracking-[0.2em] text-red-400">
          Patriot Games Newsroom
        </p>
        <h2 className="max-w-4xl text-3xl font-black leading-tight text-white md:text-5xl">
          {content.headline}
        </h2>
        <p className="mt-4 max-w-3xl text-base leading-7 text-slate-300">
          {content.intro}
        </p>
      </div>
    </article>
  )
}

function AdminSignIn({
  onSession,
}: {
  onSession: (session: Session | null) => void
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const signIn = async () => {
    if (!supabase) {
      setError('Supabase browser settings are not configured.')
      return
    }
    setLoading(true)
    setError(null)
    const result = await supabase.auth.signInWithPassword({ email, password })
    setLoading(false)
    if (result.error) {
      setError(result.error.message)
      return
    }
    onSession(result.data.session)
  }

  return (
    <div className="rounded-xl border border-amber-700/50 bg-amber-950/20 p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-amber-200">
        <LockKeyhole className="h-4 w-4" />
        Admin sign in
      </div>
      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="Email"
          className="min-h-11 rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm text-white"
        />
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Password"
          className="min-h-11 rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm text-white"
        />
        <button
          type="button"
          disabled={loading || !email || !password}
          onClick={() => void signIn()}
          className="min-h-11 rounded-lg bg-amber-600 px-4 text-sm font-bold text-white disabled:opacity-50"
        >
          {loading ? 'Signing in…' : 'Sign in'}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
    </div>
  )
}

function matchupLabel(row: JsonRecord): string {
  const home = String(row.home_team ?? '')
  const away = String(row.away_team ?? '')
  const homeWins = Number(row.home_category_wins ?? 0)
  const awayWins = Number(row.away_category_wins ?? 0)
  return `${home} ${homeWins}–${awayWins} ${away}`
}

export function WeeklyRecapTab({
  slug,
  season,
  week,
  adminMode,
}: {
  slug: string
  season: number
  week: number
  adminMode: boolean
}) {
  const queryClient = useQueryClient()
  const [session, setSession] = useState<Session | null>(null)
  const [draft, setDraft] = useState<RecapEdition | null>(null)
  const [confirmIncomplete, setConfirmIncomplete] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [working, setWorking] = useState<string | null>(null)

  useEffect(() => {
    if (!supabase) return
    void supabase.auth.getSession().then(({ data }) => setSession(data.session))
    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession)
    })
    return () => data.subscription.unsubscribe()
  }, [])

  useEffect(() => {
    setDraft(null)
    setConfirmIncomplete(false)
    setActionError(null)
  }, [week])

  const dates = MATCHUP_WEEKS_2025_26[week]
  const token = session?.access_token ?? ''
  const publicQuery = useQuery({
    queryKey: ['recap', 'published', slug, season, week],
    queryFn: () => getPublishedRecap(slug, season, week),
    retry: false,
  })
  const readinessQuery = useQuery({
    queryKey: ['recap', 'readiness', slug, season, week],
    queryFn: () =>
      getRecapReadiness(slug, season, week, dates.start, dates.end, token),
    enabled: adminMode && Boolean(token && dates?.start && dates?.end),
    retry: false,
  })
  const historyQuery = useQuery({
    queryKey: ['recap', 'history', slug, season, week],
    queryFn: () => getRecapHistory(slug, season, week, token),
    enabled: adminMode && Boolean(token),
    retry: false,
  })

  const generate = async (generateAnyway: boolean) => {
    if (!dates || !token) return
    setWorking('generate')
    setActionError(null)
    try {
      const edition = await generateRecapDraft(
        slug, season, week, dates.start, dates.end, generateAnyway, token,
      )
      setDraft(edition)
      setConfirmIncomplete(false)
      await queryClient.invalidateQueries({ queryKey: ['recap', 'history'] })
    } catch (error) {
      setActionError(formatApiError(error))
    } finally {
      setWorking(null)
    }
  }

  const previewVersion = async (editionId: string) => {
    if (!token) return
    setWorking(`preview:${editionId}`)
    setActionError(null)
    try {
      const edition = await getRecapEdition(slug, season, week, editionId, token)
      setDraft(edition)
      setConfirmIncomplete(false)
    } catch (error) {
      setActionError(formatApiError(error))
    } finally {
      setWorking(null)
    }
  }

  const publish = async (editionId: string, rollback = false) => {
    if (!token) return
    setWorking(rollback ? `rollback:${editionId}` : 'publish')
    setActionError(null)
    try {
      if (rollback) {
        await rollbackRecapEdition(slug, season, week, editionId, token)
      } else {
        await publishRecapEdition(slug, season, week, editionId, token)
      }
      setDraft(null)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['recap', 'published'] }),
        queryClient.invalidateQueries({ queryKey: ['recap', 'history'] }),
      ])
    } catch (error) {
      setActionError(formatApiError(error))
    } finally {
      setWorking(null)
    }
  }

  const published = publicQuery.data?.edition ?? null
  const preview = adminMode && draft ? draft : published
  const content = preview?.structured_content_json
  const snapshot = preview?.snapshot

  return (
    <div className="space-y-5 pb-8">
      {adminMode && !session && <AdminSignIn onSession={setSession} />}

      {adminMode && session && (
        <section className="space-y-4 rounded-2xl border border-amber-700/40 bg-amber-950/10 p-4 md:p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-bold text-white">Publishing desk</h2>
              <p className="text-sm text-slate-400">Generate Draft → Preview → Publish</p>
            </div>
            <button
              type="button"
              onClick={() => void supabase?.auth.signOut()}
              className="text-xs font-semibold text-slate-400 hover:text-white"
            >
              Sign out
            </button>
          </div>

          {readinessQuery.isLoading && <p className="text-sm text-slate-400">Checking league data…</p>}
          {readinessQuery.error && (
            <p className="text-sm text-red-400">{formatApiError(readinessQuery.error)}</p>
          )}
          {readinessQuery.data && (
            <div
              className={`rounded-xl border p-4 ${
                readinessQuery.data.data_quality.ready
                  ? 'border-emerald-700/50 bg-emerald-950/20'
                  : 'border-amber-600/50 bg-amber-950/30'
              }`}
            >
              <p className="font-semibold text-white">
                {readinessQuery.data.data_quality.ready ? 'Data ready' : 'Data incomplete'}
              </p>
              <div className="mt-2 grid gap-1 text-xs text-slate-300 sm:grid-cols-2">
                {Object.entries(readinessQuery.data.data_quality.checks).map(([label, ok]) => (
                  <span key={label}>{ok ? '✓' : '⚠'} {label.replaceAll('_', ' ')}</span>
                ))}
              </div>
              {readinessQuery.data.data_quality.warnings.length > 0 && (
                <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-amber-200">
                  {readinessQuery.data.data_quality.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              )}
            </div>
          )}

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={Boolean(working) || !readinessQuery.data}
              onClick={() => {
                if (readinessQuery.data?.data_quality.ready) {
                  void generate(false)
                } else {
                  setConfirmIncomplete(true)
                }
              }}
              className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-red-600 px-4 text-sm font-bold text-white disabled:opacity-50"
            >
              <RefreshCw className="h-4 w-4" />
              {working === 'generate' ? 'Generating…' : draft ? 'Refresh Draft' : 'Generate Draft'}
            </button>
            {draft && draft.status === 'draft' && (
              <button
                type="button"
                disabled={Boolean(working)}
                onClick={() => void publish(draft.id)}
                className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-emerald-600 px-4 text-sm font-bold text-white disabled:opacity-50"
              >
                <Send className="h-4 w-4" />
                {working === 'publish' ? 'Publishing…' : 'Publish Draft'}
              </button>
            )}
            {draft && draft.status === 'superseded' && (
              <button
                type="button"
                disabled={Boolean(working)}
                onClick={() => void publish(draft.id, true)}
                className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-amber-600 px-4 text-sm font-bold text-white disabled:opacity-50"
              >
                <Send className="h-4 w-4" />
                {working === `rollback:${draft.id}` ? 'Restoring…' : 'Roll Back to This Version'}
              </button>
            )}
          </div>

          {confirmIncomplete && readinessQuery.data && (
            <div className="rounded-xl border border-red-700/50 bg-red-950/30 p-4">
              <p className="font-semibold text-red-200">Generate with these missing facts?</p>
              <ul className="my-3 list-disc space-y-1 pl-5 text-sm text-red-100">
                {readinessQuery.data.data_quality.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => void generate(true)}
                  className="min-h-11 rounded-lg bg-red-600 px-4 text-sm font-bold text-white"
                >
                  Generate Anyway
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmIncomplete(false)}
                  className="min-h-11 rounded-lg border border-slate-600 px-4 text-sm font-semibold text-slate-200"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {historyQuery.data && historyQuery.data.length > 0 && (
            <details>
              <summary className="cursor-pointer text-sm font-semibold text-slate-300">
                Version history ({historyQuery.data.length})
              </summary>
              <div className="mt-2 space-y-2">
                {historyQuery.data.map((item) => (
                  <div
                    key={item.id}
                    className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm ${
                      draft?.id === item.id ? 'border-amber-500 bg-amber-500/10' : 'border-slate-800'
                    }`}
                  >
                    <span className="text-slate-300">
                      {item.status} · v{item.version}
                      {item.published_at ? ` · ${item.published_at}` : ''}
                    </span>
                    <button
                      type="button"
                      disabled={Boolean(working)}
                      onClick={() => void previewVersion(item.id)}
                      className="text-xs font-semibold text-amber-300 hover:text-amber-100"
                    >
                      Preview
                    </button>
                  </div>
                ))}
              </div>
            </details>
          )}

          {actionError && <p className="text-sm text-red-400">{actionError}</p>}
        </section>
      )}

      {publicQuery.isLoading && <p className="text-slate-400">Loading recap…</p>}
      {publicQuery.error && (
        <p className="text-red-400">{formatApiError(publicQuery.error)}</p>
      )}
      {preview && content && snapshot && (
        <>
          <Narrative content={content} />
          <section>
            <h2 className="text-xl font-bold text-white">
              {snapshot.playoff_context
                ? `${snapshot.playoff_context.round_label} results`
                : 'Matchup results'}
            </h2>
            <div className="mt-3 grid gap-3 md:grid-cols-2">
              {(snapshot.matchups ?? []).map((row) => {
                const takeaway = (content.matchup_takeaways ?? []).find(
                  (item) => item.matchup_id === row.matchup_id,
                )
                return (
                  <div key={(row as JsonRecord).matchup_id as string} className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
                    <p className="font-bold text-white">{matchupLabel(row)}</p>
                    {takeaway ? <MatchupVoices takeaway={takeaway} /> : null}
                  </div>
                )
              })}
            </div>
          </section>

          <section className="flex flex-wrap items-center gap-3 border-t border-slate-800 pt-5">
            <CopyButton label="Copy Recap" value={content?.share_text ?? ''} />
          </section>
        </>
      )}
      {!publicQuery.isLoading && !preview && (
        <p className="text-slate-500">No recap published for this week yet.</p>
      )}
    </div>
  )
}
