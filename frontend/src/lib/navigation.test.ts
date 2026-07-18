import { describe, expect, it } from 'vitest'
import { isMoreActive, primaryTabs } from './navigation'

const active = (label: string, pathname: string) =>
  primaryTabs.find((t) => t.label === label)!.isActive(pathname)

describe('nav active-state predicates (P-6b)', () => {
  it('Home is active on / and league home, not on scoped subpages', () => {
    expect(active('Home', '/')).toBe(true)
    expect(active('Home', '/leagues/patriot-games')).toBe(true)
    expect(active('Home', '/leagues/patriot-games/standings')).toBe(false)
    expect(active('Home', '/leagues/patriot-games/newsroom/2026/3')).toBe(false)
    expect(active('Home', '/leagues/patriot-games/draft')).toBe(false)
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
