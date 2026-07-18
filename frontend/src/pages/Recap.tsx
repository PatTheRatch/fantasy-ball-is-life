import { useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { getPublishedArchive } from '../api'
import { recapLeagueSlug } from '../lib/supabase'

const RECAP_SEASON = Number(import.meta.env.VITE_RECAP_SEASON ?? 2026)

/**
 * Legacy /recap redirect.
 *
 * - /recap?week=N → /leagues/{slug}/newsroom/{season}/{N}
 * - /recap (bare) → latest published week, or week 1 if none published
 */
export function Recap() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const resolvedRef = useRef(false)

  useEffect(() => {
    if (resolvedRef.current) return
    resolvedRef.current = true

    const requestedWeek = Number(searchParams.get('week'))

    async function redirect() {
      const slug = recapLeagueSlug
      const season = RECAP_SEASON

      if (requestedWeek && !isNaN(requestedWeek)) {
        navigate(`/leagues/${slug}/newsroom/${season}/${requestedWeek}`, {
          replace: true,
        })
        return
      }

      // Bare /recap — find latest published week
      try {
        const archive = await getPublishedArchive(slug, season)
        if (archive.length > 0) {
          const latest = archive[archive.length - 1].week
          navigate(`/leagues/${slug}/newsroom/${season}/${latest}`, {
            replace: true,
          })
          return
        }
      } catch {
        // Fall through to week 1
      }

      navigate(`/leagues/${slug}/newsroom/${season}/1`, { replace: true })
    }

    void redirect()
  }, [searchParams, navigate])

  return (
    <div className="flex min-h-[200px] items-center justify-center">
      <p className="text-slate-400">Redirecting to newsroom…</p>
    </div>
  )
}
