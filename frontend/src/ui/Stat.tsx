import type { ReactNode } from 'react'

/* -------------------------------------------------------------------------- */
/* Stat — label + value pair for dashboard widgets                            */
/* -------------------------------------------------------------------------- */

interface StatProps {
  label: string
  value: ReactNode
  /** Directional change indicator: positive = up/green, negative = down/red */
  delta?: number | null
  className?: string
}

export function Stat({ label, value, delta, className = '' }: StatProps) {
  return (
    <div className={`flex flex-col gap-0.5 ${className}`}>
      <span className="text-xs font-medium uppercase tracking-wider text-slate-500">
        {label}
      </span>
      <div className="flex items-baseline gap-1.5">
        <span className="text-2xl font-bold tabular-nums text-white">
          {value}
        </span>
        {delta != null && delta !== 0 && (
          <span
            className={`text-xs font-semibold tabular-nums ${
              delta > 0 ? 'text-emerald-400' : 'text-red-400'
            }`}
          >
            {delta > 0 ? '▲' : '▼'}
            {Math.abs(delta)}
          </span>
        )}
      </div>
    </div>
  )
}
