import { lazy, Suspense, type ReactNode } from 'react'

const DraftPageLazy = lazy(() =>
  import('./pages/DraftPage').then((m) => ({ default: m.DraftPage })),
)
const MatchupWeekPageLazy = lazy(() =>
  import('./pages/MatchupWeekPage').then((m) => ({ default: m.MatchupWeekPage })),
)
const SeasonLazy = lazy(() =>
  import('./pages/Season').then((m) => ({ default: m.Season })),
)

function withSuspense(node: ReactNode) {
  return <Suspense fallback={<p className="text-slate-400">Loading…</p>}>{node}</Suspense>
}

/** P-7 route-level code-splitting for the heavy tool surfaces. */
export function DraftPageRoute() {
  return withSuspense(<DraftPageLazy />)
}

export function MatchupWeekPageRoute() {
  return withSuspense(<MatchupWeekPageLazy />)
}

export function SeasonRoute() {
  return withSuspense(<SeasonLazy />)
}
