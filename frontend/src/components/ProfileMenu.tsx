import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { LogOut, Settings as SettingsIcon } from 'lucide-react'
import { useAuth } from '../lib/authContext'

/**
 * Profile affordance for the top nav (P-5). Signed out → a "Sign in" link;
 * signed in → an avatar-initial button opening a menu with the account email,
 * Settings, and Sign out.
 */
export function ProfileMenu() {
  const { session, user, loading, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointer = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false)
      }
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (loading) {
    return <div className="h-9 w-9" aria-hidden />
  }

  if (!session) {
    return (
      <Link
        to="/login"
        className="rounded-lg px-3 py-2 text-sm font-semibold text-slate-300 transition-colors hover:bg-white/5 hover:text-white"
      >
        Sign in
      </Link>
    )
  }

  const email = user?.email ?? ''
  const initial = email.charAt(0).toUpperCase() || '?'

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        className="flex h-9 w-9 items-center justify-center rounded-full bg-pg-accent/20 text-sm font-bold text-pg-accent transition-colors hover:bg-pg-accent/30"
      >
        {initial}
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-2 w-56 overflow-hidden rounded-pg-lg border border-pg-border bg-pg-card shadow-xl"
        >
          <div className="border-b border-pg-border px-3 py-2">
            <p className="truncate text-sm font-medium text-white">{email}</p>
            <p className="text-xs text-slate-500">Signed in</p>
          </div>
          <Link
            to="/settings"
            role="menuitem"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 px-3 py-2 text-sm text-slate-300 transition-colors hover:bg-white/5 hover:text-white"
          >
            <SettingsIcon className="h-4 w-4" aria-hidden />
            Settings
          </Link>
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false)
              void signOut()
            }}
            className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-300 transition-colors hover:bg-white/5 hover:text-white"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            Sign out
          </button>
        </div>
      )}
    </div>
  )
}
