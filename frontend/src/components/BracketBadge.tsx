/**
 * Playoff-week badge distinguishing the real title race from placement games
 * (real playoff teams no longer alive for the championship) and the
 * consolation / toilet-bowl bracket. Renders nothing outside the playoffs
 * (when a matchup has no `bracket` field).
 */
export function BracketBadge({ bracket }: { bracket?: unknown }) {
  if (bracket !== 'championship' && bracket !== 'placement' && bracket !== 'consolation') {
    return null
  }
  const styles: Record<string, string> = {
    championship: 'bg-amber-500/15 text-amber-300',
    placement: 'bg-sky-500/15 text-sky-300',
    consolation: 'bg-slate-700/40 text-slate-400',
  }
  const labels: Record<string, string> = {
    championship: '🏆 Championship',
    placement: 'Placement',
    consolation: 'Consolation',
  }
  return (
    <span
      className={`ml-2 inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${styles[bracket]}`}
    >
      {labels[bracket]}
    </span>
  )
}
