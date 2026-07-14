/**
 * Playoff-week badge distinguishing the real championship bracket from the
 * consolation / placement bracket. Renders nothing outside the playoffs (when
 * a matchup has no `bracket` field).
 */
export function BracketBadge({ bracket }: { bracket?: unknown }) {
  if (bracket !== 'championship' && bracket !== 'consolation') return null
  const isChamp = bracket === 'championship'
  return (
    <span
      className={`ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
        isChamp
          ? 'bg-amber-500/15 text-amber-300'
          : 'bg-slate-700/40 text-slate-400'
      }`}
    >
      {isChamp ? '🏆 Championship' : 'Consolation'}
    </span>
  )
}
