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
      { path: '/login', element: <div>login-page</div> },
      { path: '/signup', element: <div>signup-page</div> },
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

describe('HomeResolver (N-1: landing + lobby + resolver)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // ── N-1: logged-out → landing ──────────────────────────────────

  it('logged out → renders landing page', async () => {
    mockUseAuth.mockReturnValue({ ...authBase, session: null, user: null })
    renderResolver()
    expect(await screen.findByText('Full Court Press')).toBeInTheDocument()
    expect(screen.getByText('See the demo')).toBeInTheDocument()
    expect(screen.getByText('Log in')).toBeInTheDocument()
    expect(screen.getByText('Sign up')).toBeInTheDocument()
  })

  // ── N-1: zero memberships → lobby ──────────────────────────────

  it('zero memberships → renders lobby', async () => {
    mockUseAuth.mockReturnValue({
      ...authBase,
      session: {} as never,
      user: { id: 'u1' } as never,
    })
    mockGetMyLeagues.mockResolvedValue([])
    renderResolver()
    expect(await screen.findByText(/not in a league yet/)).toBeInTheDocument()
    expect(screen.getByText('Join your league')).toBeInTheDocument()
    expect(screen.getByText('Set up a new league')).toBeInTheDocument()
  })

  // ── intact: one membership → redirect ─────────────────────────

  it('one membership → straight to that league', async () => {
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

  // ── intact: multiple memberships → picker ──────────────────────

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
  })
})
