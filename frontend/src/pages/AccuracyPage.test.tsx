import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { AccuracyPage } from './AccuracyPage'
import type { ProjectionAccuracyResponse } from '../api'

const populated: ProjectionAccuracyResponse = {
  league: 'fcp',
  season: 2025,
  weeks_with_actuals: [1, 2],
  sources: [
    {
      source: 'bbm',
      weeks_scored: 2,
      per_category: {
        PTS: { mae: 12.5, mae_pct: 0.031, bias: 4.2, rank_corr: 0.85, weeks: 2 },
        'FG%': { mae: 0.011, mae_pct: 0.024, bias: -0.004, rank_corr: 0.6, weeks: 2 },
      },
    },
    {
      source: 'espn',
      weeks_scored: 2,
      per_category: {
        PTS: { mae: 18.0, mae_pct: 0.044, bias: -6.0, rank_corr: 0.55, weeks: 2 },
      },
    },
  ],
  weeks: [
    {
      source: 'bbm',
      week: 1,
      set_id: 'abc123',
      uploaded_at: '2025-11-03T09:00:00Z',
      players_unassigned: 3,
      teams_matched: 8,
      teams_total: 8,
      per_category: {
        PTS: { mae: 12.5, mae_pct: 0.031, bias: 4.2, rank_corr: 0.85, teams: 8 },
      },
    },
  ],
  unscoreable: [{ source: 'espn', week: 3, reason: 'week_in_progress' }],
}

const empty: ProjectionAccuracyResponse = {
  league: 'fcp',
  season: 2025,
  weeks_with_actuals: [],
  sources: [],
  weeks: [],
  unscoreable: [],
}

vi.mock('../api', () => ({
  getProjectionAccuracy: vi.fn((slug: string) =>
    Promise.resolve(slug === 'empty-league' ? empty : populated),
  ),
}))

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [{ path: '/leagues/:slug/accuracy', element: <AccuracyPage /> }],
    { initialEntries: [path] },
  )
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('AccuracyPage', () => {
  it('renders the source-vs-source summary with MAE% and rank correlation', async () => {
    renderAt('/leagues/fcp/accuracy')
    expect(await screen.findByText('Source vs source', { exact: false })).toBeInTheDocument()
    // Both sources appear (summary columns; BBM also in the weeks table)
    expect(screen.getAllByText('BBM').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('ESPN').length).toBeGreaterThanOrEqual(1)
    // BBM PTS: mae_pct 0.031 → "3.1%", rank_corr 0.85 → "ρ 0.85"
    expect(screen.getByText('3.1%')).toBeInTheDocument()
    expect(screen.getByText('ρ 0.85')).toBeInTheDocument()
    // ESPN has no FG% sample → em-dash cell renders (missing category)
    expect(screen.getByText('FG%')).toBeInTheDocument()
  })

  it('renders scored weeks with coverage and unassigned-player counts', async () => {
    renderAt('/leagues/fcp/accuracy')
    expect(await screen.findByText('Scored weeks')).toBeInTheDocument()
    expect(screen.getByText('W1')).toBeInTheDocument()
    expect(screen.getByText('8/8')).toBeInTheDocument()
    // players_unassigned = 3, highlighted
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('explains unscoreable weeks in plain language', async () => {
    renderAt('/leagues/fcp/accuracy')
    expect(
      await screen.findByText('ESPN week 3 — week still in progress', { exact: false }),
    ).toBeInTheDocument()
  })

  it('shows the honest empty state when nothing is scoreable yet', async () => {
    renderAt('/leagues/empty-league/accuracy')
    expect(
      await screen.findByText('Nothing scoreable yet', { exact: false }),
    ).toBeInTheDocument()
  })
})
