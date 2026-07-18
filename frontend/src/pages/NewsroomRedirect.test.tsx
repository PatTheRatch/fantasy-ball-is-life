import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { NewsroomRedirect } from './NewsroomRedirect'

describe('NewsroomRedirect', () => {
  it('redirects /leagues/:slug/recaps/:season/:week → /newsroom/ with the same params', async () => {
    const router = createMemoryRouter(
      [
        {
          path: '/leagues/:slug/recaps/:season/:week',
          element: <NewsroomRedirect />,
        },
        {
          path: '/leagues/:slug/newsroom/:season/:week',
          element: <div>newsroom page</div>,
        },
      ],
      { initialEntries: ['/leagues/patriot-games/recaps/2026/7'] },
    )
    render(<RouterProvider router={router} />)

    expect(await screen.findByText('newsroom page')).toBeInTheDocument()
    expect(router.state.location.pathname).toBe(
      '/leagues/patriot-games/newsroom/2026/7',
    )
  })
})
