import type { CSSProperties, ReactNode } from 'react'

type CardProps = {
  children: ReactNode
  className?: string
  style?: CSSProperties
}

export function Card({ children, className = '', style }: CardProps) {
  return (
    <div
      className={`rounded-[12px] border border-pg-border bg-pg-card p-4 shadow-[var(--shadow-pg-card)] ${className}`}
      style={style}
    >
      {children}
    </div>
  )
}
