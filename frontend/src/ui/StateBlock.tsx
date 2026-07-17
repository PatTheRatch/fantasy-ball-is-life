import { AlertTriangle, Database, ServerCrash } from 'lucide-react'
import type { ReactNode } from 'react'
import { Card } from './Card'
import { Skeleton } from './Skeleton'
import { StaleBadge } from './Skeleton'

/* -------------------------------------------------------------------------- */
/* StateBlock — unified loading / empty / error / stale container.            */
/* Every read surface renders through this instead of ad-hoc <p> tags.        */
/* -------------------------------------------------------------------------- */

export type StateBlockProps = {
  /** Which visual state to render */
  state: 'loading' | 'empty' | 'error' | 'stale'

  /** Optional: title override per state. Falls back to sensible defaults. */
  title?: string
  /** Optional: descriptive body copy. */
  description?: string

  /** For 'error': the original error object (status/message extracted). */
  error?: unknown

  /** For 'stale': ISO timestamp of last fetch. */
  fetchedAt?: string | null

  /** Optional: action element (e.g. a Retry button). */
  action?: ReactNode

  /** Optional: number of skeleton rows for 'loading' state. */
  skeletonRows?: number

  className?: string
}

const DEFAULT_COPY: Record<StateBlockProps['state'], { title: string; description: string }> = {
  loading: { title: 'Loading…', description: '' },
  empty: { title: 'Nothing here yet', description: 'Check back when data is available.' },
  error: { title: 'Could not load data', description: 'The server returned an error. Try again in a moment.' },
  stale: { title: 'Data may be stale', description: 'Live data is temporarily unavailable. Showing the last available snapshot.' },
}

function errorStatus(error: unknown): number | null {
  if (error == null) return null
  if (typeof error !== 'object') return null
  const e = error as { response?: { status?: number }; status?: number }
  return e.response?.status ?? e.status ?? null
}

function errorMessage(error: unknown): string {
  if (error == null) return ''
  if (error instanceof Error) return error.message
  if (typeof error === 'string') return error
  return ''
}

export function StateBlock({
  state,
  title,
  description: descOverride,
  error,
  fetchedAt,
  action,
  skeletonRows = 4,
  className = '',
}: StateBlockProps) {
  // ── Loading ──────────────────────────────────────────────────────
  if (state === 'loading') {
    return (
      <div className={`space-y-3 ${className}`} aria-busy="true">
        {Array.from({ length: skeletonRows }).map((_, i) => (
          <Skeleton key={i} className={i === 0 ? 'h-6 w-3/4' : 'h-4 w-full'} />
        ))}
      </div>
    )
  }

  // ── Empty, Error, Stale share the same card layout ───────────────
  const copy = DEFAULT_COPY[state]
  const status = errorStatus(error)

  // Override copy for known states
  let effectiveTitle = title ?? copy.title
  let effectiveDesc = descOverride ?? copy.description

  if (state === 'error') {
    if (status === 404) {
      effectiveTitle = 'Nothing here yet'
      effectiveDesc = 'No data available for this selection.'
    } else if (errorMessage(error).includes('Network') || status === 0) {
      effectiveTitle = 'Cannot reach server'
      effectiveDesc = 'Check your connection and try again.'
    }
  }

  const Icon =
    state === 'error' ? (status === 404 ? Database : ServerCrash) :
    state === 'stale' ? AlertTriangle :
    Database

  const iconColor =
    state === 'error' ? 'text-red-400' :
    state === 'stale' ? 'text-amber-400' :
    'text-slate-500'

  return (
    <Card variant="ghost" className={`flex flex-col items-center gap-3 px-6 py-10 text-center ${className}`}>
      <Icon className={`h-8 w-8 ${iconColor}`} />
      <div>
        <p className="text-sm font-semibold text-slate-300">{effectiveTitle}</p>
        {effectiveDesc && (
          <p className="mt-1 text-xs leading-relaxed text-slate-500">{effectiveDesc}</p>
        )}
      </div>
      {state === 'stale' && fetchedAt && (
        <StaleBadge fetchedAt={fetchedAt} />
      )}
      {action && <div className="mt-1">{action}</div>}
    </Card>
  )
}
