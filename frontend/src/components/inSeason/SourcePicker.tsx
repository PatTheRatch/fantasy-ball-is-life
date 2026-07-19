import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { getProjectionsActive, getProjectionsSets } from '../../api'

export function SourcePicker({
  onActivate,
  onClear,
}: {
  onActivate: (setId: string) => Promise<void>
  onClear: () => Promise<void>
}) {
  const { data: sets, refetch } = useQuery({
    queryKey: ['projections', 'sets', 'week'],
    queryFn: () => getProjectionsSets({ horizon: 'week' }),
    staleTime: 30_000,
  })
  const { data: active } = useQuery({
    queryKey: ['projections', 'active', 'week'],
    queryFn: () => getProjectionsActive('week'),
    staleTime: 30_000,
  })
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleActivate = async (setId: string) => {
    setBusy(setId)
    setError(null)
    try { await onActivate(setId) } catch {
      setError('Failed to switch source')
    }
    await refetch()
    setBusy(null)
  }

  const handleClear = async () => {
    setBusy('clear')
    setError(null)
    try { await onClear() } catch {
      setError('Failed to switch to ESPN')
    }
    await refetch()
    setBusy(null)
  }

  const activeSetId = active?.set_id ?? ''
  const weekSets = (sets ?? []).filter(
    (s: Record<string, unknown>) => String(s.source ?? '') !== 'espn',
  )

  // Per-request view override hint — the Last-15/30 toggle above is a
  // temporary view choice. These buttons change the persistent active
  // source that ALL projected-scoreboard views use.
  return (
    <div className="mt-4 space-y-2">
      <p className="text-xs font-medium text-slate-400">
        Persistent source (affects all views)
      </p>
      {weekSets.map((s: Record<string, unknown>) => {
        const sid = String(s.set_id)
        const isActive = sid === activeSetId
        return (
          <button
            key={sid}
            type="button"
            onClick={() => handleActivate(sid)}
            disabled={busy != null}
            className={`w-full min-h-[40px] rounded-lg border px-3 py-2 text-left text-sm ${
              isActive
                ? 'border-emerald-500/60 bg-emerald-500/10 text-emerald-300'
                : 'border-slate-600 bg-slate-800 text-slate-200'
            }`}
          >
            {String(s.source ?? '').toUpperCase()} · Week {String(s.week ?? '—')}
            {isActive && ' ✓'}
            {busy === sid && ' …'}
          </button>
        )
      })}
      <button
        type="button"
        onClick={handleClear}
        disabled={busy != null}
        className={`w-full min-h-[40px] rounded-lg border border-dashed px-3 py-2 text-left text-sm ${
          !activeSetId || active?.is_virtual
            ? 'border-emerald-500/40 bg-emerald-500/5 text-emerald-400'
            : 'border-slate-600 bg-transparent text-slate-400'
        }`}
      >
        ESPN live (default)
        {(!activeSetId || active?.is_virtual) && ' ✓'}
        {busy === 'clear' && ' …'}
      </button>
      {error && (
        <p className="text-xs text-red-400">{error}</p>
      )}
    </div>
  )
}
