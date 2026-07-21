import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { TopNav } from './TopNav'
import { BottomTabBar } from './BottomTabBar'

vi.mock('../lib/authContext', () => ({
  useAuth: () => ({
    session: null,
    user: null,
    loading: false,
    configured: false,
    signOut: async () => {},
  }),
}))

function renderChrome(entry: string, ui: React.ReactElement) {
  const router = createMemoryRouter([{ path: '*', element: ui }], {
    initialEntries: [entry],
  })
  render(<RouterProvider router={router} />)
}

describe('TopNav under a non-default league (N-3)', () => {
  it('keeps every league destination inside the active league', () => {
    renderChrome('/leagues/other-league/standings', <TopNav />)
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: /home/i })).toHaveAttribute(
      'href',
      '/leagues/other-league',
    )
    expect(within(nav).getByRole('link', { name: /matchup/i })).toHaveAttribute(
      'href',
      '/leagues/other-league/matchups',
    )
    expect(within(nav).getByRole('link', { name: /newsroom/i })).toHaveAttribute(
      'href',
      '/leagues/other-league/newsroom',
    )
    expect(within(nav).getByRole('link', { name: /standings/i })).toHaveAttribute(
      'href',
      '/leagues/other-league/standings',
    )
  })

  it('More dropdown links (Draft Room, Season tools) retain the slug', () => {
    renderChrome('/leagues/other-league', <TopNav />)
    fireEvent.click(screen.getByRole('button', { name: /more/i }))
    expect(screen.getByRole('menuitem', { name: /draft room/i })).toHaveAttribute(
      'href',
      '/leagues/other-league/draft',
    )
    expect(screen.getByRole('menuitem', { name: /season tools/i })).toHaveAttribute(
      'href',
      '/leagues/other-league/season',
    )
  })

  it('falls back to the default league on bare routes', () => {
    renderChrome('/season', <TopNav />)
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: /home/i })).toHaveAttribute(
      'href',
      '/leagues/patriot-games',
    )
  })
})

describe('BottomTabBar under a non-default league (N-3)', () => {
  it('keeps every league destination inside the active league', () => {
    renderChrome('/leagues/other-league/matchups/3', <BottomTabBar />)
    const nav = screen.getByRole('navigation', { name: 'Main' })
    expect(within(nav).getByRole('link', { name: /home/i })).toHaveAttribute(
      'href',
      '/leagues/other-league',
    )
    expect(within(nav).getByRole('link', { name: /matchup/i })).toHaveAttribute(
      'href',
      '/leagues/other-league/matchups',
    )
    expect(within(nav).getByRole('link', { name: /newsroom/i })).toHaveAttribute(
      'href',
      '/leagues/other-league/newsroom',
    )
    expect(within(nav).getByRole('link', { name: /standings/i })).toHaveAttribute(
      'href',
      '/leagues/other-league/standings',
    )
  })

  it('More sheet links retain the slug', () => {
    renderChrome('/leagues/other-league', <BottomTabBar />)
    fireEvent.click(screen.getByRole('button', { name: /more/i }))
    const sheet = screen.getByRole('dialog', { name: 'More' })
    expect(within(sheet).getByRole('link', { name: /draft room/i })).toHaveAttribute(
      'href',
      '/leagues/other-league/draft',
    )
    expect(within(sheet).getByRole('link', { name: /season tools/i })).toHaveAttribute(
      'href',
      '/leagues/other-league/season',
    )
  })
})
