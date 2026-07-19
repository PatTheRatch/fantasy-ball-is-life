import { useState } from 'react'
import type { DraftTargetPlayer } from '../../api'
import { ACCENT } from '../constants'

export function TargetPlayersEditor({
  targets,
  skipped,
  onChange,
}: {
  targets: DraftTargetPlayer[]
  skipped: string[]
  onChange: (list: DraftTargetPlayer[]) => void
}) {
  const [name, setName] = useState('')
  const [price, setPrice] = useState('')
  function add() {
    const key = name.trim().toLowerCase()
    if (!key || targets.some((t) => t.player_key === key)) return
    const expected = price.trim() ? Number(price) : null
    onChange([...targets, { player_key: key, expected_price: Number.isFinite(expected) ? expected : null }])
    setName('')
    setPrice('')
  }
  return (
    <div>
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        Target players <span className="normal-case text-slate-600">(pre-locked at projected $ unless set)</span>
      </span>
      <div className="mt-1 flex gap-1.5">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          placeholder="Player name…"
          className="min-w-0 flex-1 rounded-md border border-pg-border bg-black/30 px-2 py-1.5 text-sm text-white focus:outline-none"
        />
        <input
          type="number"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          placeholder="$ (opt.)"
          className="w-20 rounded-md border border-pg-border bg-black/30 px-2 py-1.5 text-sm text-white focus:outline-none"
        />
        <button
          type="button"
          onClick={add}
          className="rounded-md border border-pg-border px-2.5 py-1.5 text-xs font-semibold text-slate-200 hover:border-slate-500"
        >
          Add
        </button>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {targets.map((t) => (
          <span
            key={t.player_key}
            className="flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs uppercase"
            style={{ borderColor: ACCENT, backgroundColor: `${ACCENT}1a`, color: '#fbbf24' }}
          >
            {t.player_key}
            {t.expected_price != null && <span className="font-mono">${t.expected_price}</span>}
            <button
              type="button"
              onClick={() => onChange(targets.filter((x) => x.player_key !== t.player_key))}
              className="hover:text-white"
              aria-label={`Remove target ${t.player_key}`}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      {skipped.length > 0 && (
        <p className="mt-1.5 text-xs text-rose-400">
          Couldn&apos;t lock in: {skipped.join(', ')} — not in the current pool (games threshold, excluded, or a typo).
        </p>
      )}
    </div>
  )
}
