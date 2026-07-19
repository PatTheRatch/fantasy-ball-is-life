import { Search } from 'lucide-react'
import { useRef, useState } from 'react'
import type { DraftPlayerResult } from '../../api'
import { getDraftPlayers } from '../../api'

export function PlayerSearch({
  value,
  onChange,
  placeholder,
  className = '',
}: {
  value: string
  onChange: (v: string) => void
  placeholder: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const [results, setResults] = useState<DraftPlayerResult[]>([])
  const [loading, setLoading] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  function search(q: string) {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (q.length < 2) {
      setResults([])
      setLoading(false)
      return
    }
    setLoading(true)
    debounceRef.current = setTimeout(() => {
      getDraftPlayers(q).then(setResults).finally(() => setLoading(false))
    }, 200)
  }

  return (
    <div className={`relative ${className}`}>
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
        <input
          type="text"
          value={value}
          onChange={(e) => {
            onChange(e.target.value)
            search(e.target.value)
            setOpen(true)
          }}
          onFocus={() => value.length >= 2 && search(value)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => e.key === 'Escape' && setOpen(false)}
          placeholder={placeholder}
          className="w-full rounded-md border border-pg-border bg-black/30 py-1.5 pl-8 pr-6 text-sm text-white focus:outline-none"
        />
        {loading && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 h-3 w-3 animate-spin rounded-full border border-slate-500 border-t-white" />
        )}
      </div>
      {open && results.length > 0 && (
        <div className="absolute z-20 mt-1 max-h-48 w-full overflow-y-auto rounded-md border border-pg-border bg-pg-card shadow-lg">
          {results.map((r) => (
            <button
              key={r.player_key}
              type="button"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => {
                onChange(r.player_key)
                setOpen(false)
              }}
              className="flex w-full items-center justify-between px-3 py-1.5 text-left text-sm hover:bg-slate-800"
            >
              <span className="font-semibold uppercase text-slate-200">{r.player_key}</span>
              <span className="ml-2 shrink-0 text-xs text-slate-500">
                {r.pos ?? ''} {r.value != null ? `· $${r.value}` : ''}
              </span>
            </button>
          ))}
        </div>
      )}
      {open && value.length >= 2 && !loading && results.length === 0 && (
        <div className="absolute z-20 mt-1 w-full rounded-md border border-pg-border bg-pg-card px-3 py-2 text-xs text-slate-500 shadow-lg">
          No players found
        </div>
      )}
    </div>
  )
}
