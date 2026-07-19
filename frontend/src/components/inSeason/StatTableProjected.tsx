import type { JsonRecord } from '../../api'
import { formatStatValue, pillClass } from '../../lib/inSeasonUtils'

export function StatTableProjected({
  stats,
}: {
  stats: JsonRecord[]
}) {
  return (
    <div className="overflow-x-hidden rounded-lg border border-slate-700/60">
      <table className="w-full table-fixed text-left text-xs">
        <thead>
          <tr className="border-b border-slate-700/60 text-slate-400">
            <th className="w-[28%] px-2 py-2 font-medium">Stat</th>
            <th className="w-[36%] px-2 py-2 font-medium">Home</th>
            <th className="w-[36%] px-2 py-2 font-medium">Away</th>
          </tr>
        </thead>
        <tbody>
          {stats.map((r) => {
            const stat = String(r.stat)
            const hr = String(r.projected_home_result ?? '').toUpperCase()
            const ar = String(r.projected_away_result ?? '').toUpperCase()
            const hConf = r.home_confidence_pct
            const aConf = r.away_confidence_pct
            return (
              <tr
                key={stat}
                className="border-b border-slate-800/80 last:border-0"
              >
                <td className="px-2 py-2 font-medium text-slate-200">{stat}</td>
                <td className="px-2 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="tabular-nums text-slate-100">
                      {formatStatValue(stat, r.projected_home_score)}
                    </span>
                    <span
                      className={`inline-flex min-h-[22px] min-w-[22px] items-center justify-center rounded-full px-1.5 text-[10px] font-bold text-white ${pillClass(hr)}`}
                    >
                      {hr}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[10px] text-slate-500">
                    {hConf != null && !Number.isNaN(Number(hConf))
                      ? `${Number(hConf).toFixed(0)}% conf`
                      : '—'}
                  </div>
                </td>
                <td className="px-2 py-2">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="tabular-nums text-slate-100">
                      {formatStatValue(stat, r.projected_away_score)}
                    </span>
                    <span
                      className={`inline-flex min-h-[22px] min-w-[22px] items-center justify-center rounded-full px-1.5 text-[10px] font-bold text-white ${pillClass(ar)}`}
                    >
                      {ar}
                    </span>
                  </div>
                  <div className="mt-0.5 text-[10px] text-slate-500">
                    {aConf != null && !Number.isNaN(Number(aConf))
                      ? `${Number(aConf).toFixed(0)}% conf`
                      : '—'}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
