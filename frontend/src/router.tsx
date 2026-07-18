import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from './layouts/AppLayout'
import { RequireAuth } from './lib/RequireAuth'
import { DraftPage } from './pages/DraftPage'
import { InSeason } from './pages/InSeason'
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
      { index: true, element: <Navigate to="/draft" replace /> },
      { path: 'draft', element: <DraftPage /> },
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
