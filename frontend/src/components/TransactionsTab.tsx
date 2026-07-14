import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ArrowRightLeft,
  DollarSign,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { getPublishedRecap } from '../api'

/** Parse ESPN transaction id from activity_id: "txn-{week}-{txnId}-{action}-{playerId}" */
function parseTxnId(activityId: unknown): string {
  const m = String(activityId ?? '').match(/^txn-\d+-(\d+)-/)
  return m ? m[1] : String(activityId ?? '')
}

export function TransactionsTab({
  slug,
  season,
  week,
}: {
  slug: string
  season: number
  week: number
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['recap', 'published', slug, season, week],
    queryFn: () => getPublishedRecap(slug, season, week),
    retry: false,
  })

  if (isLoading) return <p className="text-slate-400">Loading transactions…</p>

  if (error) {
    const status = (error as { response?: { status: number } })?.response?.status
    if (status === 404) {
      return <p className="text-slate-500">No transactions published for this week.</p>
    }
    return <p className="text-red-400">Could not load transactions.</p>
  }

  const edition = data?.edition ?? null
  const snapshot = edition?.snapshot
  if (!edition || !snapshot) {
    return <p className="text-slate-500">No transactions published for this week.</p>
  }

  const transactions: Record<string, unknown>[] = snapshot.transactions || []
  const standings: Record<string, unknown>[] = snapshot.standings || []

  // ── Season leaderboard ──────────────────────────────────────────
  const leaderboard = standings
    .map((s) => ({
      team: String(s.team_name ?? ''),
      moves: Number(s.moves ?? 0),
      trades: Number(s.trades ?? 0),
      drops: Number(s.drops ?? 0),
      total: Number(s.moves ?? 0) + Number(s.trades ?? 0) + Number(s.drops ?? 0),
    }))
    .filter((r) => r.total > 0)
    .sort((a, b) => b.total - a.total)

  // ── Group transactions by txnId ─────────────────────────────────
  const groups: Map<string, Record<string, unknown>[]> = new Map()
  for (const txn of transactions) {
    const id = parseTxnId(txn.activity_id)
    const existing = groups.get(id) || []
    existing.push(txn)
    groups.set(id, existing)
  }

  return (
    <div className="space-y-8 pb-8">
      {/* ── Weekly feed ───────────────────────────────────────── */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
          This Week
        </h2>
        {transactions.length === 0 ? (
          <p className="text-slate-500">No transactions this week.</p>
        ) : (
          <div className="space-y-3">
            {Array.from(groups.entries()).map(([txnId, items]) => (
              <TransactionCard key={txnId} items={items} teamMap={buildTeamMap(standings)} />
            ))}
          </div>
        )}
      </section>

      {/* ── Season leaderboard ─────────────────────────────────── */}
      {leaderboard.length > 0 && (
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-400">
            Season Activity
          </h2>
          <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/60">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-700 text-xs uppercase text-slate-500">
                  <th className="px-4 py-2 font-medium">Team</th>
                  <th className="px-4 py-2 text-right font-medium">Moves</th>
                  <th className="px-4 py-2 text-right font-medium">Trades</th>
                  <th className="px-4 py-2 text-right font-medium">Drops</th>
                  <th className="px-4 py-2 text-right font-medium">Total</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map((row) => (
                  <tr key={row.team} className="border-b border-slate-800/50">
                    <td className="px-4 py-2 font-medium text-white">{row.team}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-slate-300">{row.moves}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-slate-300">{row.trades}</td>
                    <td className="px-4 py-2 text-right tabular-nums text-slate-300">{row.drops}</td>
                    <td className="px-4 py-2 text-right tabular-nums font-bold text-white">
                      {row.total}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

function buildTeamMap(
  standings: Record<string, unknown>[],
): Map<string, string> {
  const m = new Map<string, string>()
  for (const s of standings) {
    m.set(String(s.team_id), String(s.team_name ?? ''))
  }
  return m
}

function TransactionCard({
  items,
  teamMap,
}: {
  items: Record<string, unknown>[]
  teamMap: Map<string, string>
}) {
  const first = items[0]
  const team = String(first?.team_name ?? '')
  const date = String(first?.date ?? '').slice(0, 10)

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-2 flex items-center justify-between">
        <p className="font-bold text-white">{team}</p>
        <p className="text-xs text-slate-500">{date}</p>
      </div>
      <div className="space-y-1.5">
        {items.map((item, i) => {
          const action = String(item.action_type ?? '')
          const player = String(item.player ?? '')
          const bid = Number(item.bid_amount ?? 0)
          const fromTeam = teamMap.get(String(item.from_team_id))
          const toTeam = teamMap.get(String(item.to_team_id))

          if (action === 'TRADE') {
            const counterparty = String(item.to_team_id) === String(first?.team_id)
              ? fromTeam
              : toTeam
            return (
              <div key={i} className="flex items-center gap-2 text-sm">
                <ArrowRightLeft className="h-4 w-4 text-purple-400" />
                <span className="text-slate-300">{player}</span>
                {counterparty && (
                  <span className="text-xs text-slate-500">
                    (from <span className="text-slate-400">{counterparty}</span>)
                  </span>
                )}
              </div>
            )
          }

          return (
            <div key={i} className="flex items-center gap-2 text-sm">
              {action === 'ADD' ? (
                <ArrowDownToLine className="h-4 w-4 text-emerald-400" />
              ) : (
                <ArrowUpFromLine className="h-4 w-4 text-red-400" />
              )}
              <span className="text-slate-300">{player}</span>
              {action === 'ADD' && bid > 0 && (
                <span className="ml-auto inline-flex items-center gap-0.5 rounded bg-amber-950/40 px-2 py-0.5 text-xs text-amber-300">
                  <DollarSign className="h-3 w-3" />
                  {bid}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
