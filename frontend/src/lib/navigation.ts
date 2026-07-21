import {
  BarChart3,
  ClipboardList,
  House,
  LayoutDashboard,
  Newspaper,
  Trophy,
  type LucideIcon,
} from 'lucide-react'

/**
 * P-6b/P-7 nav: Home · Matchup · Newsroom · Standings · More.
 * Shared between TopNav (desktop) and BottomTabBar (mobile).
 *
 * N-3: league-scoped links derive from the active slug — callers pass
 * `useLeagueSlug()` into `buildPrimaryTabs(slug)` / `buildMoreLinks(slug)`
 * so every destination stays inside the league being viewed. Matchup and
 * Newsroom route through per-league resolvers (`/leagues/:slug/matchups`,
 * `/leagues/:slug/newsroom`) that pick the league's season and latest
 * published week server-side.
 */
export interface NavTab {
  to: string
  label: string
  Icon: LucideIcon
  /** Returns true when this tab should render as active for a pathname. */
  isActive: (pathname: string) => boolean
}

export interface NavLink {
  to: string
  label: string
  Icon: LucideIcon
}

export function buildPrimaryTabs(slug: string): NavTab[] {
  return [
    {
      to: `/leagues/${slug}`,
      label: 'Home',
      Icon: House,
      isActive: (p) =>
        p === '/' ||
        (p.startsWith('/leagues/') &&
          !p.includes('/newsroom') &&
          !p.includes('/recaps/') &&
          !p.includes('/matchups') &&
          !p.endsWith('/standings') &&
          !p.endsWith('/draft') &&
          !p.endsWith('/season')),
    },
    {
      to: `/leagues/${slug}/matchups`,
      label: 'Matchup',
      Icon: LayoutDashboard,
      isActive: (p) => p.includes('/matchups') || p.startsWith('/in-season'),
    },
    {
      to: `/leagues/${slug}/newsroom`,
      label: 'Newsroom',
      Icon: Newspaper,
      isActive: (p) =>
        p.startsWith('/recap') || p.includes('/newsroom') || p.includes('/recaps/'),
    },
    {
      to: `/leagues/${slug}/standings`,
      label: 'Standings',
      Icon: Trophy,
      isActive: (p) => p.endsWith('/standings'),
    },
  ]
}

/** Links inside the "More" surface (desktop dropdown / mobile sheet). */
export function buildMoreLinks(slug: string): NavLink[] {
  return [
    { to: `/leagues/${slug}/draft`, label: 'Draft Room', Icon: ClipboardList },
    { to: `/leagues/${slug}/season`, label: 'Season tools', Icon: BarChart3 },
  ]
}

/** True when any "More" destination (or settings) is the current page. */
export function isMoreActive(pathname: string): boolean {
  return (
    pathname.endsWith('/draft') ||
    pathname.endsWith('/season') ||
    pathname.startsWith('/season') ||
    pathname.startsWith('/settings')
  )
}
