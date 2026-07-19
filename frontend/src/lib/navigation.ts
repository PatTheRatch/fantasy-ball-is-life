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
 * Single-league interim: league-scoped links resolve via the configured slug.
 * Matchup → `/in-season`, which InSeasonRedirect resolves to the latest
 * published week at `/leagues/:slug/matchups/:week` (avoids a stale hardcoded week).
 */
export interface NavTab {
  to: string
  label: string
  Icon: LucideIcon
  /** Returns true when this tab should render as active for a pathname. */
  isActive: (pathname: string) => boolean
}

export const primaryTabs: NavTab[] = [
  {
    to: `/leagues/${recapLeagueSlug}`,
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
    to: `/leagues/${recapLeagueSlug}/standings`,
    label: 'Standings',
    Icon: Trophy,
    isActive: (p) => p.endsWith('/standings'),
  },
]

/** Links inside the "More" surface (desktop dropdown / mobile sheet). */
export const moreLinks = [
  {
    to: `/leagues/${recapLeagueSlug}/draft`,
    label: 'Draft Room',
    Icon: ClipboardList,
  },
  { to: '/season', label: 'Season tools', Icon: BarChart3 },
] as const

/** True when any "More" destination (or settings) is the current page. */
export function isMoreActive(pathname: string): boolean {
  return (
    moreLinks.some((l) => pathname.startsWith(l.to) || pathname.endsWith('/draft')) ||
    pathname.startsWith('/season') ||
    pathname.startsWith('/settings')
  )
}
