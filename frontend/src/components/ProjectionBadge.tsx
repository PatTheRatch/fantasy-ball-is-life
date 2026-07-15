import { useQuery } from '@tanstack/react-query'
import { getProjectionsActive } from '../api'
import type { ActiveProjectionSet } from '../api'

function sourceLabel(source: string): string {
  if (source === 'bbm') return 'BBM'
  if (source === 'espn') return 'ESPN'
  return source.toUpperCase()
}

function formatDate(iso: string | null, isVirtual: boolean): string {
  if (isVirtual || !iso) return 'live'
  return new Date(iso).toLocaleDateString()
}

export function ProjectionBadge({ horizon }: { horizon: 'season' | 'week' }) {
  const { data: active } = useQuery<ActiveProjectionSet | null>({
    queryKey: ['projections', 'active', horizon],
    queryFn: () => getProjectionsActive(horizon),
    staleTime: 60_000,
  })

  // No active set → fall through to default (ESPN for week, nothing for season)
  if (!active) {
    if (horizon === 'week') {
      // ESPN is the default — show it
      return (
        <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-700/60 bg-slate-900/80 px-3 py-1 text-xs text-slate-400">
          <span className="font-medium text-slate-300">Projections</span>
          <span className="text-slate-500">·</span>
          <span>{sourceLabel('espn')}</span>
          <span className="text-slate-500">·</span>
          <span>live</span>
        </div>
      )
    }
    // Season with no active set → show a neutral badge
    return (
      <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-700/60 bg-slate-900/80 px-3 py-1 text-xs text-slate-400">
        <span className="font-medium text-slate-300">Projections</span>
        <span className="text-slate-500">·</span>
        <span>none active</span>
      </div>
    )
  }

  return (
    <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-700/60 bg-slate-900/80 px-3 py-1 text-xs text-slate-400">
      <span className="font-medium text-slate-300">Projections</span>
      <span className="text-slate-500">·</span>
      <span>{sourceLabel(active.source)}</span>
      <span className="text-slate-500">·</span>
      <span>{formatDate(active.uploaded_at, active.is_virtual)}</span>
    </div>
  )
}
