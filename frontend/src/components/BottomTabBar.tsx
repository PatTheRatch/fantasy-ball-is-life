import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { LogIn, LogOut, Menu, Settings as SettingsIcon } from 'lucide-react'
import { useAuth } from '../lib/authContext'
import { isMoreActive, moreLinks, primaryTabs } from '../lib/navigation'

const tabClass = (active: boolean) =>
  [
    'flex w-full flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-semibold tracking-wide transition-colors',
    active
      ? 'border-t-2 border-pg-accent text-pg-accent'
      : 'border-t-2 border-transparent text-slate-500 hover:text-slate-300',
  ].join(' ')

/**
 * Mobile "More" sheet: Draft Room, Season tools, Settings, sign in/out.
 * Also the mobile home of the account affordance (the P-5 profile menu is
 * desktop-only).
 */
function MoreSheet({ onClose }: { onClose: () => void }) {
  const { session, user, signOut } = useAuth()

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const itemClass =
    'flex items-center gap-3 px-5 py-3.5 text-sm font-semibold text-slate-200 transition-colors hover:bg-white/5'

  return (
    <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-label="More">
      <button
        type="button"
        aria-label="Close menu"
        onClick={onClose}
        className="absolute inset-0 bg-black/60"
      />
      <div className="absolute inset-x-0 bottom-0 rounded-t-2xl border-t border-pg-border bg-pg-card pb-[env(safe-area-inset-bottom)] shadow-2xl">
        <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-slate-700" aria-hidden />
        <nav className="mt-2 pb-2" aria-label="More">
          {moreLinks.map(({ to, label, Icon }) => (
            <Link key={to} to={to} onClick={onClose} className={itemClass}>
              <Icon className="h-5 w-5 text-slate-400" aria-hidden />
              {label}
            </Link>
          ))}
          <Link to="/settings" onClick={onClose} className={itemClass}>
            <SettingsIcon className="h-5 w-5 text-slate-400" aria-hidden />
            Settings
          </Link>
          <div className="mt-1 border-t border-pg-border pt-1">
            {session ? (
              <button
                type="button"
                onClick={() => {
                  onClose()
                  void signOut()
                }}
                className={`${itemClass} w-full text-left`}
              >
                <LogOut className="h-5 w-5 text-slate-400" aria-hidden />
                Sign out
                {user?.email && (
                  <span className="ml-auto max-w-[45%] truncate text-xs font-normal text-slate-500">
                    {user.email}
                  </span>
                )}
              </button>
            ) : (
              <Link to="/login" onClick={onClose} className={itemClass}>
                <LogIn className="h-5 w-5 text-slate-400" aria-hidden />
                Sign in
              </Link>
            )}
          </div>
        </nav>
      </div>
    </div>
  )
}

export function BottomTabBar() {
  const { pathname } = useLocation()
  const [moreOpen, setMoreOpen] = useState(false)

  return (
    <>
      <nav
        className="fixed bottom-0 left-0 right-0 z-50 border-t border-pg-border bg-pg-bg/95 backdrop-blur-md md:hidden"
        aria-label="Main"
      >
        <ul className="mx-auto flex max-w-lg items-stretch justify-around px-1 pb-[env(safe-area-inset-bottom)] pt-1">
          {primaryTabs.map(({ to, label, Icon, isActive }) => (
            <li key={to} className="flex-1">
              <Link to={to} className={tabClass(isActive(pathname))}>
                <Icon className="h-5 w-5" strokeWidth={2.25} aria-hidden />
                <span>{label}</span>
              </Link>
            </li>
          ))}
          <li className="flex-1">
            <button
              type="button"
              onClick={() => setMoreOpen(true)}
              aria-haspopup="dialog"
              aria-expanded={moreOpen}
              className={tabClass(isMoreActive(pathname))}
            >
              <Menu className="h-5 w-5" strokeWidth={2.25} aria-hidden />
              <span>More</span>
            </button>
          </li>
        </ul>
      </nav>
      {moreOpen && <MoreSheet onClose={() => setMoreOpen(false)} />}
    </>
  )
}
