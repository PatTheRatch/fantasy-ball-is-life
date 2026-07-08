import { Card } from '../components/Card'

export function RecapPage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white md:text-3xl">
          Weekly Recap
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          League newsletter powered by your standings, rankings, and scores.
        </p>
      </div>
      <Card>
        <p className="text-sm leading-relaxed text-slate-300">
          Use{' '}
          <code className="rounded bg-black/30 px-1.5 py-0.5 text-pg-accent">
            getLeagueStandings
          </code>
          ,{' '}
          <code className="rounded bg-black/30 px-1.5 py-0.5">
            getPowerRankings
          </code>
          ,{' '}
          <code className="rounded bg-black/30 px-1.5 py-0.5">
            getTransactions
          </code>
          ,{' '}
          <code className="rounded bg-black/30 px-1.5 py-0.5">
            getScoreboardCurrent
          </code>
          , then{' '}
          <code className="rounded bg-black/30 px-1.5 py-0.5">
            postLeagueRecap
          </code>
          .
        </p>
      </Card>
    </div>
  )
}
