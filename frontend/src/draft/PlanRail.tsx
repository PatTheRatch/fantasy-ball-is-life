import { Undo2 } from 'lucide-react'
import type { DraftPickEntry, DraftPlayerRow } from '../api'
import { Card } from '../components/Card'
import { ACCENT } from './constants'
import { fmtBid } from './formatters'

export function BudgetCard({ spent, remaining, total }: { spent: number; remaining: number; total: number }) {
  const pct = total > 0 ? Math.min(100, (spent / total) * 100) : 0
  return (
    <Card>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Budget</p>
      <div className="mt-1 flex items-baseline justify-between">
        <span className="font-mono text-2xl font-semibold text-white">{fmtBid(remaining)}</span>
        <span className="font-mono text-xs text-slate-500">of {fmtBid(total)}</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-black/30">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: ACCENT }} />
      </div>
    </Card>
  )
}

export function ValueBoardCard({ rows }: { rows: DraftPlayerRow[] }) {
  return (
    <Card>
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        Best value on the board
      </p>
      <div className="divide-y divide-pg-border/60">
        {rows.slice(0, 8).map((r) => (
          <div key={r.player_key} className="flex items-center justify-between py-1.5 text-sm">
            <span className="uppercase text-slate-200">
              {r.player_key} <span className="ml-1 font-mono text-[10px] normal-case text-slate-500">{r.pos}</span>
            </span>
            <span className="font-mono text-xs text-slate-400">{fmtBid(r.value)}</span>
          </div>
        ))}
        {rows.length === 0 && <p className="py-2 text-xs text-slate-500">No data yet.</p>}
      </div>
    </Card>
  )
}

export function PicksLogCard({
  picks,
  onUndo,
  pending,
}: {
  picks: DraftPickEntry[]
  onUndo: (index: number) => void
  pending: boolean
}) {
  return (
    <Card>
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Picks logged</p>
      <div className="divide-y divide-pg-border/60">
        {[...picks]
          .map((p, i) => ({ p, i }))
          .reverse()
          .map(({ p, i }) => (
            <div key={`${p.player_key}-${i}`} className="group flex items-start gap-2 py-1.5 text-sm">
              <span
                className="mt-1.5 h-1.5 w-1.5 flex-none rounded-full"
                style={{ backgroundColor: p.is_user ? ACCENT : '#64748b' }}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold uppercase text-slate-200" title={p.player_key}>
                  {p.player_key}
                </p>
                <p className="font-mono text-xs text-slate-500">
                  {fmtBid(p.price)} · {p.is_user ? 'you' : p.team_id}
                </p>
              </div>
              <button
                type="button"
                onClick={() => onUndo(i)}
                disabled={pending}
                title="Undo this pick"
                className="ml-1 rounded p-1 text-slate-500 opacity-0 transition-opacity hover:text-rose-400 group-hover:opacity-100 disabled:opacity-30"
              >
                <Undo2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        {picks.length === 0 && <p className="py-2 text-xs text-slate-500">No picks logged yet.</p>}
      </div>
    </Card>
  )
}

export function PlanRail(props: {
  budgetSpent: number
  budgetRemaining: number
  budgetTotal: number
  valueBoardRows: DraftPlayerRow[]
  picks: DraftPickEntry[]
  onUndoPick: (index: number) => void
  undoPending: boolean
}) {
  const { budgetSpent, budgetRemaining, budgetTotal, valueBoardRows, picks, onUndoPick, undoPending } = props
  return (
    <div className="space-y-4">
      <BudgetCard spent={budgetSpent} remaining={budgetRemaining} total={budgetTotal} />
      <ValueBoardCard rows={valueBoardRows} />
      <PicksLogCard picks={picks} onUndo={onUndoPick} pending={undoPending} />
    </div>
  )
}
