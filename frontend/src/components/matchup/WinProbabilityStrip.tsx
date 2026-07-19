import { STAT_ORDER } from '../../lib/inSeasonUtils'

/**
 * P-7 matchup lean strip — NOT a calibrated win-probability model.
 *
 * Live mode: category-win share (ties count as half a win for each side).
 * The cats label is the full tally including ties.
 *
 * Projected mode: average of winning-side confidence over categories that
 * have both a decisive result and a confidence value. Ties and confidence-
 * less categories are excluded from BOTH the bar and the cats label so the
 * two stay in agreement.
 */
export function WinProbabilityStrip({
  homeTeam,
  awayTeam,
  categories,
  mode,
}: {
  homeTeam: string
  awayTeam: string
  categories: Record<string, unknown>[]
  mode: 'projected' | 'live'
}) {
  let homeWins = 0
  let awayWins = 0
  let ties = 0
  const homeConfs: number[] = []
  const awayConfs: number[] = []
  // Projected lean: only decisive + confidence-bearing categories.
  let leanHomeWins = 0
  let leanAwayWins = 0

  for (const cat of STAT_ORDER) {
    const row = categories.find((c) => String(c.stat) === cat)
    if (!row) continue

    if (mode === 'projected') {
      const hr = String(row.projected_home_result ?? '').toUpperCase()
      const winner = hr || String(row.winner ?? '')
      const hc = row.home_confidence_pct != null ? Number(row.home_confidence_pct) : null
      const ac = row.away_confidence_pct != null ? Number(row.away_confidence_pct) : null
      if (winner === 'W' || winner === 'home') {
        homeWins += 1
        if (hc != null && Number.isFinite(hc)) {
          homeConfs.push(hc)
          leanHomeWins += 1
        }
      } else if (winner === 'L' || winner === 'away') {
        awayWins += 1
        if (ac != null && Number.isFinite(ac)) {
          awayConfs.push(ac)
          leanAwayWins += 1
        }
      } else if (winner === 'T' || winner === 'tie') {
        ties += 1
      }
    } else {
      const winner = String(row.winner ?? '')
      if (winner === 'home') homeWins += 1
      else if (winner === 'away') awayWins += 1
      else if (winner === 'tie') ties += 1
    }
  }

  const decided = homeWins + awayWins + ties
  const shareHome =
    decided === 0 ? 50 : ((homeWins + ties * 0.5) / decided) * 100

  let homePct = shareHome
  let labelHome = homeWins
  let labelAway = awayWins
  let labelTies: number | null = ties > 0 ? ties : null

  if (mode === 'projected' && (homeConfs.length > 0 || awayConfs.length > 0)) {
    const parts: number[] = []
    for (const c of homeConfs) parts.push(c)
    for (const c of awayConfs) parts.push(100 - c)
    homePct = parts.reduce((a, b) => a + b, 0) / parts.length
    // Exclude ties / confidence-less from the label to match the bar.
    labelHome = leanHomeWins
    labelAway = leanAwayWins
    labelTies = null
  }

  const clamped = Math.max(5, Math.min(95, Math.round(homePct)))
  const awayPct = 100 - clamped

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-2 flex items-center justify-between gap-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
        <span className="truncate text-slate-300 normal-case tracking-normal">
          {homeTeam}
        </span>
        <span>{mode === 'projected' ? 'Win lean' : 'Category share'}</span>
        <span className="truncate text-right text-slate-300 normal-case tracking-normal">
          {awayTeam}
        </span>
      </div>
      <div className="flex h-3 overflow-hidden rounded-full bg-slate-800">
        <div className="bg-emerald-500 transition-all" style={{ width: `${clamped}%` }} />
        <div className="bg-sky-500 transition-all" style={{ width: `${awayPct}%` }} />
      </div>
      <div className="mt-2 flex justify-between text-sm font-bold tabular-nums text-white">
        <span>{clamped}%</span>
        <span className="text-xs font-medium text-slate-500">
          {labelHome}–{labelAway}
          {labelTies != null ? `–${labelTies}` : ''} cats
        </span>
        <span>{awayPct}%</span>
      </div>
    </div>
  )
}
