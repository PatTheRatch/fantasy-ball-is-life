import { useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { getRecapsCurrent } from '../api'
import { useLeagueSlug } from '../lib/useLeagueSlug'

// Redirect-only fallback when the league lookup fails (allowed here — this
// is bare/default-route redirect code).
const FALLBACK_SEASON = Number(import.meta.env.VITE_RECAP_SEASON ?? 2026)

/**
 * Newsroom resolver — mounted at `/leagues/:slug/newsroom` (N-3) and the
 * flat legacy `/recap` (default league via `useLeagueSlug` fallback).
 *
 * - `?week=N` → /leagues/{slug}/newsroom/{season}/{N}
 * - bare → latest published week, or week 1 if none published
 *
 * Season comes from the league's configured `espn_season`, not a
 * build-time constant.
 */
export function Recap() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const slug = useLeagueSlug()
  const resolvedRef = useRef(false)

  useEffect(() => {
    if (resolvedRef.current) return
    resolvedRef.current = true

    const requestedWeek = Number(searchParams.get('week'))

    async function redirect() {
      let season = FALLBACK_SEASON
      let latestWeek = 1
      try {
        const current = await getRecapsCurrent(slug)
        season = current.season
        if (current.archive.length > 0) {
          latestWeek = current.archive[current.archive.length - 1].week
        }
      } catch {
        // League lookup failed — fall through with defaults so the
        // newsroom route can render its own error state.
      }

      const week =
        requestedWeek && !isNaN(requestedWeek) ? requestedWeek : latestWeek
      navigate(`/leagues/${slug}/newsroom/${season}/${week}`, { replace: true })
    }

    void redirect()
  }, [searchParams, navigate, slug])

  return (
    <div className="flex min-h-[200px] items-center justify-center">
      <p className="text-slate-400">Redirecting to newsroom…</p>
    </div>
  )
}
