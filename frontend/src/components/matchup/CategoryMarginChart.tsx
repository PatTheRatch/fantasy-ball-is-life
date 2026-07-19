import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatStatValue, STAT_ORDER } from '../../lib/inSeasonUtils'

type MarginPoint = {
  stat: string
  /** Normalized bar height in [-1, 1]: directed margin ÷ max(|home|, |away|). */
  relativeMargin: number
  /** True home − away (before TO flip). */
  rawDiff: number
  /** Directed edge after TO sign flip (positive = home advantage). */
  directedMargin: number
  homeLabel: string
  awayLabel: string
}

/**
 * P-7 category-margin bars. Bars are normalized per category so PTS and FG%
 * share a comparable axis (relative margin = directed ÷ max(|home|,|away|)).
 * Positive = home edge, negative = away edge. TO is inverted so "winning" TO
 * (fewer turnovers) still reads as a positive edge for the lower-TO side.
 * Tooltips show the real directed margin, not the normalized bar height.
 */
export function CategoryMarginChart({
  categories,
  valueKeys = { home: 'home_value', away: 'away_value' },
}: {
  categories: Record<string, unknown>[]
  valueKeys?: { home: string; away: string }
}) {
  const data: MarginPoint[] = STAT_ORDER.map((stat) => {
    const row = categories.find((c) => String(c.stat) === stat)
    const home = Number(row?.[valueKeys.home] ?? NaN)
    const away = Number(row?.[valueKeys.away] ?? NaN)
    if (!Number.isFinite(home) || !Number.isFinite(away)) {
      return {
        stat,
        relativeMargin: 0,
        rawDiff: 0,
        directedMargin: 0,
        homeLabel: '—',
        awayLabel: '—',
      }
    }
    const rawDiff = home - away
    const directedMargin = stat === 'TO' ? -rawDiff : rawDiff
    const scale = Math.max(Math.abs(home), Math.abs(away))
    const relativeMargin = scale > 0 ? directedMargin / scale : 0
    return {
      stat,
      relativeMargin,
      rawDiff,
      directedMargin,
      homeLabel: formatStatValue(stat, home),
      awayLabel: formatStatValue(stat, away),
    }
  }).filter((d) => d.homeLabel !== '—' || d.awayLabel !== '—')

  if (data.length === 0) {
    return <p className="text-sm text-slate-500">No category margins to chart.</p>
  }

  return (
    <div className="h-56 w-full rounded-xl border border-slate-800 bg-slate-900/40 p-3">
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        Relative category edge (normalized; TO fewer-is-better)
      </p>
      <ResponsiveContainer width="100%" height="90%">
        <BarChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
          <XAxis
            dataKey="stat"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={[-1, 1]}
            tick={{ fill: '#64748b', fontSize: 10 }}
            axisLine={false}
            tickLine={false}
            width={32}
            tickFormatter={(v: number) => v.toFixed(1)}
          />
          <Tooltip
            contentStyle={{
              background: '#0f172a',
              border: '1px solid #334155',
              borderRadius: 8,
              fontSize: 12,
            }}
            labelFormatter={(label) => String(label)}
            formatter={(_value, _name, item) => {
              const payload = item?.payload as MarginPoint | undefined
              if (!payload) return ['—', 'Edge']
              const directed = payload.directedMargin
              const raw = payload.rawDiff
              const n = Number.isFinite(directed) ? directed.toFixed(2) : '—'
              const label =
                payload.stat === 'TO'
                  ? `Edge ${n} (fewer TO better; home−away ${Number.isFinite(raw) ? raw.toFixed(2) : '—'})`
                  : `Edge ${n} (home−away)`
              return [
                `${label} · H ${payload.homeLabel} / A ${payload.awayLabel}`,
                'Directed edge',
              ]
            }}
          />
          <Bar dataKey="relativeMargin" radius={[4, 4, 0, 0]}>
            {data.map((d) => (
              <Cell
                key={d.stat}
                fill={
                  d.relativeMargin > 0
                    ? '#34d399'
                    : d.relativeMargin < 0
                      ? '#38bdf8'
                      : '#475569'
                }
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
