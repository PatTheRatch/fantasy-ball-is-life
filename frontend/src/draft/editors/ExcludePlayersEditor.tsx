import { useState } from 'react'

export function ExcludePlayersEditor({
  excluded,
  onChange,
}: {
  excluded: string[]
  onChange: (list: string[]) => void
}) {
  const [input, setInput] = useState('')
  function add() {
    const key = input.trim().toLowerCase()
    if (!key || excluded.includes(key)) return
    onChange([...excluded, key])
    setInput('')
  }
  return (
    <div>
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Avoid these players</span>
      <div className="mt-1 flex gap-1.5">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
          placeholder="Player name…"
          className="min-w-0 flex-1 rounded-md border border-pg-border bg-black/30 px-2 py-1.5 text-sm text-white focus:outline-none"
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
        {excluded.map((key) => (
          <span
            key={key}
            className="flex items-center gap-1 rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-xs uppercase text-rose-300"
          >
            {key}
            <button
              type="button"
              onClick={() => onChange(excluded.filter((k) => k !== key))}
              className="text-rose-400 hover:text-rose-200"
              aria-label={`Stop avoiding ${key}`}
            >
              ×
            </button>
          </span>
        ))}
      </div>
    </div>
  )
}
