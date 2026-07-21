import { matchPath, useLocation, useParams } from 'react-router-dom'
import { recapLeagueSlug } from './supabase'

/**
 * N-3: Returns the active league slug — from the route param when inside
 * a `/leagues/:slug/...` route, falling back to the default league for
 * bare/redirect routes (`/recap`, `/draft`, `/season`, etc.) that don't
 * yet know their league.
 *
 * Layout chrome (TopNav, BottomTabBar) renders outside the matched child
 * route, where `useParams` cannot see `:slug` — so we also match the
 * pathname directly.
 */
export function useLeagueSlug(): string {
  const { slug } = useParams<{ slug?: string }>()
  const { pathname } = useLocation()
  if (slug) return slug
  const match = matchPath({ path: '/leagues/:slug/*' }, pathname)
  return match?.params.slug ?? recapLeagueSlug
}
