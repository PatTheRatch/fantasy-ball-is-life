import type { ReactNode } from 'react'

/* -------------------------------------------------------------------------- */
/* Badge — unified badge with semantic variants                               */
/* -------------------------------------------------------------------------- */

export type BadgeVariant =
  | 'default'
  | 'accent'
  | 'positive'
  | 'negative'
  | 'warning'
  | 'info'
  | 'ai'

interface BadgeProps {
  children: ReactNode
  variant?: BadgeVariant
  className?: string
}

const variantStyles: Record<BadgeVariant, string> = {
  default: 'bg-slate-800 text-slate-300 border-slate-700',
  accent: 'bg-red-900/30 text-red-400 border-red-800/40',
  positive: 'bg-emerald-900/30 text-emerald-400 border-emerald-800/40',
  negative: 'bg-red-900/30 text-red-400 border-red-800/40',
  warning: 'bg-amber-900/30 text-amber-400 border-amber-800/40',
  info: 'bg-sky-900/30 text-sky-400 border-sky-800/40',
  ai: 'bg-purple-900/30 text-purple-400 border-purple-800/40',
}

export function Badge({ children, variant = 'default', className = '' }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${variantStyles[variant]} ${className}`}
    >
      {children}
    </span>
  )
}

/* -------------------------------------------------------------------------- */
/* AiTakeBadge — indicates AI-generated content                               */
/* -------------------------------------------------------------------------- */

export function AiTakeBadge({ className = '' }: { className?: string }) {
  return (
    <Badge variant="ai" className={className}>
      AI
    </Badge>
  )
}

/* -------------------------------------------------------------------------- */
/* RankPill — colored number pill for power ranking sub-ranks                 */
/* -------------------------------------------------------------------------- */

interface RankPillProps {
  rank: number
  label: string
  className?: string
}

function rankPillVariant(rank: number): BadgeVariant {
  if (rank <= 3) return 'positive'
  if (rank <= 7) return 'warning'
  return 'negative'
}

export function RankPill({ rank, label, className = '' }: RankPillProps) {
  return (
    <Badge variant={rankPillVariant(rank)} className={className}>
      {label} #{rank}
    </Badge>
  )
}

/* -------------------------------------------------------------------------- */
/* MovementBadge — directional change indicator (+3, -1, —)                  */
/* -------------------------------------------------------------------------- */

interface MovementBadgeProps {
  change: number | null | undefined
  className?: string
}

export function MovementBadge({ change, className = '' }: MovementBadgeProps) {
  if (change == null || !Number.isFinite(change)) {
    return (
      <span className={`text-xs font-semibold text-slate-600 tabular-nums ${className}`}>
        —
      </span>
    )
  }

  const variant: BadgeVariant = change > 0 ? 'positive' : change < 0 ? 'negative' : 'default'
  const arrow = change > 0 ? '▲' : change < 0 ? '▼' : ''
  return (
    <Badge variant={variant} className={className}>
      {arrow}{Math.abs(change)}
    </Badge>
  )
}

/* -------------------------------------------------------------------------- */
/* WinLossBadge — W / L / T indicator                                         */
/* -------------------------------------------------------------------------- */

interface WinLossBadgeProps {
  result: 'W' | 'L' | 'T' | string
  className?: string
}

export function WinLossBadge({ result, className = '' }: WinLossBadgeProps) {
  const r = String(result).trim().toUpperCase()
  const variant: BadgeVariant =
    r === 'W' ? 'positive' : r === 'L' ? 'negative' : 'warning'
  return (
    <Badge variant={variant} className={`min-w-[1.8em] justify-center text-center ${className}`}>
      {r}
    </Badge>
  )
}
