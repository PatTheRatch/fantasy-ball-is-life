import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { useLeagueSlug } from './useLeagueSlug'

function Probe() {
  return <div data-testid="slug">{useLeagueSlug()}</div>
}

function renderAt(entry: string, path: string) {
  const router = createMemoryRouter([{ path, element: <Probe /> }], {
    initialEntries: [entry],
  })
  render(<RouterProvider router={router} />)
}

describe('useLeagueSlug (N-3)', () => {
  it('returns the route param inside /leagues/:slug routes', () => {
    renderAt('/leagues/other-league/standings', '/leagues/:slug/standings')
    expect(screen.getByTestId('slug')).toHaveTextContent('other-league')
  })

  it('matches the pathname when rendered outside the routed element (layout chrome)', () => {
    // Layout chrome renders at the parent route, where useParams sees no slug.
    renderAt('/leagues/other-league/matchups/3', '*')
    expect(screen.getByTestId('slug')).toHaveTextContent('other-league')
  })

  it('matches a bare /leagues/:slug pathname with no sub-route', () => {
    renderAt('/leagues/other-league', '*')
    expect(screen.getByTestId('slug')).toHaveTextContent('other-league')
  })

  it('falls back to the default league on bare routes', () => {
    renderAt('/season', '/season')
    expect(screen.getByTestId('slug')).toHaveTextContent('patriot-games')
  })
})
