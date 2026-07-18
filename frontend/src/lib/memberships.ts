import { supabase } from './supabase'

/**
 * P-6b: read/write the current user's league memberships via the Supabase
 * client (RLS: members read their own rows; `team_name` is the only
 * member-writable column — see migrations/20260718070000).
 */
export interface MyLeague {
  leagueId: string
  slug: string
  name: string
  teamName: string | null
}

/**
 * The user's leagues (slug + claimed team). Tolerant by design: returns []
 * when Supabase is unconfigured or the query fails, so callers can fall back
 * to the single-league default instead of breaking the page.
 */
export async function getMyLeagues(userId: string): Promise<MyLeague[]> {
  if (!supabase) return []
  const { data, error } = await supabase
    .from('league_memberships')
    .select('league_id, team_name, leagues ( slug, name )')
    .eq('user_id', userId)
  if (error || !data) return []
  return data.flatMap((row) => {
    // PostgREST returns the FK join as an object (or array under ambiguity).
    const league = Array.isArray(row.leagues) ? row.leagues[0] : row.leagues
    if (!league?.slug) return []
    return [
      {
        leagueId: String(row.league_id),
        slug: String(league.slug),
        name: String(league.name ?? league.slug),
        teamName: row.team_name != null ? String(row.team_name) : null,
      },
    ]
  })
}

/** Claim (or clear, with null) the user's team in a league. Throws on failure. */
export async function claimTeam(
  leagueId: string,
  userId: string,
  teamName: string | null,
): Promise<void> {
  if (!supabase) throw new Error('Supabase is not configured.')
  const { error } = await supabase
    .from('league_memberships')
    .update({ team_name: teamName })
    .eq('league_id', leagueId)
    .eq('user_id', userId)
  if (error) throw new Error(error.message)
}
