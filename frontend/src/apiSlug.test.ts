import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  apiClient,
  getLeagueSettings,
  getLeagueTeams,
  getPowerRankings,
  getScoreboardCurrent,
} from './api'

afterEach(() => {
  vi.restoreAllMocks()
})

function spyGet() {
  return vi
    .spyOn(apiClient, 'get')
    .mockResolvedValue({ data: { data: [], fetched_at: null } })
}

describe('league API helpers (N-3: URLs are slug-scoped)', () => {
  it('different slugs produce different URLs for the same helper', async () => {
    const spy = spyGet()
    await getLeagueTeams('league-a')
    await getLeagueTeams('league-b')
    expect(spy.mock.calls[0][0]).toBe('/leagues/league-a/teams')
    expect(spy.mock.calls[1][0]).toBe('/leagues/league-b/teams')
  })

  it('settings, power rankings, and scoreboard all hit /leagues/{slug}/…', async () => {
    const spy = spyGet()
    await getLeagueSettings('other-league')
    await getPowerRankings('other-league', '1,2,3', 3)
    await getScoreboardCurrent('other-league', 4)
    const urls = spy.mock.calls.map((c) => c[0])
    expect(urls).toEqual([
      '/leagues/other-league/settings',
      '/leagues/other-league/power-rankings',
      '/leagues/other-league/scoreboard/current',
    ])
  })
})
