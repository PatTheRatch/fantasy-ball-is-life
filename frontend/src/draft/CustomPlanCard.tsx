import { useState } from 'react'
import type { CustomPlanSpec } from '../api'
import { Card } from '../components/Card'
import { ACCENT, BLANK_CUSTOM_SPEC, BUILTIN_TEMPLATES, CATS, COUNTING_CATS } from './constants'
import { NumberField } from './shared/NumberField'

export function CustomPlanCard({
  presets,
  onDeletePreset,
  onSolve,
  pending,
  error,
}: {
  presets: CustomPlanSpec[]
  onDeletePreset: (label: string) => void
  onSolve: (spec: CustomPlanSpec) => void
  pending: boolean
  error: string | null
}) {
  const [spec, setSpec] = useState<CustomPlanSpec>(BLANK_CUSTOM_SPEC)
  const library = [...BUILTIN_TEMPLATES, ...presets]
  const availableObjectives = COUNTING_CATS.filter((c) => spec.constrained_categories.includes(c))

  function loadFromLibrary(label: string) {
    const found = library.find((p) => p.label === label)
    if (found) setSpec({ ...found })
  }

  function toggleCategory(cat: string) {
    const next = spec.constrained_categories.includes(cat)
      ? spec.constrained_categories.filter((c) => c !== cat)
      : [...spec.constrained_categories, cat]
    if (next.length === 0) return // must keep at least one category selected
    const patch: CustomPlanSpec = { ...spec, constrained_categories: next }
    if (!next.includes(spec.stat_to_maximize)) {
      patch.stat_to_maximize = COUNTING_CATS.find((c) => next.includes(c)) ?? spec.stat_to_maximize
    }
    setSpec(patch)
  }

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-white">Build a plan</p>
        <label className="flex items-center gap-2 text-xs text-slate-400">
          Start from
          <select
            value=""
            onChange={(e) => e.target.value && loadFromLibrary(e.target.value)}
            className="rounded-md border border-pg-border bg-black/30 px-2 py-1 text-xs text-white focus:outline-none"
          >
            <option value="">blank</option>
            <optgroup label="Built-in strategies">
              {BUILTIN_TEMPLATES.map((t) => (
                <option key={t.label} value={t.label}>
                  {t.label}
                </option>
              ))}
            </optgroup>
            {presets.length > 0 && (
              <optgroup label="My saved plans">
                {presets.map((p) => (
                  <option key={p.label} value={p.label}>
                    {p.label}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </label>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Name</span>
          <input
            type="text"
            value={spec.label}
            onChange={(e) => setSpec({ ...spec, label: e.target.value })}
            placeholder="e.g. My punt-AST build"
            className="w-56 rounded-md border border-pg-border bg-black/30 px-2 py-1.5 text-sm text-white focus:outline-none"
          />
        </label>
        <NumberField
          label="$1 slots"
          value={spec.minimum_value_players}
          onChange={(v) => setSpec({ ...spec, minimum_value_players: v })}
          min={0}
        />
        <label className="flex items-center gap-2 pb-1.5 text-xs text-slate-400">
          <input
            type="checkbox"
            checked={spec.ban_top_price}
            onChange={(e) => setSpec({ ...spec, ban_top_price: e.target.checked })}
          />
          Avoid relying on one priciest player
        </label>
      </div>

      <div className="mt-3">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Categories to compete in</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {CATS.map((cat) => {
            const on = spec.constrained_categories.includes(cat)
            return (
              <button
                key={cat}
                type="button"
                onClick={() => toggleCategory(cat)}
                title={on ? `Competing in ${cat} — click to punt it` : `Punting ${cat} — click to compete in it`}
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
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-5">
        <label className="flex flex-1 min-w-[220px] flex-col gap-1">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Confidence: <span className="font-mono text-slate-300">{Math.round(spec.percentile * 100)}%</span>
          </span>
          <input
            type="range"
            min={5}
            max={95}
            step={1}
            value={Math.round(spec.percentile * 100)}
            onChange={(e) => setSpec({ ...spec, percentile: Number(e.target.value) / 100 })}
            style={{ accentColor: ACCENT }}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Push hardest on</span>
          <select
            value={spec.stat_to_maximize}
            onChange={(e) => setSpec({ ...spec, stat_to_maximize: e.target.value })}
            className="rounded-md border border-pg-border bg-black/30 px-2 py-1.5 text-sm text-white focus:outline-none"
          >
            {availableObjectives.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          onClick={() => spec.label.trim() && onSolve(spec)}
          disabled={pending || !spec.label.trim()}
          className="ml-auto rounded-lg px-4 py-2 text-sm font-semibold text-black transition-opacity disabled:opacity-50"
          style={{ backgroundColor: ACCENT }}
        >
          {pending ? 'Solving…' : 'Save & add to portfolio'}
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}

      {presets.length > 0 && (
        <div className="mt-3 border-t border-pg-border pt-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">My saved plans</p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {presets.map((p) => (
              <span
                key={p.label}
                className="flex items-center gap-1.5 rounded-md border border-pg-border px-2 py-1 text-xs text-slate-300"
              >
                {p.label}
                <button
                  type="button"
                  onClick={() => onDeletePreset(p.label)}
                  className="text-slate-500 hover:text-rose-400"
                  title="Delete saved plan"
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        </div>
      )}
    </Card>
  )
}
