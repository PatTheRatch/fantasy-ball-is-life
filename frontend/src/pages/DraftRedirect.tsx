import { Navigate } from 'react-router-dom'
import { recapLeagueSlug } from '../lib/supabase'

/**
 * P-6b: flat `/draft` → league-scoped `/leagues/:slug/draft` (§5).
 * Single-league interim: the slug resolves from config, as in Recap.tsx.
 */
export function DraftRedirect() {
  return <Navigate to={`/leagues/${recapLeagueSlug}/draft`} replace />
}
