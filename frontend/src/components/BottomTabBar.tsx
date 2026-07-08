import { NavLink } from 'react-router-dom'
import { ClipboardList, LayoutDashboard, Newspaper, Trophy } from 'lucide-react'

const tabs = [
  { to: '/draft', label: 'Draft', Icon: ClipboardList },
  { to: '/in-season', label: 'In-Season', Icon: LayoutDashboard },
  { to: '/recap', label: 'Recap', Icon: Newspaper },
  { to: '/season', label: 'Season', Icon: Trophy },
] as const

export function BottomTabBar() {
  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-50 border-t border-pg-border bg-pg-bg/95 backdrop-blur-md md:hidden"
      aria-label="Main"
    >
      <ul className="mx-auto flex max-w-lg items-stretch justify-around px-1 pb-[env(safe-area-inset-bottom)] pt-1">
        {tabs.map(({ to, label, Icon }) => (
          <li key={to} className="flex-1">
            <NavLink
              to={to}
              className={({ isActive }) =>
                [
                  'flex flex-col items-center justify-center gap-0.5 py-2 text-[11px] font-semibold tracking-wide transition-colors',
                  isActive
                    ? 'border-t-2 border-pg-accent text-pg-accent'
                    : 'border-t-2 border-transparent text-slate-500 hover:text-slate-300',
                ].join(' ')
              }
            >
              <Icon className="h-5 w-5" strokeWidth={2.25} aria-hidden />
              <span>{label}</span>
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
