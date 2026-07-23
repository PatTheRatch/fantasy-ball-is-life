import { createBrowserRouter } from 'react-router-dom'
import { AppLayout } from './layouts/AppLayout'
import {
  DraftPageRoute,
  MatchupWeekPageRoute,
  SeasonRoute,
} from './lazyPages'
import { RequireAuth } from './lib/RequireAuth'
import { CreateLeagueWizard } from './pages/CreateLeagueWizard'
import { DraftRedirect } from './pages/DraftRedirect'
import { HomeResolver } from './pages/HomeResolver'
import { InSeasonRedirect } from './pages/InSeasonRedirect'
import { LeagueHome } from './pages/LeagueHome'
import { Login } from './pages/Login'
import { NewsroomLayout } from './pages/NewsroomLayout'
import { NewsroomRedirect } from './pages/NewsroomRedirect'
import { Recap } from './pages/Recap'
import { ResetPassword } from './pages/ResetPassword'
import { Settings } from './pages/Settings'
import { StandingsPage } from './pages/StandingsPage'
import { Signup } from './pages/Signup'
import { UpdatePassword } from './pages/UpdatePassword'

import { JoinPage } from './pages/JoinPage'

export const router = createBrowserRouter([
  // Standalone auth surfaces (P-5) — rendered without the app chrome.
  { path: '/login', element: <Login /> },
  { path: '/signup', element: <Signup /> },
  { path: '/reset-password', element: <ResetPassword /> },
  { path: '/update-password', element: <UpdatePassword /> },
  // N-2b: invite redeem — standalone, no chrome needed
  { path: '/join', element: <JoinPage /> },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      // P-6b: `/` resolves by membership (1 league → its Home; many → picker;
      // logged out → the single-league default).
      { index: true, element: <HomeResolver /> },
      // League Home — the new default league surface (P-6b).
      { path: 'leagues/:slug', element: <LeagueHome /> },
      { path: 'leagues/:slug/draft', element: <DraftPageRoute /> },
      // P-7: matchup detail route (snapshot + live/projected tools).
      { path: 'leagues/:slug/matchups/:week', element: <MatchupWeekPageRoute /> },
      // N-3: per-league resolvers — pick the league's season + latest week.
      { path: 'leagues/:slug/matchups', element: <InSeasonRedirect /> },
      { path: 'leagues/:slug/newsroom', element: <Recap /> },
      // Flat legacy paths → default-league equivalents (§5).
      { path: 'draft', element: <DraftRedirect /> },
      { path: 'in-season', element: <InSeasonRedirect /> },
      { path: 'recap', element: <Recap /> },
      // Newsroom (P-6a: renamed from /recaps/; old path redirects below).
      { path: 'leagues/:slug/newsroom/:season/:week', element: <NewsroomLayout /> },
      { path: 'leagues/:slug/recaps/:season/:week', element: <NewsroomRedirect /> },
      // Standings promoted to its own route (P-6a).
      { path: 'leagues/:slug/standings', element: <StandingsPage /> },
      { path: 'season', element: <SeasonRoute /> },
      // N-3: league-scoped season tools (bare /season keeps the default league).
      { path: 'leagues/:slug/season', element: <SeasonRoute /> },
      // N-4d: create-league wizard (login-required).
      {
        path: 'leagues/new',
        element: (
          <RequireAuth>
            <CreateLeagueWizard />
          </RequireAuth>
        ),
      },
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
