import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PlayoffScheduleCard } from './PlayoffScheduleCard'
import { getPlayoffSchedule } from '../api'

vi.mock('../api', () => ({
  getPlayoffSchedule: vi.fn(),
}))

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <PlayoffScheduleCard slug="patriot-games" />
    </QueryClientProvider>,
  )
}

describe('PlayoffScheduleCard (W-2)', () => {
  it('renders teams sorted by total with week columns', async () => {
    vi.mocked(getPlayoffSchedule).mockResolvedValueOnce({
      playoff_weeks: [20, 21],
      teams: [
        { pro_team: 'OKC', games_by_week: { '20': 4, '21': 4 }, total: 8 },
        { pro_team: 'DEN', games_by_week: { '20': 3, '21': 2 }, total: 5 },
      ],
    })
    renderCard()

    expect(await screen.findByText('OKC')).toBeInTheDocument()
    expect(screen.getByText('DEN')).toBeInTheDocument()
    // Week columns + the weeks range in the subtitle.
    expect(screen.getByText('W20')).toBeInTheDocument()
    expect(screen.getByText('W21')).toBeInTheDocument()
    expect(screen.getByText(/weeks 20–21/)).toBeInTheDocument()
    // Backend order preserved: OKC (best) row precedes DEN.
    const cells = screen.getAllByRole('cell').map((c) => c.textContent)
    expect(cells.indexOf('OKC')).toBeLessThan(cells.indexOf('DEN'))
  })

  it('highlights the best total', async () => {
    vi.mocked(getPlayoffSchedule).mockResolvedValueOnce({
      playoff_weeks: [20],
      teams: [
        { pro_team: 'OKC', games_by_week: { '20': 4 }, total: 4 },
        { pro_team: 'DEN', games_by_week: { '20': 2 }, total: 2 },
      ],
    })
    renderCard()
    const best = await screen.findByText('4', { selector: 'td.font-bold' })
    expect(best).toBeInTheDocument()
  })

  it('shows the pre-release empty state instead of an error', async () => {
    vi.mocked(getPlayoffSchedule).mockResolvedValueOnce({
      playoff_weeks: [20, 21, 22, 23],
      teams: [],
      reason: 'schedule_unavailable',
    })
    renderCard()
    expect(
      await screen.findByText(/NBA schedule not yet released/),
    ).toBeInTheDocument()
  })

  it('explains when league settings have not synced', async () => {
    vi.mocked(getPlayoffSchedule).mockResolvedValueOnce({
      playoff_weeks: [],
      teams: [],
      reason: 'settings_unavailable',
    })
    renderCard()
    expect(
      await screen.findByText(/settings haven’t synced/),
    ).toBeInTheDocument()
  })
})
