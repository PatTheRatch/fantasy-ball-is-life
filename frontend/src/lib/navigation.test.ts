import { describe, expect, it } from 'vitest'
import { buildMoreLinks, buildPrimaryTabs, isMoreActive } from './navigation'

const tabs = (slug: string) => buildPrimaryTabs(slug)
const active = (slug: string, label: string, pathname: string) =>
  tabs(slug).find((t) => t.label === label)!.isActive(pathname)
const tabTo = (slug: string, label: string) =>
  tabs(slug).find((t) => t.label === label)!.to

describe('nav active-state predicates (P-6b, N-3)', () => {
  it('Home is active on / and league home, not on scoped subpages', () => {
    expect(active('patriot-games', 'Home', '/')).toBe(true)
    expect(active('patriot-games', 'Home', '/leagues/patriot-games')).toBe(true)
    expect(active('patriot-games', 'Home', '/leagues/patriot-games/standings')).toBe(false)
    expect(active('patriot-games', 'Home', '/leagues/patriot-games/newsroom/2026/3')).toBe(false)
    expect(active('patriot-games', 'Home', '/leagues/patriot-games/matchups/3')).toBe(false)
    expect(active('patriot-games', 'Home', '/leagues/patriot-games/draft')).toBe(false)
    // N-3 resolver + season routes are not "Home"
    expect(active('patriot-games', 'Home', '/leagues/patriot-games/matchups')).toBe(false)
    expect(active('patriot-games', 'Home', '/leagues/patriot-games/newsroom')).toBe(false)
    expect(active('patriot-games', 'Home', '/leagues/patriot-games/season')).toBe(false)
  })

  it('Matchup is active on final week route, resolver route, and legacy /in-season', () => {
    expect(active('x', 'Matchup', '/leagues/x/matchups/3')).toBe(true)
    expect(active('x', 'Matchup', '/leagues/x/matchups')).toBe(true)
    expect(active('x', 'Matchup', '/in-season')).toBe(true)
    expect(active('x', 'Matchup', '/leagues/x')).toBe(false)
  })

  it('Newsroom matches flat /recap, resolver, renamed /newsroom/, and legacy /recaps/', () => {
    expect(active('x', 'Newsroom', '/recap')).toBe(true)
    expect(active('x', 'Newsroom', '/leagues/x/newsroom')).toBe(true)
    expect(active('x', 'Newsroom', '/leagues/x/newsroom/2026/3')).toBe(true)
    expect(active('x', 'Newsroom', '/leagues/x/recaps/2026/3')).toBe(true)
    expect(active('x', 'Newsroom', '/leagues/x')).toBe(false)
  })

  it('Standings matches only the standings route', () => {
    expect(active('x', 'Standings', '/leagues/x/standings')).toBe(true)
    expect(active('x', 'Standings', '/leagues/x')).toBe(false)
  })

  it('More is active on draft, season (bare and scoped), and settings surfaces', () => {
    expect(isMoreActive('/leagues/x/draft')).toBe(true)
    expect(isMoreActive('/season')).toBe(true)
    expect(isMoreActive('/leagues/x/season')).toBe(true)
    expect(isMoreActive('/settings')).toBe(true)
    expect(isMoreActive('/leagues/x')).toBe(false)
  })
})

describe('nav destination targets (N-3: every destination retains the slug)', () => {
  it('builds all primary destinations inside the given league', () => {
    expect(tabTo('other-league', 'Home')).toBe('/leagues/other-league')
    expect(tabTo('other-league', 'Matchup')).toBe('/leagues/other-league/matchups')
    expect(tabTo('other-league', 'Newsroom')).toBe('/leagues/other-league/newsroom')
    expect(tabTo('other-league', 'Standings')).toBe('/leagues/other-league/standings')
  })

  it('Matchup goes through the per-league resolver, never a hardcoded week', () => {
    expect(tabTo('other-league', 'Matchup')).not.toMatch(/\/matchups\/\d+$/)
  })

  it('More links (Draft Room, Season tools) retain the slug', () => {
    const links = buildMoreLinks('other-league')
    expect(links.map((l) => l.to)).toEqual([
      '/leagues/other-league/draft',
      '/leagues/other-league/season',
    ])
  })

  it('two different slugs never share a league-scoped destination', () => {
    const a = buildPrimaryTabs('league-a').map((t) => t.to)
    const b = buildPrimaryTabs('league-b').map((t) => t.to)
    a.forEach((to, i) => expect(to).not.toBe(b[i]))
  })
})
