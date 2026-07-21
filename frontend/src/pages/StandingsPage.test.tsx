import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { StandingsPage } from './StandingsPage'

vi.mock('../api', () => ({
  getRecapsCurrent: vi.fn((slug: string) =>
    Promise.resolve(
      slug === 'other-league'
        ? { league: { slug }, season: 2025, archive: [{ week: 3 }] }
        : { league: { slug }, season: 2026, archive: [{ week: 1 }, { week: 5 }] },
    ),
  ),
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

function renderAt(path: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [{ path: '/leagues/:slug/standings', element: <StandingsPage /> }],
    { initialEntries: [path] },
  )
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

describe('StandingsPage', () => {
  it('resolves the latest published week and renders StandingsTab with it', async () => {
    renderAt('/leagues/patriot-games/standings')
    const tab = await screen.findByTestId('standings-tab')
    expect(tab).toHaveTextContent('patriot-games:2026:5')
  })

  it("N-3: uses the league's own configured season for a non-default slug", async () => {
    renderAt('/leagues/other-league/standings')
    const tab = await screen.findByTestId('standings-tab')
    expect(tab).toHaveTextContent('other-league:2025:3')
  })
})
