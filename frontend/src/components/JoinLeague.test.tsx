import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { JoinLeague } from './JoinLeague'
import { useAuth } from '../lib/authContext'

// Mock supabase and auth
vi.mock('../lib/supabase', () => ({
  supabase: {
    rpc: vi.fn(),
    from: vi.fn(() => ({
      insert: vi.fn(() => ({
        select: vi.fn(),
      })),
    })),
  },
}))

vi.mock('../lib/authContext', () => ({
  useAuth: vi.fn(),
}))

const mockUseAuth = vi.mocked(useAuth)
const mockSupabase = (await import('../lib/supabase')).supabase!

const TEAMS = ['Through The Wire', 'Optimize the MVPs', 'Fantastic 5', 'Brighton Bears']

function setup(user: { id: string } | null = { id: 'u1' }) {
  mockUseAuth.mockReturnValue({
    user: user as never,
    session: user ? ({} as never) : null,
    loading: false,
    configured: true,
    signOut: async () => {},
  })
  return { onJoined: vi.fn() }
}

describe('JoinLeague', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: claimed_team_names returns empty
    vi.mocked(mockSupabase.rpc).mockResolvedValue({ data: [], error: null } as never)
  })

  it('shows log-in prompt when not authenticated', async () => {
    const { onJoined } = setup(null)
    render(<MemoryRouter><JoinLeague leagueId="l1" teams={TEAMS} onJoined={onJoined} /></MemoryRouter>)
    expect(await screen.findByText(/Log in/i)).toBeInTheDocument()
  })

  it('shows join button and transitions to team picker', async () => {
    setup()
    render(<MemoryRouter><JoinLeague leagueId="l1" teams={TEAMS} onJoined={vi.fn()} /></MemoryRouter>)
    expect(await screen.findByText('Join this league')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Join this league'))
    expect(screen.getByText('Claim your team')).toBeInTheDocument()
  })

  it('hides already-claimed teams', async () => {
    setup()
    vi.mocked(mockSupabase.rpc).mockResolvedValue({ data: ['Through The Wire'], error: null } as never)
    render(<MemoryRouter><JoinLeague leagueId="l1" teams={TEAMS} onJoined={vi.fn()} /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Join this league'))
    // Through The Wire should NOT appear (claimed), the other 3 should
    expect(screen.queryByText('Through The Wire')).not.toBeInTheDocument()
    expect(screen.getByText('Optimize the MVPs')).toBeInTheDocument()
    expect(screen.getByText('Fantastic 5')).toBeInTheDocument()
    expect(screen.getByText('Brighton Bears')).toBeInTheDocument()
  })

  it('shows "all claimed" when no teams available', async () => {
    setup()
    vi.mocked(mockSupabase.rpc).mockResolvedValue({ data: TEAMS, error: null } as never)
    render(<MemoryRouter><JoinLeague leagueId="l1" teams={TEAMS} onJoined={vi.fn()} /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Join this league'))
    expect(screen.getByText('All teams are claimed.')).toBeInTheDocument()
  })

  it('fires onJoined after successful claim', async () => {
    const { onJoined } = setup()
    const insertMock = vi.fn().mockResolvedValue({ error: null })
    vi.mocked(mockSupabase.from).mockReturnValue({ insert: insertMock } as never)

    render(<MemoryRouter><JoinLeague leagueId="l1" teams={TEAMS} onJoined={onJoined} /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Join this league'))
    fireEvent.click(screen.getByText('Brighton Bears'))
    fireEvent.click(screen.getByText('Claim as Brighton Bears'))

    await waitFor(() => {
      expect(insertMock).toHaveBeenCalledWith({
        league_id: 'l1',
        user_id: 'u1',
        role: 'member',
        team_name: 'Brighton Bears',
      })
      expect(onJoined).toHaveBeenCalled()
    })
  })

  it('shows team-taken error on duplicate team claim', async () => {
    setup()
    const insertMock = vi.fn().mockResolvedValue({
      error: { message: 'duplicate key value violates unique constraint "league_memberships_team_unique_idx"' },
    })
    vi.mocked(mockSupabase.from).mockReturnValue({ insert: insertMock } as never)

    render(<MemoryRouter><JoinLeague leagueId="l1" teams={TEAMS} onJoined={vi.fn()} /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Join this league'))
    fireEvent.click(screen.getByText('Brighton Bears'))
    fireEvent.click(screen.getByText('Claim as Brighton Bears'))

    await waitFor(() => {
      expect(screen.getByText(/just claimed by someone else/)).toBeInTheDocument()
    })
  })

  it('shows already-member error', async () => {
    setup()
    const insertMock = vi.fn().mockResolvedValue({
      error: { message: 'duplicate key value violates unique constraint' },
    })
    vi.mocked(mockSupabase.from).mockReturnValue({ insert: insertMock } as never)

    render(<MemoryRouter><JoinLeague leagueId="l1" teams={TEAMS} onJoined={vi.fn()} /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Join this league'))
    fireEvent.click(screen.getByText('Brighton Bears'))
    fireEvent.click(screen.getByText('Claim as Brighton Bears'))

    await waitFor(() => {
      expect(screen.getByText(/already a member/)).toBeInTheDocument()
    })
  })

  it('disables claim button until a team is selected', async () => {
    setup()
    render(<MemoryRouter><JoinLeague leagueId="l1" teams={TEAMS} onJoined={vi.fn()} /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Join this league'))
    const btn = screen.getByText(/Claim as/)
    expect(btn).toBeDisabled()
    fireEvent.click(screen.getByText('Brighton Bears'))
    expect(btn).not.toBeDisabled()
  })

  it('handles claimed_team_names RPC failure gracefully', async () => {
    setup()
    vi.mocked(mockSupabase.rpc).mockRejectedValue(new Error('down'))
    render(<MemoryRouter><JoinLeague leagueId="l1" teams={TEAMS} onJoined={vi.fn()} /></MemoryRouter>)
    fireEvent.click(await screen.findByText('Join this league'))
    // Falls back to empty claimed list — all teams show
    for (const t of TEAMS) {
      expect(screen.getByText(t)).toBeInTheDocument()
    }
  })
})
