import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getSnapshot, getPublishedRecap, type RecapGeneratedContent } from '../api'
import { formatStatValue, STAT_ORDER } from '../lib/inSeasonUtils'
import { AiTakeBadge } from './AiTakeBadge'
import { MatchupVoices } from './MatchupVoices'

function winnerLabel(row: Record<string, unknown>): string {
  const home = String(row.home_team ?? '')
  const away = String(row.away_team ?? '')
  const homeWins = Number(row.home_category_wins ?? 0)
  const awayWins = Number(row.away_category_wins ?? 0)
  return `${home} ${homeWins}–${awayWins} ${away}`
}

function CategoryBreakdown({ categories }: { categories: Record<string, unknown>[] }) {
  return (
    <div className="mt-3 overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead>
          <tr className="border-b border-slate-700 text-slate-500">
            <th className="pb-1 font-medium">Category</th>
            <th className="pb-1 pr-2 text-right font-medium">Home</th>
            <th className="pb-1 text-right font-medium">Away</th>
            <th className="pb-1 text-center font-medium">Edge</th>
          </tr>
        </thead>
        <tbody>
          {STAT_ORDER.map((stat) => {
            const row = categories.find(
              (c) => String(c.stat) === stat,
            )
            if (!row) {
              return (
                <tr key={stat} className="border-b border-slate-800/50">
                  <td className="py-1.5 text-slate-400">{stat}</td>
                  <td className="py-1.5 pr-2 text-right text-slate-600">—</td>
                  <td className="py-1.5 text-right text-slate-600">—</td>
                  <td className="py-1.5 text-center text-slate-600">—</td>
                </tr>
              )
            }
            const hVal = formatStatValue(stat, row.home_value)
            const aVal = formatStatValue(stat, row.away_value)
            const winner = String(row.winner ?? '')
            const complete = row.complete !== false && winner !== 'unavailable'
            return (
              <tr
                key={stat}
                className={`border-b border-slate-800/50 ${!complete ? 'opacity-40' : ''}`}
              >
                <td className="py-1.5 font-medium text-slate-300">{stat}</td>
                <td
                  className={`py-1.5 pr-2 text-right tabular-nums ${
                    winner === 'home'
                      ? 'font-bold text-emerald-400'
                      : 'text-slate-400'
                  }`}
                >
                  {complete ? hVal : '—'}
                </td>
                <td
                  className={`py-1.5 text-right tabular-nums ${
                    winner === 'away'
                      ? 'font-bold text-emerald-400'
                      : 'text-slate-400'
                  }`}
                >
                  {complete ? aVal : '—'}
                </td>
                <td className="py-1.5 text-center">
                  {winner === 'home' ? (
                    <span className="text-emerald-500">H</span>
                  ) : winner === 'away' ? (
                    <span className="text-emerald-500">A</span>
                  ) : winner === 'tie' ? (
                    <span className="text-slate-500">T</span>
                  ) : null}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function MatchupsTab({
  slug,
  season,
  week,
}: {
  slug: string
  season: number
  week: number
}) {
  const snapshotQuery = useQuery({
    queryKey: ['recap', 'snapshot', slug, season, week],
    queryFn: () => getSnapshot(slug, season, week),
    retry: false,
  })

  const recapQuery = useQuery({
    queryKey: ['recap', 'published', slug, season, week],
    queryFn: () => getPublishedRecap(slug, season, week),
    retry: false,
  })

  if (snapshotQuery.isLoading) return <p className="text-slate-400">Loading matchups…</p>

  if (snapshotQuery.error) {
    const status = (snapshotQuery.error as { response?: { status: number } })?.response?.status
    if (status === 404) {
      return <p className="text-slate-500">No matchup data for this week.</p>
    }
    return <p className="text-red-400">Could not load matchups.</p>
  }

  const snapshot = snapshotQuery.data?.snapshot as Record<string, unknown> | undefined
  const content = recapQuery.data?.edition?.structured_content_json

  if (!snapshot) {
    return <p className="text-slate-500">No matchup data for this week.</p>
  }

  const { matchups } = snapshot
  if (!Array.isArray(matchups) || matchups.length === 0) {
    return <p className="text-slate-500">No matchups recorded for this week.</p>
  }

  return (
    <div className="space-y-4 pb-8">
      {(snapshot.playoff_context as Record<string, unknown> | undefined)?.round_label ? (
        <p className="text-sm font-semibold text-amber-400">
          {String((snapshot.playoff_context as Record<string, unknown>).round_label)}
        </p>
      ) : null}
      <p className="text-xs text-slate-600">
        ESPN resolves category ties. AI takeaways may reflect model opinion.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        {matchups.map((row) => (
          <MatchupCard
            key={String((row as Record<string, unknown>).matchup_id ?? '')}
            row={row as Record<string, unknown>}
            content={content ?? null}
          />
        ))}
      </div>
    </div>
  )
}

function MatchupCard({
  row,
  content,
}: {
  row: Record<string, unknown>
  content: RecapGeneratedContent | null
}) {
  const [open, setOpen] = useState(false)

  const takeawayItem = ((content?.matchup_takeaways) || []).find(
    (item) => item.matchup_id === row.matchup_id,
  )

  const tiebreakResolved = row.tiebreak_resolved === true

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start justify-between gap-3 p-4 text-left"
      >
        <div className="min-w-0 flex-1">
          <p className="font-bold text-white">{winnerLabel(row)}</p>
          {tiebreakResolved && (
            <p className="mt-0.5 text-xs text-amber-400">
              Tie resolved by ESPN tiebreaker
            </p>
          )}
          {takeawayItem && (
            <div>
              <MatchupVoices takeaway={takeawayItem} />
              <AiTakeBadge />
            </div>
          )}
        </div>
        {open ? (
          <ChevronUp className="mt-0.5 h-5 w-5 flex-shrink-0 text-slate-500" />
        ) : (
          <ChevronDown className="mt-0.5 h-5 w-5 flex-shrink-0 text-slate-500" />
        )}
      </button>
      {open && Array.isArray(row.categories) && (
        <div className="border-t border-slate-800 px-4 pb-4">
          <CategoryBreakdown categories={row.categories as Record<string, unknown>[]} />
        </div>
      )}
    </div>
  )
}
