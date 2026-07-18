import { Navigate, useParams } from 'react-router-dom'

/**
 * P-6a: the newsroom route was renamed `/recaps/` → `/newsroom/`. This keeps
 * the old path working (bookmarks, shared links) by redirecting to the new one
 * with the same params.
 */
export function NewsroomRedirect() {
  const { slug, season, week } = useParams<{
    slug: string
    season: string
    week: string
  }>()
  return (
    <Navigate to={`/leagues/${slug}/newsroom/${season}/${week}`} replace />
  )
}
