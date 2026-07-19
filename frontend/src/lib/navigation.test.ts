import { describe, expect, it } from 'vitest'
import { isMoreActive, primaryTabs } from './navigation'
import { recapLeagueSlug } from './supabase'

const active = (label: string, pathname: string) =>
  primaryTabs.find((t) => t.label === label)!.isActive(pathname)

const tabTo = (label: string) => primaryTabs.find((t) => t.label === label)!.to

describe('nav active-state predicates (P-6b)', () => {
  it('Home is active on / and league home, not on scoped subpages', () => {
    expect(active('Home', '/')).toBe(true)
    expect(active('Home', '/leagues/patriot-games')).toBe(true)
    expect(active('Home', '/leagues/patriot-games/standings')).toBe(false)
    expect(active('Home', '/leagues/patriot-games/newsroom/2026/3')).toBe(false)
    expect(active('Home', '/leagues/patriot-games/matchups/3')).toBe(false)
    expect(active('Home', '/leagues/patriot-games/draft')).toBe(false)
  })

  it('Matchup is active on matchups route and legacy /in-season', () => {
    expect(active('Matchup', '/leagues/patriot-games/matchups/3')).toBe(true)
    expect(active('Matchup', '/in-season')).toBe(true)
    expect(active('Matchup', '/leagues/patriot-games')).toBe(false)
  })

  it('Newsroom matches flat /recap, renamed /newsroom/, and legacy /recaps/', () => {
    expect(active('Newsroom', '/recap')).toBe(true)
    expect(active('Newsroom', '/leagues/patriot-games/newsroom/2026/3')).toBe(true)
    expect(active('Newsroom', '/leagues/patriot-games/recaps/2026/3')).toBe(true)
    expect(active('Newsroom', '/leagues/patriot-games')).toBe(false)
  })

  it('Standings matches only the standings route', () => {
    expect(active('Standings', '/leagues/patriot-games/standings')).toBe(true)
    expect(active('Standings', '/leagues/patriot-games')).toBe(false)
  })

  it('More is active on draft, season, and settings surfaces', () => {
    expect(isMoreActive('/leagues/patriot-games/draft')).toBe(true)
    expect(isMoreActive('/season')).toBe(true)
    expect(isMoreActive('/settings')).toBe(true)
    expect(isMoreActive('/leagues/patriot-games')).toBe(false)
  })
})

describe('nav destination targets (P-7)', () => {
  it('resolves each primary tab to the correct path (no hardcoded stale week)', () => {
    expect(tabTo('Home')).toBe(`/leagues/${recapLeagueSlug}`)
    // Matchup goes through /in-season so InSeasonRedirect picks the latest week.
    expect(tabTo('Matchup')).toBe('/in-season')
    expect(tabTo('Matchup')).not.toMatch(/\/matchups\/1$/)
    expect(tabTo('Newsroom')).toBe('/recap')
    expect(tabTo('Standings')).toBe(`/leagues/${recapLeagueSlug}/standings`)
  })
})
