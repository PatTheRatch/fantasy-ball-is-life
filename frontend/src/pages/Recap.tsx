import { useQuery, useQueryClient } from '@tanstack/react-query'
import type { Session } from '@supabase/supabase-js'
import { Copy, LockKeyhole, RefreshCw, Send, ShieldCheck } from 'lucide-react'
import { useEffect, useState } from 'react'
import {
  formatApiError,
  generateRecapDraft,
  getLeagueSettings,
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
import {
  MATCHUP_WEEKS_2025_26,
  WEEK_MAX,
  WEEK_MIN,
} from '../lib/matchupWeeks'
import { recapLeagueSlug, supabase } from '../lib/supabase'

const RECAP_SEASON = Number(import.meta.env.VITE_RECAP_SEASON ?? 2026)
const REQUESTED_WEEK =
  typeof window === 'undefined'
    ? null
    : Number(new URLSearchParams(window.location.search).get('week'))

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
          {content.dek}
        </p>
      </div>
      <div className="space-y-5 px-5 py-6 text-[15px] leading-7 text-slate-200 md:px-8">
        {content.lead_story.map((paragraph, index) => (
          <p key={`${index}-${paragraph.slice(0, 20)}`}>{paragraph}</p>
        ))}
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

export function Recap() {
  const queryClient = useQueryClient()
  const [week, setWeek] = useState(
    REQUESTED_WEEK &&
      REQUESTED_WEEK >= WEEK_MIN &&
      REQUESTED_WEEK <= WEEK_MAX
      ? REQUESTED_WEEK
      : 1,
  )
  const [adminMode, setAdminMode] = useState(false)
  const [session, setSession] = useState<Session | null>(null)
  const [draft, setDraft] = useState<RecapEdition | null>(null)
  const [confirmIncomplete, setConfirmIncomplete] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [working, setWorking] = useState<string | null>(null)

  const settingsQuery = useQuery({
    queryKey: ['league', 'settings'],
    queryFn: getLeagueSettings,
  })
  useEffect(() => {
    if (REQUESTED_WEEK) return
    if (!settingsQuery.data?.current_week) return
    setWeek(
      Math.min(
        WEEK_MAX,
        Math.max(WEEK_MIN, Number(settingsQuery.data.current_week) - 1),
      ),
    )
  }, [settingsQuery.data?.current_week])

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
    queryKey: ['recap', 'published', recapLeagueSlug, RECAP_SEASON, week],
    queryFn: () => getPublishedRecap(recapLeagueSlug, RECAP_SEASON, week),
    retry: false,
  })
  const readinessQuery = useQuery({
    queryKey: ['recap', 'readiness', recapLeagueSlug, RECAP_SEASON, week],
    queryFn: () =>
      getRecapReadiness(
        recapLeagueSlug,
        RECAP_SEASON,
        week,
        dates.start,
        dates.end,
        token,
      ),
    enabled: adminMode && Boolean(token && dates?.start && dates?.end),
    retry: false,
  })
  const historyQuery = useQuery({
    queryKey: ['recap', 'history', recapLeagueSlug, RECAP_SEASON, week],
    queryFn: () =>
      getRecapHistory(recapLeagueSlug, RECAP_SEASON, week, token),
    enabled: adminMode && Boolean(token),
    retry: false,
  })

  const generate = async (generateAnyway: boolean) => {
    if (!dates || !token) return
    setWorking('generate')
    setActionError(null)
    try {
      const edition = await generateRecapDraft(
        recapLeagueSlug,
        RECAP_SEASON,
        week,
        dates.start,
        dates.end,
        generateAnyway,
        token,
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
      const edition = await getRecapEdition(
        recapLeagueSlug,
        RECAP_SEASON,
        week,
        editionId,
        token,
      )
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
        await rollbackRecapEdition(
          recapLeagueSlug,
          RECAP_SEASON,
          week,
          editionId,
          token,
        )
      } else {
        await publishRecapEdition(
          recapLeagueSlug,
          RECAP_SEASON,
          week,
          editionId,
          token,
        )
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
      <header className="flex flex-col gap-4 border-b border-slate-800 pb-5 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-red-400">
            Patriot Games
          </p>
          <h1 className="mt-1 text-3xl font-black tracking-tight text-white">
            Weekly Recap
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            One published edition for the whole league.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={week}
            onChange={(event) => setWeek(Number(event.target.value))}
            className="min-h-11 rounded-lg border border-slate-700 bg-slate-900 px-3 text-sm font-semibold text-white"
            aria-label="Recap week"
          >
            {Array.from({ length: WEEK_MAX }, (_, index) => index + 1).map(
              (value) => (
                <option key={value} value={value}>
                  Week {value}
                </option>
              ),
            )}
          </select>
          <button
            type="button"
            onClick={() => setAdminMode((value) => !value)}
            className={`inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-semibold ${
              adminMode
                ? 'border-amber-500 bg-amber-500/15 text-amber-200'
                : 'border-slate-700 bg-slate-900 text-slate-300'
            }`}
          >
            <ShieldCheck className="h-4 w-4" />
            {adminMode ? 'Exit admin mode' : 'Admin mode'}
          </button>
        </div>
      </header>

      {adminMode && !session && <AdminSignIn onSession={setSession} />}

      {adminMode && session && (
        <section className="space-y-4 rounded-2xl border border-amber-700/40 bg-amber-950/10 p-4 md:p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-bold text-white">Publishing desk</h2>
              <p className="text-sm text-slate-400">
                Generate Draft → Preview → Publish
              </p>
            </div>
            <button
              type="button"
              onClick={() => void supabase?.auth.signOut()}
              className="text-xs font-semibold text-slate-400 hover:text-white"
            >
              Sign out
            </button>
          </div>

          {readinessQuery.isLoading && (
            <p className="text-sm text-slate-400">Checking league data…</p>
          )}
          {readinessQuery.error && (
            <p className="text-sm text-red-400">
              {formatApiError(readinessQuery.error)}
            </p>
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
                {readinessQuery.data.data_quality.ready
                  ? 'Data ready'
                  : 'Data incomplete'}
              </p>
              <div className="mt-2 grid gap-1 text-xs text-slate-300 sm:grid-cols-2">
                {Object.entries(readinessQuery.data.data_quality.checks).map(
                  ([label, ok]) => (
                    <span key={label}>
                      {ok ? '✓' : '⚠'} {label.replaceAll('_', ' ')}
                    </span>
                  ),
                )}
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
              {working === 'generate'
                ? 'Generating…'
                : draft
                  ? 'Refresh Draft'
                  : 'Generate Draft'}
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
              <p className="font-semibold text-red-200">
                Generate with these missing facts?
              </p>
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
                      draft?.id === item.id
                        ? 'border-amber-500 bg-amber-500/10'
                        : 'border-slate-800'
                    }`}
                  >
                    <span className="text-slate-300">
                      Version {item.version} · {item.status}
                    </span>
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        disabled={Boolean(working) || draft?.id === item.id}
                        onClick={() => void previewVersion(item.id)}
                        className="font-semibold text-slate-300 hover:text-white disabled:opacity-50"
                      >
                        {working === `preview:${item.id}`
                          ? 'Loading…'
                          : draft?.id === item.id
                            ? 'Previewing'
                            : 'Preview'}
                      </button>
                      {item.status === 'superseded' && (
                        <button
                          type="button"
                          disabled={Boolean(working)}
                          onClick={() => void publish(item.id, true)}
                          className="font-semibold text-amber-300 disabled:opacity-50"
                        >
                          {working === `rollback:${item.id}`
                            ? 'Restoring…'
                            : 'Roll back'}
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </details>
          )}
          {actionError && <p className="text-sm text-red-400">{actionError}</p>}
        </section>
      )}

      {draft && adminMode && (
        <div className="rounded-lg border border-amber-600/50 bg-amber-950/30 px-4 py-3 text-sm font-semibold text-amber-200">
          Previewing version {draft.version} · {draft.status}
          {draft.status !== 'published' && ' · not visible to league members'}
        </div>
      )}

      {content ? (
        <>
          <Narrative content={content} />
          <div className="flex flex-wrap gap-2">
            <CopyButton label="Copy Summary" value={content.whatsapp_summary} />
            <CopyButton label="Copy Full Recap" value={content.whatsapp_full} />
          </div>

          {snapshot?.matchups && snapshot.matchups.length > 0 && (
            <section className="rounded-2xl border border-slate-800 bg-slate-900/50 p-5">
              <h2 className="text-lg font-bold text-white">
                {snapshot.playoff_context
                  ? `${snapshot.playoff_context.round_label} results`
                  : 'Matchup results'}
              </h2>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                {snapshot.matchups.map((row) => {
                  const playoffRecap = content.playoff_matchup_recaps.find(
                    (item) => item.matchup_id === row.matchup_id,
                  )
                  const takeaway = content.matchup_takeaways.find(
                    (item) => item.matchup_id === row.matchup_id,
                  )
                  return (
                    <div
                      key={String(row.matchup_id)}
                      className="rounded-xl border border-slate-800 bg-slate-950/40 p-4"
                    >
                      <p className="font-bold text-white">
                        {playoffRecap?.result_summary ?? matchupLabel(row)}
                      </p>
                      {playoffRecap ? (
                        <p className="mt-2 text-sm leading-6 text-slate-400">
                          {playoffRecap.text}
                        </p>
                      ) : (
                        takeaway && (
                          <p className="mt-2 text-sm leading-6 text-slate-400">
                            {takeaway.text}
                          </p>
                        )
                      )}
                    </div>
                  )
                })}
              </div>
            </section>
          )}

          {snapshot?.playoff_context && (
            <section className="space-y-4 rounded-2xl border border-amber-800/40 bg-amber-950/10 p-5">
              {content.playoff_outlook.length > 0 && (
                <div>
                  <h2 className="text-lg font-bold text-white">What This Sets Up</h2>
                  <div className="mt-3 grid gap-3 md:grid-cols-2">
                    {content.playoff_outlook.map((item) => (
                      <div
                        key={item.team}
                        className="rounded-xl border border-amber-800/30 bg-slate-950/40 p-4"
                      >
                        <p className="font-bold text-white">{item.team}</p>
                        <p className="mt-2 text-sm leading-6 text-slate-400">{item.text}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {content.playoff_storylines.length > 0 && (
                <div>
                  <h2 className="text-lg font-bold text-white">Storylines</h2>
                  <div className="mt-3 space-y-3">
                    {content.playoff_storylines.map((item) => (
                      <div key={item.title}>
                        <p className="font-semibold text-amber-200">{item.title}</p>
                        <p className="mt-1 text-sm leading-6 text-slate-400">{item.text}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {content.playoff_final_line && (
                <p className="border-t border-amber-800/30 pt-4 text-base font-semibold italic text-amber-100">
                  {content.playoff_final_line}
                </p>
              )}
            </section>
          )}
        </>
      ) : publicQuery.isLoading ? (
        <p className="text-sm text-slate-400">Loading published edition…</p>
      ) : (
        <div className="rounded-2xl border border-dashed border-slate-700 px-5 py-12 text-center">
          <p className="font-semibold text-slate-200">
            No published recap for Week {week}
          </p>
          <p className="mt-1 text-sm text-slate-500">
            League members will see the same edition after the commissioner
            publishes it.
          </p>
        </div>
      )}
    </div>
  )
}
