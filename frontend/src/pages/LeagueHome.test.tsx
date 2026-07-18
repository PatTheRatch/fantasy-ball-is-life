import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { LeagueHome } from './LeagueHome'

vi.mock('../api', () => ({
  getPublishedArchive: vi
    .fn()
    .mockResolvedValue([{ week: 1 }, { week: 6, headline: 'Big Week Six' }]),
  getSnapshot: vi.fn().mockResolvedValue({
    league: {},
    snapshot: {
      matchups: [
        {
          matchup_id: 'm1',
          home_team: 'Alpha',
          away_team: 'Beta',
          home_category_wins: 5,
          away_category_wins: 4,
          home_games_played: 30,
          away_games_played: 28,
        },
      ],
      power_rankings: [
        { team_id: '1', team: 'Alpha', rank: 1, rank_change: 0 },
        { team_id: '2', team: 'Beta', rank: 2, rank_change: 3 },
        { team_id: '3', team: 'Gamma', rank: 3, rank_change: -1 },
        { team_id: '4', team: 'Delta', rank: 4, rank_change: -2 },
      ],
      transactions: [
        { date: '2026-07-15', team_name: 'Alpha' },
        { date: '2026-07-16', team_name: 'Beta' },
      ],
    },
  }),
}))

// Logged out: the membership query stays disabled; Home still renders fully.
vi.mock('../lib/authContext', () => ({
  useAuth: () => ({
    session: null,
    user: null,
    loading: false,
    configured: false,
    signOut: async () => {},
  }),
}))

describe('LeagueHome (spec §8)', () => {
  it('auto-loads all four sections from the latest snapshot — no Load buttons (D-P6)', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider
          router={createMemoryRouter(
            [{ path: '/leagues/:slug', element: <LeagueHome /> }],
            { initialEntries: ['/leagues/patriot-games'] },
          )}
        />
      </QueryClientProvider>,
    )

    // Week context from the latest published week
    expect(await screen.findByText('Week 6')).toBeInTheDocument()
    // Matchup card (logged out → generic "This week" heading, not "Your matchup")
    const matchupCard = screen.getByText('This week').closest('section')!
    expect(within(matchupCard).getByText('Alpha')).toBeInTheDocument()
    expect(within(matchupCard).getByText('Beta')).toBeInTheDocument()
    expect(within(matchupCard).getByText('5')).toBeInTheDocument()
    // Movers: sorted by |rank_change|, zero-change teams excluded
    const movers = screen.getByText('Ranking movers').closest('section')!
    expect(within(movers).getByText('Gamma')).toBeInTheDocument()
    expect(within(movers).queryByText('Alpha')).toBeNull()
    // Latest recap card
    expect(screen.getByText('Big Week Six')).toBeInTheDocument()
    // Transaction ticker
    expect(screen.getByText('Recent moves')).toBeInTheDocument()
    // D-P6: zero manual load buttons on Home
    expect(screen.queryByRole('button', { name: /load/i })).toBeNull()
  })
})
