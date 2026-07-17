import type { ReactNode } from 'react'

export type CardVariant = 'default' | 'editorial' | 'ghost'

interface CardProps {
  children: ReactNode
  variant?: CardVariant
  className?: string
}

const variantStyles: Record<CardVariant, string> = {
  default: 'rounded-xl border border-pg-border bg-pg-card',
  editorial: 'rounded-2xl border border-pg-border bg-gradient-to-b from-pg-card to-pg-bg',
  ghost: 'rounded-xl border border-transparent bg-transparent',
}

export function Card({ children, variant = 'default', className = '' }: CardProps) {
  return <div className={`${variantStyles[variant]} ${className}`}>{children}</div>
}
