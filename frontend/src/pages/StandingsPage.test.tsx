import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { StandingsPage } from './StandingsPage'

vi.mock('../api', () => ({
  getPublishedArchive: vi.fn().mockResolvedValue([{ week: 1 }, { week: 5 }]),
}))

vi.mock('../components/StandingsTab', () => ({
  StandingsTab: ({
    slug,
    season,
    week,
  }: {
    slug: string
    season: number
    week: number
  }) => <div data-testid="standings-tab">{`${slug}:${season}:${week}`}</div>,
}))

describe('StandingsPage', () => {
  it('resolves the latest published week and renders StandingsTab with it', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const router = createMemoryRouter(
      [{ path: '/leagues/:slug/standings', element: <StandingsPage /> }],
      { initialEntries: ['/leagues/patriot-games/standings'] },
    )
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    )

    const tab = await screen.findByTestId('standings-tab')
    expect(tab).toHaveTextContent('patriot-games:2026:5')
  })
})
