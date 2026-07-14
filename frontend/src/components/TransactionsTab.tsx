import {
  ArrowDownToLine,
  ArrowUpFromLine,
  ArrowRightLeft,
  DollarSign,
} from 'lucide-react'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getSnapshot } from '../api'

/** Parse ESPN transaction id from activity_id: "txn-{week}-{txnId}-{action}-{playerId}"
 * ESPN's txnId is a UUID (contains hyphens), not a plain number -- match
 * everything between the "txn-{week}-" prefix and the trailing action/player
 * suffix so the same txnId is extracted for both the ADD and DROP half of a
 * paired waiver move, regardless of id format. */
function parseTxnId(activityId: unknown): string {
  const s = String(activityId ?? '')
  const m = s.match(/^txn-\d+-(.+)-(?:ADD|DROP|TRADE)-\d+$/)
  return m ? m[1] : s
}

const ALL = '__all__'

export function TransactionsTab({
  slug,
  season,
  week,
}: {
  slug: string
  season: number
  week: number
}) {
  const [dayFilter, setDayFilter] = useState(ALL)
  const [teamFilter, setTeamFilter] = useState(ALL)

  const { data, isLoading, error } = useQuery({
    queryKey: ['recap', 'snapshot', slug, season, week],
    queryFn: () => getSnapshot(slug, season, week),
    retry: false,
  })

  if (isLoading) return <p className="text-slate-400">Loading transactions…</p>

  if (error) {
    const status = (error as { response?: { status: number } })?.response?.status
    if (status === 404) {
      return <p className="text-slate-500">No transactions data for this week.</p>
    }
    return <p className="text-red-400">Could not load transactions.</p>
  }

  const snapshot = data?.snapshot as Record<string, unknown> | undefined
  if (!snapshot) {
    return <p className="text-slate-500">No transactions data for this week.</p>
  }

  const transactions: Record<string, unknown>[] = (snapshot.transactions as Record<string, unknown>[]) || []
  const standings: Record<string, unknown>[] = (snapshot.standings as Record<string, unknown>[]) || []
  const teamMap = buildTeamMap(standings)

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

  // ── Filter options, derived from the week's own data ────────────
  const days = Array.from(new Set(transactions.map((t) => String(t.date ?? '').slice(0, 10))))
    .filter(Boolean)
    .sort()
  const teams = Array.from(new Set(transactions.map((t) => String(t.team_name ?? ''))))
    .filter(Boolean)
    .sort((a, b) => a.localeCompare(b))

  const filtered = transactions.filter((t) => {
    if (dayFilter !== ALL && String(t.date ?? '').slice(0, 10) !== dayFilter) return false
    if (teamFilter !== ALL && String(t.team_name ?? '') !== teamFilter) return false
    return true
  })

  // ── Pair each waiver move's ADD + DROP under their shared txnId ─
  const groups = new Map<string, Record<string, unknown>[]>()
  for (const txn of filtered) {
    const id = parseTxnId(txn.activity_id)
    const existing = groups.get(id) || []
    existing.push(txn)
    groups.set(id, existing)
  }

  // ── Order by team, then date (oldest first within a team) ───────
  const orderedGroups = Array.from(groups.entries()).sort(([, a], [, b]) => {
    const teamA = String(a[0]?.team_name ?? '')
    const teamB = String(b[0]?.team_name ?? '')
    if (teamA !== teamB) return teamA.localeCompare(teamB)
    return String(a[0]?.date ?? '').localeCompare(String(b[0]?.date ?? ''))
  })

  return (
    <div className="space-y-8 pb-8">
      {/* ── Weekly feed ───────────────────────────────────────── */}
      <section>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            This Week
          </h2>
          <div className="flex flex-wrap gap-2">
            <FilterSelect
              value={dayFilter}
              onChange={setDayFilter}
              options={days}
              allLabel="All days"
              formatOption={formatDay}
            />
            <FilterSelect
              value={teamFilter}
              onChange={setTeamFilter}
              options={teams}
              allLabel="All teams"
            />
          </div>
        </div>
        {orderedGroups.length === 0 ? (
          <p className="text-slate-500">
            {transactions.length === 0 ? 'No transactions this week.' : 'No transactions match these filters.'}
          </p>
        ) : (
          <div className="space-y-3">
            {orderedGroups.map(([txnId, items]) => (
              <TransactionCard key={txnId} items={items} teamMap={teamMap} />
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

function formatDay(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' })
}

function FilterSelect({
  value,
  onChange,
  options,
  allLabel,
  formatOption,
}: {
  value: string
  onChange: (v: string) => void
  options: string[]
  allLabel: string
  formatOption?: (v: string) => string
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 text-sm text-slate-200"
    >
      <option value={ALL}>{allLabel}</option>
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {formatOption ? formatOption(opt) : opt}
        </option>
      ))}
    </select>
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

  const trades = items.filter((i) => String(i.action_type) === 'TRADE')
  const add = items.find((i) => String(i.action_type) === 'ADD')
  const drop = items.find((i) => String(i.action_type) === 'DROP')
  const isPairedMove = trades.length === 0 && add && drop

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-2 flex items-center justify-between">
        <p className="font-bold text-white">{team}</p>
        <p className="text-xs text-slate-500">{date}</p>
      </div>

      {isPairedMove ? (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-sm">
          <span className="inline-flex items-center gap-1.5 text-emerald-300">
            <ArrowDownToLine className="h-4 w-4" />
            {String(add.player)}
            {Number(add.bid_amount ?? 0) > 0 && (
              <span className="inline-flex items-center gap-0.5 rounded bg-amber-950/40 px-1.5 py-0.5 text-xs text-amber-300">
                <DollarSign className="h-3 w-3" />
                {Number(add.bid_amount)}
              </span>
            )}
          </span>
          <span className="text-slate-600">for</span>
          <span className="inline-flex items-center gap-1.5 text-red-300">
            <ArrowUpFromLine className="h-4 w-4" />
            {String(drop.player)}
          </span>
        </div>
      ) : (
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
      )}
    </div>
  )
}
