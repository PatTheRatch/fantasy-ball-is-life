import type { JsonRecord } from '../../api'
import type { MatchupGroup } from '../../lib/inSeasonUtils'

export function MatchupCardsRow({
  groups,
  selectedKey,
  onSelect,
  recordFn,
}: {
  groups: MatchupGroup[]
  selectedKey: string | null
  onSelect: (key: string) => void
  recordFn: (stats: JsonRecord[]) => { home: number; away: number }
}) {
  if (groups.length === 0) return null
  return (
    <div className="flex gap-2 overflow-x-auto pb-1 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {groups.map((g) => {
        const rec = recordFn(g.stats)
        const homeW = rec.home > rec.away
        const awayW = rec.away > rec.home
        const tie = rec.home === rec.away
        const active = selectedKey === g.key
        return (
          <button
            key={g.key}
            type="button"
            onClick={() => onSelect(g.key)}
            className={`min-h-[44px] min-w-[160px] shrink-0 rounded-xl border px-3 py-2 text-left transition ${
              active
                ? 'border-[#e03131] bg-slate-800/90'
                : 'border-slate-700/80 bg-slate-900/60'
            }`}
          >
            <div className="text-xs font-medium text-slate-300">
              {g.home} vs {g.away}
            </div>
            <div className="mt-1 text-sm font-semibold tabular-nums text-white">
              <span className={homeW && !tie ? 'text-emerald-400' : ''}>
                {rec.home}
              </span>
              <span className="text-slate-500">-</span>
              <span className={awayW && !tie ? 'text-emerald-400' : ''}>
                {rec.away}
              </span>
            </div>
            {!tie && (
              <div className="mt-0.5 text-xs text-emerald-400/90">
                {homeW ? g.home : g.away}
              </div>
            )}
          </button>
        )
      })}
    </div>
  )
}
