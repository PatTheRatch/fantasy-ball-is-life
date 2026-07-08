import { Card } from '../components/Card'

export function DraftPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white md:text-3xl">
          Draft Optimizer
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Build your roster and run the optimizer against BBM projections.
        </p>
      </div>
      <Card>
        <p className="text-sm leading-relaxed text-slate-300">
          Full draft UI will live here — upload season projections, set budget and
          constraints, then call{' '}
          <code className="rounded bg-black/30 px-1.5 py-0.5 text-pg-accent">
            postOptimizerOptimize
          </code>{' '}
          from <code className="rounded bg-black/30 px-1.5 py-0.5">src/api.ts</code>.
        </p>
      </Card>
    </div>
  )
}
