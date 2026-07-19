import type { DraftPoolParams } from '../api'
import { ACCENT, CATS, COUNTING_CATS } from './constants'

/**
 * P-7 Advanced sheet — solver knobs that used to sit inline in SetupPanel.
 * Time limit is server-owned (`SOLVER_TIME_LIMIT_SECONDS`); shown read-only
 * because `DraftPoolParams` has no time_limit field.
 */
export function ControlsSheet({
  open,
  onClose,
  params,
  onChange,
  leagueTeamCount,
}: {
  open: boolean
  onClose: () => void
  params: DraftPoolParams
  onChange: (p: DraftPoolParams) => void
  leagueTeamCount: number | null
}) {
  if (!open) return null

  const selectedCats = params.target_categories ?? [...CATS]
  const percentile = params.base_percentile ?? 0.7
  const availableObjectives = COUNTING_CATS.filter((c) => selectedCats.includes(c))

  function toggleCategory(cat: string) {
    const next = selectedCats.includes(cat)
      ? selectedCats.filter((c) => c !== cat)
      : [...selectedCats, cat]
    if (next.length === 0) return
    const patch: DraftPoolParams = { ...params, target_categories: next }
    if (params.stat_to_maximize && !next.includes(params.stat_to_maximize)) {
      patch.stat_to_maximize = null
    }
    onChange(patch)
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-end justify-center md:items-center md:p-4">
      <button
        type="button"
        tabIndex={-1}
        className="absolute inset-0 bg-black/55 backdrop-blur-[2px]"
        aria-label="Close advanced controls"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="draft-controls-title"
        className="relative z-10 max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-t-2xl border border-pg-border bg-pg-card p-5 shadow-xl md:rounded-2xl"
      >
        <div className="mb-4 flex items-center justify-between gap-3">
          <h2 id="draft-controls-title" className="text-lg font-semibold text-white">
            Advanced
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-pg-border px-3 py-1.5 text-xs font-semibold text-slate-300"
          >
            Done
          </button>
        </div>

        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          What to optimize for
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {CATS.map((cat) => {
            const on = selectedCats.includes(cat)
            return (
              <button
                key={cat}
                type="button"
                onClick={() => toggleCategory(cat)}
                title={
                  on
                    ? `Competing in ${cat} — click to punt it`
                    : `Punting ${cat} — click to compete in it`
                }
                className="rounded-md border px-2.5 py-1 font-mono text-xs font-semibold transition-colors"
                style={
                  on
                    ? { borderColor: ACCENT, backgroundColor: `${ACCENT}1f`, color: '#fff' }
                    : { borderColor: 'var(--color-pg-border)', color: '#64748b' }
                }
              >
                {cat}
              </button>
            )
          })}
        </div>
        <p className="mt-1 text-xs text-slate-500">
          Unselected categories are always punted across every generated plan.
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-5">
          <label className="flex min-w-[220px] flex-1 flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Confidence — how likely to win a category:{' '}
              <span className="font-mono text-slate-300">{Math.round(percentile * 100)}%</span>
            </span>
            <input
              type="range"
              min={50}
              max={95}
              step={1}
              value={Math.round(percentile * 100)}
              onChange={(e) =>
                onChange({ ...params, base_percentile: Number(e.target.value) / 100 })
              }
              style={{ accentColor: ACCENT }}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Push hardest on
            </span>
            <select
              value={params.stat_to_maximize ?? ''}
              onChange={(e) =>
                onChange({ ...params, stat_to_maximize: e.target.value || null })
              }
              className="rounded-md border border-pg-border bg-black/30 px-2 py-1.5 text-sm text-white focus:outline-none"
            >
              <option value="">Recipe default (varies by plan)</option>
              {availableObjectives.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="mt-4 border-t border-pg-border pt-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Player values
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <div className="flex overflow-hidden rounded-md border border-pg-border">
              {(
                [
                  { value: 'bbm' as const, label: 'BBM (uploaded)' },
                  { value: 'forge' as const, label: 'Forge Value (proprietary)' },
                ] as const
              ).map((opt) => {
                const on = (params.value_source ?? 'bbm') === opt.value
                return (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => onChange({ ...params, value_source: opt.value })}
                    className="px-3 py-1.5 text-xs font-semibold transition-colors"
                    style={
                      on
                        ? { backgroundColor: `${ACCENT}1f`, color: '#fff' }
                        : { color: '#64748b' }
                    }
                  >
                    {opt.label}
                  </button>
                )
              })}
            </div>
            <p className="text-xs text-slate-500">
              {(params.value_source ?? 'bbm') === 'bbm'
                ? "The uploaded projections file's own $ column."
                : leagueTeamCount
                  ? `PatriotGames' own projection-derived valuation — sized to your ${leagueTeamCount}-team league and this draft's roster size/budget.`
                  : "PatriotGames' own projection-derived valuation — sized to your league's real team count and this draft's roster size/budget."}
            </p>
          </div>
        </div>

        <div className="mt-4 border-t border-pg-border pt-4">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Solver time limit
          </p>
          <p className="mt-1 text-sm text-slate-300">
            8s per solve <span className="text-slate-500">(server-enforced)</span>
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Owned by backend env <span className="font-mono">SOLVER_TIME_LIMIT_SECONDS</span>.
            Not tunable per draft from the client.
          </p>
        </div>
      </div>
    </div>
  )
}
