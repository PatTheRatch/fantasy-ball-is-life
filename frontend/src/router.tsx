import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from './layouts/AppLayout'
import { DraftPage } from './pages/DraftPage'
import { InSeason } from './pages/InSeason'
import { Recap } from './pages/Recap'
import { Season } from './pages/Season'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/draft" replace /> },
      { path: 'draft', element: <DraftPage /> },
      { path: 'in-season', element: <InSeason /> },
      { path: 'recap', element: <Recap /> },
      { path: 'season', element: <Season /> },
    ],
  },
])
