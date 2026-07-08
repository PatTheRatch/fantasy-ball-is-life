import type { ReactNode } from 'react'

type CardProps = {
  children: ReactNode
  className?: string
}

export function Card({ children, className = '' }: CardProps) {
  return (
    <div
      className={`rounded-[12px] border border-pg-border bg-pg-card p-4 shadow-[var(--shadow-pg-card)] ${className}`}
    >
      {children}
    </div>
  )
}
