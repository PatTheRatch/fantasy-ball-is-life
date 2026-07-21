import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ChevronDown } from 'lucide-react'
import { buildMoreLinks, buildPrimaryTabs, isMoreActive, type NavLink } from '../lib/navigation'
import { useLeagueSlug } from '../lib/useLeagueSlug'
import { ProfileMenu } from './ProfileMenu'

const linkClass = (active: boolean) =>
  [
    'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors',
    active
      ? 'bg-pg-accent/15 text-pg-accent'
      : 'text-slate-400 hover:bg-white/5 hover:text-slate-200',
  ].join(' ')

/** Desktop "More" dropdown: Draft Room + Season tools (account lives in ProfileMenu). */
function MoreMenu({ pathname, links }: { pathname: string; links: NavLink[] }) {
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

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={linkClass(isMoreActive(pathname))}
      >
        More <ChevronDown className="h-3.5 w-3.5" aria-hidden />
      </button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 z-50 mt-2 w-48 overflow-hidden rounded-pg-lg border border-pg-border bg-pg-card shadow-xl"
        >
          {links.map(({ to, label, Icon }) => (
            <Link
              key={to}
              to={to}
              role="menuitem"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 px-3 py-2 text-sm text-slate-300 transition-colors hover:bg-white/5 hover:text-white"
            >
              <Icon className="h-4 w-4" aria-hidden />
              {label}
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

export function TopNav() {
  const { pathname } = useLocation()
  const slug = useLeagueSlug()
  const primaryTabs = buildPrimaryTabs(slug)
  const moreLinks = buildMoreLinks(slug)
  return (
    <header className="sticky top-0 z-40 hidden border-b border-pg-border bg-pg-bg/90 backdrop-blur-md md:block">
      <div className="mx-auto flex max-w-6xl items-center gap-8 px-6 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="truncate text-lg font-bold tracking-tight text-white">
            Full Court Press
          </span>
          <span
            className="hidden h-5 w-px bg-pg-border lg:block"
            aria-hidden
          />
          <span className="hidden text-sm text-slate-500 lg:inline">
            Fantasy basketball
          </span>
        </div>
        <nav aria-label="Main" className="flex items-center gap-1">
          {primaryTabs.map(({ to, label, Icon, isActive }) => (
            <Link key={to} to={to} className={linkClass(isActive(pathname))}>
              <Icon className="h-4 w-4" strokeWidth={2} aria-hidden />
              {label}
            </Link>
          ))}
          <MoreMenu pathname={pathname} links={moreLinks} />
        </nav>
        <ProfileMenu />
      </div>
    </header>
  )
}
