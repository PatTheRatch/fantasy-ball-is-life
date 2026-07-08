import { NavLink } from 'react-router-dom'
import { ClipboardList, LayoutDashboard, Newspaper, Trophy } from 'lucide-react'

const tabs = [
  { to: '/draft', label: 'Draft', Icon: ClipboardList },
  { to: '/in-season', label: 'In-Season', Icon: LayoutDashboard },
  { to: '/recap', label: 'Recap', Icon: Newspaper },
  { to: '/season', label: 'Season', Icon: Trophy },
] as const

export function TopNav() {
  return (
    <header className="sticky top-0 z-40 hidden border-b border-pg-border bg-pg-bg/90 backdrop-blur-md md:block">
      <div className="mx-auto flex max-w-6xl items-center gap-8 px-6 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <span className="truncate text-lg font-bold tracking-tight text-white">
            PatriotGames Fantasy
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
          {tabs.map(({ to, label, Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                [
                  'flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors',
                  isActive
                    ? 'bg-pg-accent/15 text-pg-accent'
                    : 'text-slate-400 hover:bg-white/5 hover:text-slate-200',
                ].join(' ')
              }
            >
              <Icon className="h-4 w-4" strokeWidth={2} aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
      </div>
    </header>
  )
}
