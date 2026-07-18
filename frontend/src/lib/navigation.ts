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
 * P-6b nav restructure (spec §5): Home · Matchup · Newsroom · Standings · More.
 * Shared between TopNav (desktop) and BottomTabBar (mobile) — previously each
 * kept its own copy of the tab list.
 *
 * Single-league interim: league-scoped links resolve via the configured slug,
 * the same way Recap.tsx resolves its redirect target.
 *
 * "Matchup" points at the In-Season page until P-7 promotes matchup detail to
 * `/leagues/:slug/matchups/:week`.
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
        !p.endsWith('/standings') &&
        !p.endsWith('/draft')),
  },
  {
    to: '/in-season',
    label: 'Matchup',
    Icon: LayoutDashboard,
    isActive: (p) => p.startsWith('/in-season'),
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
