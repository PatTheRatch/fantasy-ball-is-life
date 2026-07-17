import { useState, useEffect } from 'react'

/* -------------------------------------------------------------------------- */
/* Skeleton — animated placeholder for loading states                         */
/* -------------------------------------------------------------------------- */

interface SkeletonProps {
  className?: string
}

export function Skeleton({ className = '' }: SkeletonProps) {
  return (
    <div
      className={`animate-pulse rounded-md bg-slate-700/50 ${className}`}
      aria-hidden
    />
  )
}

/* -------------------------------------------------------------------------- */
/* Staleness stamp — "as of" indicator when data is older than threshold      */
/* -------------------------------------------------------------------------- */

interface StaleBadgeProps {
  fetchedAt: string | null | undefined
  className?: string
}

export function StaleBadge({ fetchedAt, className = '' }: StaleBadgeProps) {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    setNow(Date.now())
    const interval = setInterval(() => setNow(Date.now()), 60_000)
    return () => clearInterval(interval)
  }, [])

  if (!fetchedAt) return null

  const fetched = new Date(fetchedAt)
  const minutesAgo = Math.floor((now - fetched.getTime()) / 60_000)

  if (minutesAgo < 5) return null // still fresh

  const label =
    minutesAgo < 60
      ? `${minutesAgo}m ago`
      : `${Math.floor(minutesAgo / 60)}h ago`

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border border-amber-700/40 bg-amber-900/30 px-2 py-0.5 text-[10px] font-medium text-amber-400 ${className}`}
      title={`Data fetched ${fetched.toLocaleString()}`}
    >
      as of {label}
    </span>
  )
}
