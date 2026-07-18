import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { HomeResolver } from './HomeResolver'
import { useAuth } from '../lib/authContext'
import { getMyLeagues } from '../lib/memberships'

vi.mock('../lib/authContext', () => ({ useAuth: vi.fn() }))
vi.mock('../lib/memberships', () => ({ getMyLeagues: vi.fn() }))

const mockUseAuth = vi.mocked(useAuth)
const mockGetMyLeagues = vi.mocked(getMyLeagues)

function renderResolver() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  const router = createMemoryRouter(
    [
      { path: '/', element: <HomeResolver /> },
      { path: '/leagues/:slug', element: <div>league-home</div> },
    ],
    { initialEntries: ['/'] },
  )
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

const authBase = {
  loading: false,
  configured: true,
  signOut: async () => {},
}

describe('HomeResolver (logged-in / resolver, spec §5)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('logged out → single-league default home', async () => {
    mockUseAuth.mockReturnValue({ ...authBase, session: null, user: null })
    const router = renderResolver()
    expect(await screen.findByText('league-home')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/leagues/patriot-games')
  })

  it('exactly one membership → straight to that league', async () => {
    mockUseAuth.mockReturnValue({
      ...authBase,
      session: {} as never,
      user: { id: 'u1' } as never,
    })
    mockGetMyLeagues.mockResolvedValue([
      { leagueId: 'a', slug: 'league-a', name: 'League A', teamName: null },
    ])
    const router = renderResolver()
    expect(await screen.findByText('league-home')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe('/leagues/league-a')
  })

  it('multiple memberships → league picker', async () => {
    mockUseAuth.mockReturnValue({
      ...authBase,
      session: {} as never,
      user: { id: 'u1' } as never,
    })
    mockGetMyLeagues.mockResolvedValue([
      { leagueId: 'a', slug: 'league-a', name: 'League A', teamName: 'Team X' },
      { leagueId: 'b', slug: 'league-b', name: 'League B', teamName: null },
    ])
    renderResolver()
    expect(await screen.findByText('Your leagues')).toBeInTheDocument()
    expect(screen.getByText('League A')).toBeInTheDocument()
    expect(screen.getByText('League B')).toBeInTheDocument()
    expect(screen.getByText('League A').closest('a')).toHaveAttribute(
      'href',
      '/leagues/league-a',
    )
  })
})
