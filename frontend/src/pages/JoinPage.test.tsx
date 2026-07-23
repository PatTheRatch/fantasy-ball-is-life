import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { JoinPage } from './JoinPage'

const h = vi.hoisted(() => ({
  auth: { session: null as unknown, user: null as unknown, loading: false },
  rpc: vi.fn(),
}))

vi.mock('../lib/authContext', () => ({ useAuth: () => h.auth }))
vi.mock('../lib/supabase', () => ({ supabase: { rpc: h.rpc } }))

function renderAt(entry: string) {
  const router = createMemoryRouter(
    [
      { path: '/join', element: <JoinPage /> },
      { path: '/signup', element: <div>signup page</div> },
      { path: '/login', element: <div>login page</div> },
      { path: '/', element: <div>home</div> },
    ],
    { initialEntries: [entry] },
  )
  render(<RouterProvider router={router} />)
  return router
}

beforeEach(() => {
  h.auth = { session: null, user: null, loading: false }
  h.rpc.mockReset()
})

describe('JoinPage invite routing (N-2b)', () => {
  it('shows a helpful message when the invite token is missing', () => {
    renderAt('/join')
    expect(screen.getByText(/no invite link found/i)).toBeInTheDocument()
  })

  it('routes an unauthenticated invitee to signup, preserving invite + next', async () => {
    const router = renderAt('/join?invite=TOK123')

    await waitFor(() => expect(router.state.location.pathname).toBe('/signup'))
    const p = new URLSearchParams(router.state.location.search)
    // The token reveals the (otherwise gated) signup form...
    expect(p.get('invite')).toBe('TOK123')
    // ...and `next` brings them back here to redeem once authenticated.
    expect(p.get('next')).toBe('/join?invite=TOK123')
  })

  it('redeems the invite for a signed-in user and lands home', async () => {
    h.auth = { session: { access_token: 'x' }, user: { id: 'u1' }, loading: false }
    h.rpc.mockResolvedValue({ error: null })

    const router = renderAt('/join?invite=TOK123')

    await waitFor(() =>
      expect(h.rpc).toHaveBeenCalledWith('redeem_league_invite', { p_token: 'TOK123' }),
    )
    await waitFor(() => expect(router.state.location.pathname).toBe('/'))
  })
})
