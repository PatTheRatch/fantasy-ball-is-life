import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Upload } from 'lucide-react'
import {
  deleteProjectionsActive,
  getProjectionsSets,
  postProjectionsUpload,
  putProjectionsActive,
  type ProjectionUploadResult,
} from '../api'
import type { JsonRecord } from '../api'

/**
 * Season-horizon projection upload for the Draft Room.
 *
 * The draft optimizer reads `get_active_projections('season')`. Until this
 * existed there was no way to put a set there from the UI: the only
 * projection controls (`inSeason/SourcePicker`, `ScoreboardTools`) are
 * hardcoded to the *week* horizon, and the legacy on-disk workbook is
 * gitignored and absent from every deploy. So a deployed Draft Room had no
 * projection source and no way to be given one.
 *
 * `horizon` is sent EXPLICITLY as 'season' and never left to auto-detection.
 * BBM uses `/g` column names in both its season and weekly exports, so the
 * server's signature sniffing classifies a season file as 'week' — which
 * files it under the wrong horizon (the draft still sees nothing) and, in
 * the offseason, fails outright because week uploads require a live ESPN
 * matchup period.
 */
export function ProjectionUpload() {
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [result, setResult] = useState<ProjectionUploadResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const sets = useQuery({
    queryKey: ['projections', 'sets', 'season'],
    queryFn: () => getProjectionsSets({ horizon: 'season' }),
  })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['projections'] })
  }

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const fd = new FormData()
      fd.append('file', file)
      // Explicit — see the note above. Never rely on auto-detection here.
      fd.append('horizon', 'season')
      fd.append('source', 'bbm')
      return postProjectionsUpload(fd)
    },
    onSuccess: (r) => {
      setResult(r)
      setError(null)
      invalidate()
    },
    onError: (e: unknown) => {
      setResult(null)
      setError(extractError(e))
    },
  })

  const activate = useMutation({
    mutationFn: (setId: string) => putProjectionsActive(setId),
    onSuccess: invalidate,
    onError: (e: unknown) => setError(extractError(e)),
  })

  const clear = useMutation({
    mutationFn: () => deleteProjectionsActive('season'),
    onSuccess: () => {
      setResult(null)
      invalidate()
    },
    onError: (e: unknown) => setError(extractError(e)),
  })

  const rows = (sets.data ?? []) as JsonRecord[]

  return (
    <section className="rounded-pg-lg border border-pg-border bg-pg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-bold uppercase tracking-wider text-slate-300">
            Season projections
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            Upload your Basketball Monster season export (.xls or .csv). The
            optimizer prices players from its <code>$</code> column.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <input
            ref={fileRef}
            type="file"
            accept=".xls,.xlsx,.csv"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) upload.mutate(f)
              e.target.value = ''
            }}
          />
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={upload.isPending}
            className="inline-flex items-center gap-2 rounded-lg bg-pg-accent px-3 py-2 text-sm font-semibold text-white disabled:opacity-50"
          >
            <Upload className="h-4 w-4" aria-hidden />
            {upload.isPending ? 'Uploading…' : 'Upload projections'}
          </button>
          {rows.length > 0 && (
            <button
              type="button"
              onClick={() => clear.mutate()}
              disabled={clear.isPending}
              className="rounded-lg border border-pg-border px-3 py-2 text-sm text-slate-300 disabled:opacity-50"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {error && (
        <p className="mt-3 rounded-lg border border-red-900/50 bg-red-950/30 p-2 text-xs text-red-300">
          {error}
        </p>
      )}

      {result && (
        <div className="mt-3 rounded-lg border border-pg-border bg-pg-bg p-3 text-xs">
          <p className="text-slate-300">
            Loaded <strong>{result.row_count}</strong> players from{' '}
            {result.filename ?? 'upload'}.
          </p>
          {result.unmatched_players.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-amber-400">
                {result.unmatched_players.length} name
                {result.unmatched_players.length === 1 ? '' : 's'} didn’t match an
                ESPN player
              </summary>
              <p className="mt-1 max-h-32 overflow-y-auto text-slate-500">
                {result.unmatched_players.join(', ')}
              </p>
            </details>
          )}
        </div>
      )}

      {rows.length > 0 && (
        <ul className="mt-3 space-y-1">
          {rows.map((s) => {
            const id = String(s.set_id ?? '')
            const isActive = Boolean(s.is_active)
            return (
              <li
                key={id}
                className="flex items-center justify-between gap-3 rounded-lg border border-pg-border px-3 py-2 text-xs"
              >
                <span className="min-w-0 flex-1 truncate text-slate-300">
                  {String(s.filename ?? s.source ?? 'projection set')}
                  <span className="ml-2 text-slate-500">
                    {String(s.row_count ?? '')} players
                  </span>
                </span>
                {isActive ? (
                  <span className="shrink-0 font-semibold text-emerald-400">
                    Active
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => activate.mutate(id)}
                    disabled={activate.isPending}
                    className="shrink-0 text-pg-accent hover:underline disabled:opacity-50"
                  >
                    Use this
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function extractError(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response
    ?.data?.detail
  if (typeof detail === 'string') return detail
  if (e instanceof Error) return e.message
  return 'Upload failed.'
}
