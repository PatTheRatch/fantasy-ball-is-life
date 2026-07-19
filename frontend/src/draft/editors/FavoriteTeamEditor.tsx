import { NBA_TEAMS } from '../constants'

export function FavoriteTeamEditor({
  team,
  representation,
  onChange,
}: {
  team: string
  representation: number
  onChange: (team: string, representation: number) => void
}) {
  return (
    <div>
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Favorite team</span>
      <div className="mt-1 flex gap-1.5">
        <select
          value={team}
          onChange={(e) => onChange(e.target.value, representation)}
          className="min-w-0 flex-1 rounded-md border border-pg-border bg-black/30 px-2 py-1.5 text-sm text-white focus:outline-none"
        >
          <option value="">None</option>
          {NBA_TEAMS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        {team && (
          <label className="flex items-center gap-1.5">
            <span className="text-xs text-slate-500">min</span>
            <input
              type="number"
              min={1}
              max={13}
              value={representation}
              onChange={(e) => onChange(team, Number(e.target.value))}
              className="w-14 rounded-md border border-pg-border bg-black/30 px-2 py-1.5 text-sm text-white focus:outline-none"
            />
          </label>
        )}
      </div>
      {team && (
        <p className="mt-1.5 text-xs text-slate-500">
          Every plan will include at least {representation} {team} player(s).
        </p>
      )}
    </div>
  )
}
