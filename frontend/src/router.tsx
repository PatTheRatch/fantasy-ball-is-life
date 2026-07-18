import { createBrowserRouter } from 'react-router-dom'
import { AppLayout } from './layouts/AppLayout'
import { RequireAuth } from './lib/RequireAuth'
import { DraftPage } from './pages/DraftPage'
import { DraftRedirect } from './pages/DraftRedirect'
import { HomeResolver } from './pages/HomeResolver'
import { InSeason } from './pages/InSeason'
import { LeagueHome } from './pages/LeagueHome'
import { Login } from './pages/Login'
import { NewsroomLayout } from './pages/NewsroomLayout'
import { NewsroomRedirect } from './pages/NewsroomRedirect'
import { Recap } from './pages/Recap'
import { ResetPassword } from './pages/ResetPassword'
import { Season } from './pages/Season'
import { Settings } from './pages/Settings'
import { StandingsPage } from './pages/StandingsPage'
import { Signup } from './pages/Signup'
import { UpdatePassword } from './pages/UpdatePassword'

export const router = createBrowserRouter([
  // Standalone auth surfaces (P-5) — rendered without the app chrome.
  { path: '/login', element: <Login /> },
  { path: '/signup', element: <Signup /> },
  { path: '/reset-password', element: <ResetPassword /> },
  { path: '/update-password', element: <UpdatePassword /> },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      // P-6b: `/` resolves by membership (1 league → its Home; many → picker;
      // logged out → the single-league default).
      { index: true, element: <HomeResolver /> },
      // League Home — the new default league surface (P-6b).
      { path: 'leagues/:slug', element: <LeagueHome /> },
      { path: 'leagues/:slug/draft', element: <DraftPage /> },
      // Flat legacy paths → league-scoped equivalents (§5). `/in-season` and
      // `/season` keep flat until P-7 gives them scoped destinations.
      { path: 'draft', element: <DraftRedirect /> },
      { path: 'in-season', element: <InSeason /> },
      { path: 'recap', element: <Recap /> },
      // Newsroom (P-6a: renamed from /recaps/; old path redirects below).
      { path: 'leagues/:slug/newsroom/:season/:week', element: <NewsroomLayout /> },
      { path: 'leagues/:slug/recaps/:season/:week', element: <NewsroomRedirect /> },
      // Standings promoted to its own route (P-6a).
      { path: 'leagues/:slug/standings', element: <StandingsPage /> },
      { path: 'season', element: <Season /> },
      {
        path: 'settings',
        element: (
          <RequireAuth>
            <Settings />
          </RequireAuth>
        ),
      },
    ],
  },
])
