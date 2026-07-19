import type { DraftPoolParams } from '../api'
import { Card } from '../components/Card'
import { ACCENT } from './constants'
import { ExcludePlayersEditor } from './editors/ExcludePlayersEditor'
import { FavoriteTeamEditor } from './editors/FavoriteTeamEditor'
import { TargetPlayersEditor } from './editors/TargetPlayersEditor'
import { NumberField } from './shared/NumberField'

export function SetupPanel({
  params,
  onChange,
  onGenerate,
  pending,
  error,
  hasPortfolio,
  pickCount,
  skippedTargets,
  onOpenAdvanced,
}: {
  params: DraftPoolParams
  onChange: (p: DraftPoolParams) => void
  onGenerate: () => void
  pending: boolean
  error: string | null
  hasPortfolio: boolean
  pickCount: number
  skippedTargets: string[]
  onOpenAdvanced: () => void
}) {
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3">
        <NumberField
          label="Plans"
          value={params.n_plans ?? 10}
          onChange={(v) => onChange({ ...params, n_plans: v })}
          min={1}
          max={10}
        />
        <NumberField
          label="Budget"
          value={params.initial_budget ?? 200}
          onChange={(v) => onChange({ ...params, initial_budget: v })}
          min={1}
        />
        <NumberField
          label="Roster size"
          value={params.roster_size ?? 13}
          onChange={(v) => onChange({ ...params, roster_size: v })}
          min={1}
        />
        <button
          type="button"
          onClick={onOpenAdvanced}
          className="rounded-lg border border-pg-border px-3 py-2 text-xs font-semibold text-slate-300"
        >
          Advanced
        </button>
        <button
          type="button"
          onClick={onGenerate}
          disabled={pending}
          className="ml-auto rounded-lg px-4 py-2 text-sm font-semibold text-black transition-opacity disabled:opacity-50"
          style={{ backgroundColor: ACCENT }}
        >
          {pending ? 'Generating…' : hasPortfolio ? 'Regenerate portfolio' : 'Generate portfolio'}
        </button>
      </div>

      <div className="mt-4 border-t border-pg-border pt-4">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
          Team construction
        </p>
        <div className="mt-2 grid grid-cols-1 gap-4 md:grid-cols-3">
          <ExcludePlayersEditor
            excluded={params.exclude_players ?? []}
            onChange={(list) => onChange({ ...params, exclude_players: list })}
          />
          <FavoriteTeamEditor
            team={params.favorite_team ?? ''}
            representation={params.favorite_team_representation ?? 1}
            onChange={(team, representation) =>
              onChange({
                ...params,
                favorite_team: team || null,
                favorite_team_representation: representation,
              })
            }
          />
          <TargetPlayersEditor
            targets={params.target_players ?? []}
            skipped={skippedTargets}
            onChange={(list) => onChange({ ...params, target_players: list })}
          />
        </div>
      </div>

      {pickCount > 0 && (
        <p className="mt-3 text-xs text-slate-500">
          {pickCount} pick(s) logged so far will be applied.
        </p>
      )}
      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}
    </Card>
  )
}
