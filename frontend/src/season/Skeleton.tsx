export function Skeleton({ className = '' }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-md bg-slate-700/50 ${className}`}
      aria-hidden
    />
  )
}
