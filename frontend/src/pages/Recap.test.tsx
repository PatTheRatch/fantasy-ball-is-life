import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { Recap } from './Recap'

vi.mock('../api', () => ({
  getRecapsCurrent: vi.fn((slug: string) =>
    Promise.resolve(
      slug === 'other-league'
        ? { league: { slug }, season: 2025, archive: [{ week: 4 }] }
        : { league: { slug }, season: 2026, archive: [] },
    ),
  ),
}))

function renderAt(entry: string) {
  const router = createMemoryRouter(
    [
      { path: '/recap', element: <Recap /> },
      { path: '/leagues/:slug/newsroom', element: <Recap /> },
      {
        path: '/leagues/:slug/newsroom/:season/:week',
        element: <div>newsroom</div>,
      },
    ],
    { initialEntries: [entry] },
  )
  render(<RouterProvider router={router} />)
  return router
}

describe('Recap (flat → newsroom redirect)', () => {
  it('/recap?week=5 → /leagues/{slug}/newsroom/{season}/5', async () => {
    const router = renderAt('/recap?week=5')
    expect(await screen.findByText('newsroom')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe(
      '/leagues/patriot-games/newsroom/2026/5',
    )
  })

  it('bare /recap with no published weeks → newsroom week 1', async () => {
    const router = renderAt('/recap')
    expect(await screen.findByText('newsroom')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe(
      '/leagues/patriot-games/newsroom/2026/1',
    )
  })
})

describe('Newsroom resolver (N-3, league-scoped)', () => {
  it("/leagues/:slug/newsroom keeps the slug and uses that league's season + latest week", async () => {
    const router = renderAt('/leagues/other-league/newsroom')
    expect(await screen.findByText('newsroom')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe(
      '/leagues/other-league/newsroom/2025/4',
    )
  })
})
