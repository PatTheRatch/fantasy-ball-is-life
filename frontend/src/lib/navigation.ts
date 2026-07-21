import {
  BarChart3,
  ClipboardList,
  House,
  LayoutDashboard,
  Newspaper,
  Trophy,
  type LucideIcon,
} from 'lucide-react'
import { recapLeagueSlug } from './supabase'

/**
 * P-6b/P-7 nav: Home · Matchup · Newsroom · Standings · More.
 * Shared between TopNav (desktop) and BottomTabBar (mobile).
 *
 * N-3: league-scoped links are now dynamic — derive from the current
 * route slug (fallback to recapLeagueSlug at /). Callers should use
 * ``buildPrimaryTabs(slug)`` and ``buildMoreLinks(slug)`` instead of
 * the raw static exports when a route slug is available.
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

/** Static fallback (bare routes with no route slug). */
export const primaryTabs: NavTab[] = buildPrimaryTabs(recapLeagueSlug)

/** Static fallback (bare routes with no route slug). */
export const moreLinks = buildMoreLinks(recapLeagueSlug)

export function buildPrimaryTabs(slug: string): NavTab[] {
  return [
    {
      to: `/leagues/${slug}`,
      label: 'Home',
      Icon: House,
      isActive: (p) =>
        p === '/' ||
        (p.startsWith('/leagues/') &&
          !p.includes('/newsroom/') &&
          !p.includes('/recaps/') &&
          !p.includes('/matchups/') &&
          !p.endsWith('/standings') &&
          !p.endsWith('/draft')),
    },
    {
      to: '/in-season',
      label: 'Matchup',
      Icon: LayoutDashboard,
      isActive: (p) => p.includes('/matchups/') || p.startsWith('/in-season'),
    },
    {
      to: '/recap',
      label: 'Newsroom',
      Icon: Newspaper,
      isActive: (p) =>
        p.startsWith('/recap') || p.includes('/newsroom/') || p.includes('/recaps/'),
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
    { to: '/season', label: 'Season tools', Icon: BarChart3 },
  ]
}

/** True when any "More" destination (or settings) is the current page. */
export function isMoreActive(pathname: string): boolean {
  return (
    moreLinks.some((l) => pathname.startsWith(l.to) || pathname.endsWith('/draft')) ||
    pathname.startsWith('/season') ||
    pathname.startsWith('/settings')
  )
}
