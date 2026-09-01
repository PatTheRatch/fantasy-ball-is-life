import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient, getScoreboardCurrent } from './api'
import { enrichCurrentRows } from './lib/inSeasonUtils'

afterEach(() => {
  vi.restoreAllMocks()
})

/**
 * GET /leagues/{slug}/scoreboard/current returns the snapshot envelope
 * `{ data, fetched_at }` — the same shape as /standings, /settings and
 * /power-rankings (backend/api/routers/league.py). getScoreboardCurrent
 * must unwrap it like getLeagueStandings does, because its only consumer
 * (fetchCurrentMatchupGroups -> enrichCurrentRows) calls .map() on the
 * result.
 */
describe('getScoreboardCurrent unwraps the snapshot envelope', () => {
  const ROWS = [
    { stat: 'PTS', current_home_score: 812, current_away_score: 790 },
    { stat: 'REB', current_home_score: 331, current_away_score: 344 },
  ]

  it('returns the inner array, not the envelope', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { data: ROWS, fetched_at: '2026-01-05T00:00:00Z' },
    })

    const result = await getScoreboardCurrent('patriot-games', 8)

    expect(Array.isArray(result)).toBe(true)
    expect(result).toHaveLength(2)
    expect(result[0].stat).toBe('PTS')
  })

  it('the result flows into enrichCurrentRows without throwing', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { data: ROWS, fetched_at: null },
    })

    const rows = await getScoreboardCurrent('patriot-games', 8)

    // Before the fix this threw "rows.map is not a function", because the
    // envelope object was handed straight to enrichCurrentRows.
    expect(() => enrichCurrentRows(rows)).not.toThrow()
    expect(enrichCurrentRows(rows)).toHaveLength(2)
  })

  it('an empty snapshot yields [] rather than undefined', async () => {
    vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { data: null, fetched_at: null },
    })

    const result = await getScoreboardCurrent('patriot-games', 8)

    expect(result).toEqual([])
  })
})
