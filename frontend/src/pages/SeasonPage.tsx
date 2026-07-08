import { Card } from '../components/Card'

export function SeasonPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white md:text-3xl">
          Season
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Long-range stats, luck index, and season commentary.
        </p>
      </div>
      <Card>
        <p className="text-sm leading-relaxed text-slate-300">
          Use{' '}
          <code className="rounded bg-black/30 px-1.5 py-0.5 text-pg-accent">
            getLeagueSettings
          </code>{' '}
          and{' '}
          <code className="rounded bg-black/30 px-1.5 py-0.5">
            getSeasonStats
          </code>
          , then{' '}
          <code className="rounded bg-black/30 px-1.5 py-0.5">
            postSeasonCommentary
          </code>
          .
        </p>
      </Card>
    </div>
  )
}
