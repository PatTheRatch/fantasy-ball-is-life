import { useQuery } from '@tanstack/react-query'
import { getProjectionsSets } from '../api'

interface ProjectionSet {
  set_id: string
  source: string
  horizon: string
  uploaded_at: string
  filename: string | null
}

async function fetchActiveSet(horizon: string): Promise<ProjectionSet | null> {
  const sets = await getProjectionsSets({ horizon })
  if (sets.length === 0) return null
  return sets[0] as unknown as ProjectionSet
}

export function ProjectionBadge({ horizon }: { horizon: 'season' | 'week' }) {
  const { data } = useQuery({
    queryKey: ['projections', 'active', horizon],
    queryFn: () => fetchActiveSet(horizon),
    staleTime: 60_000,
  })

  if (!data) return null

  const sourceLabel =
    data.source === 'bbm' ? 'BBM' : data.source.toUpperCase()
  const date = new Date(data.uploaded_at).toLocaleDateString()

  return (
    <div className="inline-flex items-center gap-1.5 rounded-full border border-slate-700/60 bg-slate-900/80 px-3 py-1 text-xs text-slate-400">
      <span className="font-medium text-slate-300">
        Projections
      </span>
      <span className="text-slate-500">·</span>
      <span>{sourceLabel}</span>
      <span className="text-slate-500">·</span>
      <span>{date}</span>
    </div>
  )
}
