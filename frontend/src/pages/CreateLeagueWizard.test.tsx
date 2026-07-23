import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { CreateLeagueWizard } from './CreateLeagueWizard'

// ── Mock api module ──────────────────────────────────────────────────────

vi.mock('../api', () => ({
  getLeaguePreview: vi.fn(),
  createLeague: vi.fn(),
  formatApiError: vi.fn((err: unknown) => String(err)),
}))

vi.mock('../lib/authContext', () => ({
  useAccessToken: () => 'mock-token',
}))

// ── Helpers ──────────────────────────────────────────────────────────────

function renderPage() {
  const router = createMemoryRouter(
    [{ path: '/leagues/new', element: <CreateLeagueWizard /> }],
    { initialEntries: ['/leagues/new'] },
  )
  return render(<RouterProvider router={router} />)
}

function fillStep1() {
  const user = userEvent.setup()
  return {
    user,
    async submit() {
      const idInput = screen.getByPlaceholderText('e.g. 1234567')
      const seasonInput = screen.getAllByRole('spinbutton')[1]
      const nameInput = screen.getByPlaceholderText('My Fantasy League')

      await user.clear(idInput)
      await user.type(idInput, '12345')
      await user.clear(seasonInput)
      await user.type(seasonInput, '2026')
      await user.clear(nameInput)
      await user.type(nameInput, 'Test League')

      await user.click(screen.getByRole('button', { name: /check league/i }))
    },
  }
}

// ── Tests ────────────────────────────────────────────────────────────────

describe('CreateLeagueWizard', () => {
  it('step 1 renders identify form', () => {
    renderPage()
    expect(screen.getByText('Create a league')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('e.g. 1234567')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /check league/i })).toBeInTheDocument()
  })

  it('preview success renders league info and advances to step 2', async () => {
    const { getLeaguePreview } = await import('../api')
    ;(getLeaguePreview as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      name: 'My ESPN League',
      teams: 12,
      scoring_type: 'H2H Points',
      season: 2026,
      team_names: ['Team A', 'Team B', 'Team C'],
    })

    renderPage()
    const { submit } = fillStep1()
    await submit()

    await waitFor(() => {
      expect(screen.getByText('My ESPN League')).toBeInTheDocument()
      expect(screen.getByText(/12 teams/)).toBeInTheDocument()
      expect(screen.getByText(/H2H Points/)).toBeInTheDocument()
    })

    // Step 2 elements visible
    expect(screen.getByRole('button', { name: /create league/i })).toBeInTheDocument()
    expect(screen.getByText(/which team is yours/i)).toBeInTheDocument()
  })

  it('not_found shows friendly message', async () => {
    const { getLeaguePreview } = await import('../api')
    ;(getLeaguePreview as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      response: { data: { detail: { code: 'not_found', message: 'Not found' } } },
    })

    renderPage()
    const { submit } = fillStep1()
    await submit()

    await waitFor(() => {
      expect(screen.getByText('No ESPN league found with that ID and season.')).toBeInTheDocument()
    })
  })

  it('private_league shows message and reveals cookie fields', async () => {
    const { getLeaguePreview } = await import('../api')
    ;(getLeaguePreview as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      response: { data: { detail: { code: 'private_league', message: 'Private' } } },
    })

    renderPage()
    const { submit } = fillStep1()
    await submit()

    await waitFor(() => {
      expect(
        screen.getByText('This league is private — add your ESPN SWID and ESPN_S2 cookies below.'),
      ).toBeInTheDocument()
      // Cookie fields revealed
      expect(screen.getByPlaceholderText('{…}')).toBeInTheDocument()
      expect(screen.getByPlaceholderText('AEA…')).toBeInTheDocument()
    })
  })

  it('bad_cookies shows friendly message', async () => {
    const { getLeaguePreview } = await import('../api')
    ;(getLeaguePreview as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      response: { data: { detail: { code: 'bad_cookies', message: 'Bad' } } },
    })

    renderPage()
    const { submit } = fillStep1()
    await submit()

    await waitFor(() => {
      expect(screen.getByText('ESPN rejected those cookies. Double-check them and try again.')).toBeInTheDocument()
    })
  })

  it('espn_unavailable shows friendly message', async () => {
    const { getLeaguePreview } = await import('../api')
    ;(getLeaguePreview as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      response: { data: { detail: { code: 'espn_unavailable', message: 'Down' } } },
    })

    renderPage()
    const { submit } = fillStep1()
    await submit()

    await waitFor(() => {
      expect(screen.getByText("Couldn't reach ESPN right now. Try again in a moment.")).toBeInTheDocument()
    })
  })

  it('create success navigates to /leagues/{slug}', async () => {
    const { getLeaguePreview, createLeague } = await import('../api')
    ;(getLeaguePreview as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      name: 'My League',
      teams: 10,
      scoring_type: 'H2H',
      season: 2026,
      team_names: ['T1'],
    })
    ;(createLeague as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 'abc-123',
      slug: 'my-league',
      name: 'My League',
      espn_league_id: 12345,
      espn_season: 2026,
      timezone: 'America/New_York',
      team_name: 'T1',
    })

    const router = createMemoryRouter(
      [
        { path: '/leagues/new', element: <CreateLeagueWizard /> },
        { path: '/leagues/:slug', element: <div>League Home: test</div> },
      ],
      { initialEntries: ['/leagues/new'] },
    )
    render(<RouterProvider router={router} />)

    const { submit } = fillStep1()
    await submit()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create league/i })).toBeInTheDocument()
    })

    // Select team and create
    const select = screen.getByRole('combobox')
    const user = userEvent.setup()
    await user.selectOptions(select, 'T1')
    await user.click(screen.getByRole('button', { name: /create league/i }))

    await waitFor(() => {
      expect(screen.getByText('League Home: test')).toBeInTheDocument()
    })
  })

  it('league_cap_reached shows friendly message', async () => {
    const { getLeaguePreview, createLeague } = await import('../api')
    ;(getLeaguePreview as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      name: 'My League',
      teams: 10,
      scoring_type: 'H2H',
      season: 2026,
      team_names: [],
    })
    ;(createLeague as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      response: { data: { detail: { code: 'league_cap_reached', message: 'Cap' } } },
    })

    renderPage()
    const { submit } = fillStep1()
    await submit()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create league/i })).toBeInTheDocument()
    })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /create league/i }))

    await waitFor(() => {
      expect(screen.getByText("You've reached the limit of 2 leagues.")).toBeInTheDocument()
    })
  })

  it('team_taken shows friendly message', async () => {
    const { getLeaguePreview, createLeague } = await import('../api')
    ;(getLeaguePreview as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      name: 'My League',
      teams: 10,
      scoring_type: 'H2H',
      season: 2026,
      team_names: ['T1'],
    })
    ;(createLeague as ReturnType<typeof vi.fn>).mockRejectedValueOnce({
      response: { data: { detail: { code: 'team_taken', message: 'Taken' } } },
    })

    renderPage()
    const { submit } = fillStep1()
    await submit()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /create league/i })).toBeInTheDocument()
    })

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /create league/i }))

    await waitFor(() => {
      expect(screen.getByText('That team is already claimed.')).toBeInTheDocument()
    })
  })
})
