import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

/** Shared input styling for the auth forms. */
export const authInputClass =
  'min-h-11 w-full rounded-lg border border-pg-border bg-pg-bg px-3 text-sm text-white outline-none focus:border-pg-accent'

/** Shared primary-button styling for the auth forms. */
export const authButtonClass =
  'min-h-11 w-full rounded-lg bg-pg-accent px-4 text-sm font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50'

/** Centered card layout for the standalone auth pages (login/signup/reset). */
export function AuthShell({
  title,
  subtitle,
  children,
  footer,
}: {
  title: string
  subtitle?: string
  children: ReactNode
  footer?: ReactNode
}) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center bg-pg-bg px-4 py-12">
      <div className="w-full max-w-sm">
        <Link
          to="/"
          className="mb-8 block text-center text-lg font-bold tracking-tight text-white"
        >
          Full Court Press
        </Link>
        <div className="rounded-pg-lg border border-pg-border bg-pg-card p-6 shadow-xl">
          <h1 className="text-xl font-bold text-white">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
          <div className="mt-6">{children}</div>
        </div>
        {footer && (
          <p className="mt-6 text-center text-sm text-slate-400">{footer}</p>
        )}
      </div>
    </div>
  )
}
