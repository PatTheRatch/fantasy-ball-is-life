import type { DraftPlanSnapshot } from '../api'

export function fmtBid(n: number | null | undefined): string {
  return n == null ? '—' : `$${Math.round(n)}`
}

export function fmtStat(n: number | null | undefined, digits = 1): string {
  return n == null ? '—' : n.toFixed(digits)
}

export function fmtPct(n: number | null | undefined): string {
  return n == null ? '—' : `${(n * 100).toFixed(1)}%`
}

/** The always-on fallback the "never freeze" guarantee depends on (spec §2
 * criterion 2): first still-Alive plan, in portfolio order. Used client-side
 * after a local edit (e.g. accepting a relax proposal) without a round-trip. */
export function firstAlive(plans: DraftPlanSnapshot[]): DraftPlanSnapshot | null {
  return plans.find((p) => p.health === 'alive') ?? null
}

export function healthPillClass(health: 'alive' | 'broken'): string {
  return health === 'alive'
    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400'
    : 'border-rose-500/40 bg-rose-500/10 text-rose-400'
}
