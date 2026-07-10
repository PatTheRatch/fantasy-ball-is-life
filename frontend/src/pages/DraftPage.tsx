import { useMutation, useQuery } from '@tanstack/react-query'
import { Redo2, Search, Undo2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import type {
  CustomPlanSpec,
  DraftPickEntry,
  DraftPlanSnapshot,
  DraftPlayerRow,
  DraftPoolParams,
  DraftPortfolioResponse,
  DraftRelaxProposal,
  DraftTargetPlayer,
  DraftTriageResponse,
} from '../api'
import {
  formatApiError,
  getDraftPlayers,
  getLeagueTeams,
  postDraftCustomPlan,
  postDraftPick,
  postDraftPlans,
  postDraftRelax,
  postDraftTriage,
} from '../api'
import type { DraftPlayerResult } from '../api'
import { Card } from '../components/Card'

/* -------------------------------------------------------------------------- */
/* Draft Room — docs/specs/DRAFT_ROOM.md. Scoped "data-dense terminal" look   */
/* (D3): amber accent + tabular numerals, layered on the app's existing dark  */
/* chrome (Card, pg-* tokens) rather than reskinning the whole product.       */
/* -------------------------------------------------------------------------- */

const ACCENT = '#e7a93c'
const CATS = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'FG%', 'FT%', 'TO'] as const
// Only counting categories are valid optimizer objectives (maximizing a
// percentage or turnovers is undefined) — mirrors draft_strategies.COUNTING_CATS.
const COUNTING_CATS = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM'] as const
// Static, not league-specific — "favorite NBA team" is independent of ESPN/
// fantasy-league state, so no endpoint round-trip is needed for this dropdown.
const NBA_TEAMS = [
  'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
  'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
  'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS',
] as const

const STORAGE_KEY = 'draft-room-v1'
const SCHEMA_VERSION = 1
const PRESETS_STORAGE_KEY = 'draft-room-presets-v1'

// Starting points for "Build a plan" (below) — the same shapes build_plan_configs'
// recipe uses, at their current percentile-band midpoint (draft_strategies.py,
// STRATEGY_PERCENTILE_BANDS as of 2026-07-10), so a user's blank-slate build
// starts from a sane, already-tuned baseline. Purely a prefill: every field is
// editable afterward, nothing here is enforced server-side.
const BUILTIN_TEMPLATES: CustomPlanSpec[] = [
  {
    label: 'Balanced',
    constrained_categories: [...CATS],
    percentile: 0.35,
    stat_to_maximize: 'PTS',
    minimum_value_players: 3,
    ban_top_price: false,
  },
  {
    label: 'Stars & scrubs',
    constrained_categories: [...CATS],
    percentile: 0.25,
    stat_to_maximize: 'PTS',
    minimum_value_players: 6,
    ban_top_price: false,
  },
  {
    label: 'Spread value',
    constrained_categories: [...CATS],
    percentile: 0.33,
    stat_to_maximize: 'PTS',
    minimum_value_players: 1,
    ban_top_price: true,
  },
]

const BLANK_CUSTOM_SPEC: CustomPlanSpec = {
  label: '',
  constrained_categories: [...CATS],
  percentile: 0.5,
  stat_to_maximize: 'PTS',
  minimum_value_players: 3,
  ban_top_price: false,
}

function loadPresets(): CustomPlanSpec[] {
  try {
    const raw = localStorage.getItem(PRESETS_STORAGE_KEY)
    if (raw) return JSON.parse(raw) as CustomPlanSpec[]
  } catch {
    // corrupt/old localStorage payload — fall through to an empty library
  }
  return []
}

interface StoredState {
  schemaVersion: number
  picks: DraftPickEntry[]
  portfolio: DraftPortfolioResponse | null
  activePlanId: string | null
  params: DraftPoolParams
}

const DEFAULT_PARAMS: DraftPoolParams = {
  n_plans: 10,
  initial_budget: 200,
  roster_size: 13,
  minimum_game_threshold: 20,
  games_per_week: 3,
  minimum_value_players: 3,
  exclude_players: [],
  favorite_team: null,
  favorite_team_representation: 1,
  target_players: [],
  target_categories: null,
  base_percentile: null,
  stat_to_maximize: null,
}

function loadStored(): StoredState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as StoredState
      if (parsed.schemaVersion === SCHEMA_VERSION) return parsed
    }
  } catch {
    // corrupt/old localStorage payload — fall through to a clean slate
  }
  return { schemaVersion: SCHEMA_VERSION, picks: [], portfolio: null, activePlanId: null, params: DEFAULT_PARAMS }
}

function fmtBid(n: number | null | undefined): string {
  return n == null ? '—' : `$${Math.round(n)}`
}

function fmtStat(n: number | null | undefined, digits = 1): string {
  return n == null ? '—' : n.toFixed(digits)
}

function fmtPct(n: number | null | undefined): string {
  return n == null ? '—' : `${(n * 100).toFixed(1)}%`
}

/** The always-on fallback the "never freeze" guarantee depends on (spec §2
 * criterion 2): first still-Alive plan, in portfolio order. Used client-side
 * after a local edit (e.g. accepting a relax proposal) without a round-trip. */
function firstAlive(plans: DraftPlanSnapshot[]): DraftPlanSnapshot | null {
  return plans.find((p) => p.health === 'alive') ?? null
}

function healthPillClass(health: 'alive' | 'broken'): string {
  return health === 'alive'
    ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400'
    : 'border-rose-500/40 bg-rose-500/10 text-rose-400'
}

export function DraftPage() {
  const [picks, setPicks] = useState<DraftPickEntry[]>(() => loadStored().picks)
  const [portfolio, setPortfolio] = useState<DraftPortfolioResponse | null>(() => loadStored().portfolio)
  const [activePlanId, setActivePlanId] = useState<string | null>(() => loadStored().activePlanId)
  const [params, setParams] = useState<DraftPoolParams>(() => loadStored().params)

  const [onBlockKey, setOnBlockKey] = useState('')
  const [onBlockPrice, setOnBlockPrice] = useState('')
  const [onBlockTeamId, setOnBlockTeamId] = useState('you')
  const [triageResult, setTriageResult] = useState<DraftTriageResponse | null>(null)
  const [relaxProposal, setRelaxProposal] = useState<DraftRelaxProposal | null>(null)

  const [pickName, setPickName] = useState('')
  const [pickPrice, setPickPrice] = useState('')
  const [pickTeamId, setPickTeamId] = useState('you')

  const [presets, setPresets] = useState<CustomPlanSpec[]>(() => loadPresets())

  // D12: same-device autosave, so an accidental refresh mid-draft loses nothing.
  useEffect(() => {
    const state: StoredState = { schemaVersion: SCHEMA_VERSION, picks, portfolio, activePlanId, params }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  }, [picks, portfolio, activePlanId, params])

  // Saved custom plan *parameters* (not solved rosters) — a separate, durable
  // library so "hit save, then make a new one" survives across drafts/refreshes.
  useEffect(() => {
    localStorage.setItem(PRESETS_STORAGE_KEY, JSON.stringify(presets))
  }, [presets])

  const teamsQuery = useQuery({
    queryKey: ['draft', 'teams'],
    queryFn: getLeagueTeams,
    retry: 0,
  })

  const generateMutation = useMutation({
    mutationFn: () => postDraftPlans({ ...params, picks }),
    onSuccess: (data) => {
      setPortfolio(data)
      setActivePlanId(data.fallback_next?.plan_id ?? firstAlive(data.plans)?.plan_id ?? null)
      setRelaxProposal(null)
      setTriageResult(null)
    },
  })

  // "Build a plan" (below the recipe) — solves one hand-tuned config and
  // merges it into the working portfolio, alongside whatever the recipe
  // generated. Saving the params to `presets` is what makes "save, then
  // build another one" durable across sessions.
  const customPlanMutation = useMutation({
    mutationFn: (spec: CustomPlanSpec) => postDraftCustomPlan({ ...params, ...spec, picks }),
    onSuccess: (data, spec) => {
      setPortfolio((prev) => {
        const base: DraftPortfolioResponse = prev ?? {
          plans: [],
          fallback_next: null,
          value_board: data.value_board,
          skipped_targets: data.skipped_targets ?? [],
        }
        const withoutDup = base.plans.filter((p) => p.plan_id !== data.plan.plan_id)
        return {
          ...base,
          plans: [...withoutDup, data.plan],
          fallback_next: base.fallback_next ?? { plan_id: data.plan.plan_id, label: data.plan.label, player_key: data.plan.next_target?.player_key ?? null, max_bid: data.plan.next_target?.max_bid ?? null },
          value_board: data.value_board,
          skipped_targets: data.skipped_targets ?? base.skipped_targets,
        }
      })
      setActivePlanId(data.plan.plan_id)
      setPresets((prev) => [...prev.filter((p) => p.label !== spec.label), spec])
    },
  })

  function deletePreset(label: string) {
    setPresets((prev) => prev.filter((p) => p.label !== label))
  }

  const logPickMutation = useMutation({
    mutationFn: (newPick: DraftPickEntry) => {
      const newPicks = [...picks, newPick]
      if (!portfolio) throw new Error('Generate a portfolio before logging picks.')
      return postDraftPick({ ...params, picks: newPicks, new_pick: newPick, prior_plans: portfolio.plans }).then(
        (data) => ({ data, newPicks }),
      )
    },
    onSuccess: ({ data, newPicks }) => {
      setPicks(newPicks)
      setPortfolio(data)
      setActivePlanId((prev) => {
        const stillAlive = data.plans.find((p) => p.plan_id === prev && p.health === 'alive')
        return stillAlive ? prev : (data.fallback_next?.plan_id ?? firstAlive(data.plans)?.plan_id ?? null)
      })
      setRelaxProposal(null)
      setPickName('')
      setPickPrice('')
      setOnBlockKey('')
      setOnBlockPrice('')
      setTriageResult(null)
    },
  })

  // Undo (spec §6): recompute from the full picks log, not incremental
  // patching — a removal doesn't fit /draft/pick's single-addition contract,
  // so this re-generates the whole portfolio from the shorter picks list.
  const undoMutation = useMutation({
    mutationFn: (index: number) => {
      const newPicks = picks.filter((_, i) => i !== index)
      return postDraftPlans({ ...params, picks: newPicks }).then((data) => ({ data, newPicks }))
    },
    onSuccess: ({ data, newPicks }) => {
      setPicks(newPicks)
      setPortfolio(data)
      setActivePlanId(data.fallback_next?.plan_id ?? firstAlive(data.plans)?.plan_id ?? null)
      setRelaxProposal(null)
    },
  })

  const triageMutation = useMutation({
    mutationFn: (playerKey: string) => {
      if (!portfolio) throw new Error('Generate a portfolio first.')
      return postDraftTriage({ ...params, picks, prior_plans: portfolio.plans, player_key: playerKey })
    },
    onSuccess: (data) => setTriageResult(data),
  })

  const relaxMutation = useMutation({
    mutationFn: () => {
      if (!portfolio) throw new Error('Generate a portfolio first.')
      return postDraftRelax({ ...params, picks, prior_plans: portfolio.plans, plan_id: activePlanId })
    },
    onSuccess: (data) => setRelaxProposal(data.proposal),
  })

  const activePlan = useMemo(
    () => portfolio?.plans.find((p) => p.plan_id === activePlanId) ?? null,
    [portfolio, activePlanId],
  )
  const everyPlanBroken = useMemo(
    () => (portfolio ? portfolio.plans.every((p) => p.health === 'broken') : false),
    [portfolio],
  )
  const ownedKeys = useMemo(
    () => new Set(picks.filter((p) => p.is_user).map((p) => p.player_key)),
    [picks],
  )
  const targetKeys = useMemo(
    () => new Set((params.target_players ?? []).map((t) => t.player_key)),
    [params.target_players],
  )
  const budgetSpent = useMemo(
    () => picks.filter((p) => p.is_user).reduce((sum, p) => sum + p.price, 0),
    [picks],
  )
  const budgetRemaining = (params.initial_budget ?? 200) - budgetSpent

  function acceptRelaxProposal() {
    if (!relaxProposal || !portfolio) return
    const cleaned: DraftPlanSnapshot = {
      plan_id: relaxProposal.relaxed_from_plan_id,
      label: relaxProposal.label,
      shape: relaxProposal.shape,
      config: relaxProposal.config,
      roster: relaxProposal.roster,
      players: relaxProposal.players,
      health: 'alive',
      health_reason: null,
      next_target: relaxProposal.next_target,
    }
    const nextPlans = portfolio.plans.map((p) => (p.plan_id === cleaned.plan_id ? cleaned : p))
    setPortfolio({ ...portfolio, plans: nextPlans })
    setActivePlanId(cleaned.plan_id)
    setRelaxProposal(null)
  }

  function submitPick() {
    const key = pickName.trim().toLowerCase()
    const price = Number(pickPrice)
    if (!key || Number.isNaN(price)) return
    const isUser = pickTeamId === 'you'
    logPickMutation.mutate({ player_key: key, price, team_id: pickTeamId, is_user: isUser })
  }

  // The on-the-block player is about to be sold — you're always going to say
  // who got them right after checking relevance, so logging the sale lives
  // in the same card instead of a second "type the name again" form.
  function submitOnBlockPick() {
    const key = onBlockKey.trim().toLowerCase()
    const price = Number(onBlockPrice)
    if (!key || Number.isNaN(price)) return
    const isUser = onBlockTeamId === 'you'
    logPickMutation.mutate({ player_key: key, price, team_id: onBlockTeamId, is_user: isUser })
  }

  return (
    <div className="space-y-4" style={{ fontVariantNumeric: 'tabular-nums' }}>
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white md:text-3xl">Draft Room</h1>
        <p className="mt-1 text-sm text-slate-400">
          Build and pivot your target roster live, against the real optimizer.
        </p>
      </div>

      <SetupPanel
        params={params}
        onChange={setParams}
        onGenerate={() => generateMutation.mutate()}
        pending={generateMutation.isPending}
        error={generateMutation.isError ? formatApiError(generateMutation.error) : null}
        hasPortfolio={portfolio != null}
        pickCount={picks.length}
        skippedTargets={portfolio?.skipped_targets ?? []}
      />

      <CustomPlanCard
        presets={presets}
        onDeletePreset={deletePreset}
        onSolve={(spec) => customPlanMutation.mutate(spec)}
        pending={customPlanMutation.isPending}
        error={customPlanMutation.isError ? formatApiError(customPlanMutation.error) : null}
      />

      {portfolio && (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
            <div className="space-y-4">
              <OnBlockCard
                onBlockKey={onBlockKey}
                setOnBlockKey={setOnBlockKey}
                onCheck={() => onBlockKey.trim() && triageMutation.mutate(onBlockKey.trim().toLowerCase())}
                checkPending={triageMutation.isPending}
                result={triageResult}
                price={onBlockPrice}
                setPrice={setOnBlockPrice}
                teamId={onBlockTeamId}
                setTeamId={setOnBlockTeamId}
                teams={teamsQuery.data ?? []}
                onLogPick={submitOnBlockPick}
                logPending={logPickMutation.isPending}
                logError={logPickMutation.isError ? formatApiError(logPickMutation.error) : null}
              />

              <AddPickCard
                pickName={pickName}
                setPickName={setPickName}
                pickPrice={pickPrice}
                setPickPrice={setPickPrice}
                pickTeamId={pickTeamId}
                setPickTeamId={setPickTeamId}
                teams={teamsQuery.data ?? []}
                onSubmit={submitPick}
                pending={logPickMutation.isPending}
                error={logPickMutation.isError ? formatApiError(logPickMutation.error) : null}
              />

              <NextMoveCard activePlan={activePlan} fallback={portfolio.fallback_next} />

              {everyPlanBroken && (
                <RelaxCard
                  proposal={relaxProposal}
                  onRelax={() => relaxMutation.mutate()}
                  onAccept={acceptRelaxProposal}
                  pending={relaxMutation.isPending}
                  error={relaxMutation.isError ? formatApiError(relaxMutation.error) : null}
                />
              )}

              <PivotPlansStrip plans={portfolio.plans} activePlanId={activePlanId} onSelect={setActivePlanId} />

              <RosterTable plan={activePlan} ownedKeys={ownedKeys} targetKeys={targetKeys} />
            </div>

            <div className="space-y-4">
              <BudgetCard spent={budgetSpent} remaining={budgetRemaining} total={params.initial_budget ?? 200} />
              <ValueBoardCard rows={portfolio.value_board} />
              <PicksLogCard picks={picks} onUndo={(i) => undoMutation.mutate(i)} pending={undoMutation.isPending} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Setup                                                                      */
/* -------------------------------------------------------------------------- */

function SetupPanel({
  params,
  onChange,
  onGenerate,
  pending,
  error,
  hasPortfolio,
  pickCount,
  skippedTargets,
}: {
  params: DraftPoolParams
  onChange: (p: DraftPoolParams) => void
  onGenerate: () => void
  pending: boolean
  error: string | null
  hasPortfolio: boolean
  pickCount: number
  skippedTargets: string[]
}) {
  const selectedCats = params.target_categories ?? [...CATS]
  const percentile = params.base_percentile ?? 0.7
  const availableObjectives = COUNTING_CATS.filter((c) => selectedCats.includes(c))

  function toggleCategory(cat: string) {
    const next = selectedCats.includes(cat) ? selectedCats.filter((c) => c !== cat) : [...selectedCats, cat]
    if (next.length === 0) return // must keep at least one category selected
    const patch: DraftPoolParams = { ...params, target_categories: next }
    // The current objective may no longer be valid under the new selection —
    // fall back to the recipe default rather than send an invalid combination.
    if (params.stat_to_maximize && !next.includes(params.stat_to_maximize)) {
      patch.stat_to_maximize = null
    }
    onChange(patch)
  }

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
          onClick={onGenerate}
          disabled={pending}
          className="ml-auto rounded-lg px-4 py-2 text-sm font-semibold text-black transition-opacity disabled:opacity-50"
          style={{ backgroundColor: ACCENT }}
        >
          {pending ? 'Generating…' : hasPortfolio ? 'Regenerate portfolio' : 'Generate portfolio'}
        </button>
      </div>

      <div className="mt-4 border-t border-pg-border pt-4">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">What to optimize for</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {CATS.map((cat) => {
            const on = selectedCats.includes(cat)
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
        <p className="mt-1 text-xs text-slate-500">
          Unselected categories are always punted across every generated plan.
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-5">
          <label className="flex flex-1 min-w-[220px] flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Confidence — how likely to win a category: <span className="font-mono text-slate-300">{Math.round(percentile * 100)}%</span>
            </span>
            <input
              type="range"
              min={50}
              max={95}
              step={1}
              value={Math.round(percentile * 100)}
              onChange={(e) => onChange({ ...params, base_percentile: Number(e.target.value) / 100 })}
              style={{ accentColor: ACCENT }}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Push hardest on</span>
            <select
              value={params.stat_to_maximize ?? ''}
              onChange={(e) => onChange({ ...params, stat_to_maximize: e.target.value || null })}
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
      </div>

      <div className="mt-4 border-t border-pg-border pt-4">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Team construction</p>
        <div className="mt-2 grid grid-cols-1 gap-4 md:grid-cols-3">
          <ExcludePlayersEditor
            excluded={params.exclude_players ?? []}
            onChange={(list) => onChange({ ...params, exclude_players: list })}
          />
          <FavoriteTeamEditor
            team={params.favorite_team ?? ''}
            representation={params.favorite_team_representation ?? 1}
            onChange={(team, representation) =>
              onChange({ ...params, favorite_team: team || null, favorite_team_representation: representation })
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
        <p className="mt-3 text-xs text-slate-500">{pickCount} pick(s) logged so far will be applied.</p>
      )}
      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}
    </Card>
  )
}

/** "Build a plan" — solve one fully hand-tuned config on demand and add it to
 * the working portfolio, separate from the recipe SetupPanel drives. Start
 * from a built-in shape or a previously saved plan, or from blank — "but
 * they don't have to." Saving persists the *parameters*, not the solved
 * roster, so the same plan can be re-solved later against a changed pool. */
function CustomPlanCard({
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

function ExcludePlayersEditor({
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

function FavoriteTeamEditor({
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

function TargetPlayersEditor({
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

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-24 rounded-md border border-pg-border bg-black/30 px-2 py-1.5 text-sm text-white focus:outline-none"
      />
    </label>
  )
}

/* -------------------------------------------------------------------------- */
/* Player search (autocomplete — GET /draft/players)                          */
/* -------------------------------------------------------------------------- */

function PlayerSearch({
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

/* -------------------------------------------------------------------------- */
/* On the block / triage (spec §2 criterion 3)                                */
/* -------------------------------------------------------------------------- */

function OnBlockCard({
  onBlockKey,
  setOnBlockKey,
  onCheck,
  checkPending,
  result,
  price,
  setPrice,
  teamId,
  setTeamId,
  teams,
  onLogPick,
  logPending,
  logError,
}: {
  onBlockKey: string
  setOnBlockKey: (v: string) => void
  onCheck: () => void
  checkPending: boolean
  result: DraftTriageResponse | null
  price: string
  setPrice: (v: string) => void
  teamId: string
  setTeamId: (v: string) => void
  teams: Record<string, unknown>[]
  onLogPick: () => void
  logPending: boolean
  logError: string | null
}) {
  return (
    <Card>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        On the block — you set who&apos;s up
      </p>
      <div className="mt-2 flex gap-2">
        <PlayerSearch
          value={onBlockKey}
          onChange={setOnBlockKey}
          placeholder="Player just nominated…"
          className="flex-1"
        />
        <button
          type="button"
          onClick={onCheck}
          disabled={checkPending || !onBlockKey.trim()}
          className="rounded-md border border-pg-border px-3 py-1.5 text-sm font-semibold text-slate-200 hover:border-slate-500 disabled:opacity-50"
        >
          {checkPending ? '…' : 'Check'}
        </button>
      </div>
      {result && (
        <div
          className={`mt-3 rounded-md border px-3 py-2 text-sm ${
            result.relevant
              ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
              : 'border-pg-border bg-black/20 text-slate-400'
          }`}
        >
          {result.relevant ? (
            <>
              <span className="font-semibold">Relevant</span> — {result.reason === 'in_plan' ? `in ${result.in_plans.length} plan(s)` : 'top value on the board'}.
              {result.max_bid != null && <> Your max: <span className="font-mono">{fmtBid(result.max_bid)}</span></>}
            </>
          ) : (
            <>Safe to pass — not in a live plan, not a value target.</>
          )}
        </div>
      )}

      {/* Whoever's on the block is about to be sold — log it right here,
          same name, no retyping. */}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-pg-border pt-3">
        <span className="text-xs text-slate-500">Sold to</span>
        <div className="relative">
          <span className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-xs text-slate-500">$</span>
          <input
            type="number"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onLogPick()}
            placeholder="0"
            className="w-20 rounded-md border border-pg-border bg-black/30 py-1.5 pl-5 pr-2 text-sm text-white focus:outline-none"
          />
        </div>
        <select
          value={teamId}
          onChange={(e) => setTeamId(e.target.value)}
          className="rounded-md border border-pg-border bg-black/30 px-2 py-1.5 text-sm text-white focus:outline-none"
        >
          <option value="you">You — your roster</option>
          {teams.map((t) => {
            const id = String(t.team_id ?? t.team_name)
            const name = String(t.team_name ?? id)
            return (
              <option key={id} value={id}>
                {name}
              </option>
            )
          })}
        </select>
        <button
          type="button"
          onClick={onLogPick}
          disabled={logPending || !onBlockKey.trim()}
          className="rounded-md px-3 py-1.5 text-sm font-semibold text-black disabled:opacity-50"
          style={{ backgroundColor: ACCENT }}
        >
          {logPending ? 'Logging…' : 'Log pick'}
        </button>
      </div>
      {logError && <p className="mt-2 text-xs text-rose-400">{logError}</p>}
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* Add / correct a pick (D6: team dropdown + undo lives in the picks log)     */
/* -------------------------------------------------------------------------- */

function AddPickCard({
  pickName,
  setPickName,
  pickPrice,
  setPickPrice,
  pickTeamId,
  setPickTeamId,
  teams,
  onSubmit,
  pending,
  error,
}: {
  pickName: string
  setPickName: (v: string) => void
  pickPrice: string
  setPickPrice: (v: string) => void
  pickTeamId: string
  setPickTeamId: (v: string) => void
  teams: Record<string, unknown>[]
  onSubmit: () => void
  pending: boolean
  error: string | null
}) {
  return (
    <Card>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Add or correct a pick</p>
      <p className="mt-0.5 text-xs text-slate-500">
        For picks you missed or need to fix — use &ldquo;On the block&rdquo; above for the live flow.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <PlayerSearch
          value={pickName}
          onChange={setPickName}
          placeholder="Player name…"
          className="min-w-[10rem] flex-1"
        />
        <div className="relative">
          <span className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-xs text-slate-500">$</span>
          <input
            type="number"
            value={pickPrice}
            onChange={(e) => setPickPrice(e.target.value)}
            placeholder="0"
            className="w-20 rounded-md border border-pg-border bg-black/30 py-1.5 pl-5 pr-2 text-sm text-white focus:outline-none"
          />
        </div>
        <select
          value={pickTeamId}
          onChange={(e) => setPickTeamId(e.target.value)}
          className="rounded-md border border-pg-border bg-black/30 px-2 py-1.5 text-sm text-white focus:outline-none"
        >
          <option value="you">You — your roster</option>
          {teams.map((t) => {
            const id = String(t.team_id ?? t.team_name)
            const name = String(t.team_name ?? id)
            return (
              <option key={id} value={id}>
                {name}
              </option>
            )
          })}
        </select>
        <button
          type="button"
          onClick={onSubmit}
          disabled={pending || !pickName.trim()}
          className="rounded-md px-3 py-1.5 text-sm font-semibold text-black disabled:opacity-50"
          style={{ backgroundColor: ACCENT }}
        >
          {pending ? 'Logging…' : 'Log pick'}
        </button>
      </div>
      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* Next move (spec §2 criterion 2/5: never-empty guarantee)                   */
/* -------------------------------------------------------------------------- */

function NextMoveCard({
  activePlan,
  fallback,
}: {
  activePlan: DraftPlanSnapshot | null
  fallback: DraftPortfolioResponse['fallback_next']
}) {
  const target = activePlan?.health === 'alive' ? activePlan.next_target : null
  return (
    <Card className="border-l-4" style={{ borderLeftColor: ACCENT }}>
      <p className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: ACCENT }}>
        Next move · {activePlan?.label ?? '—'}
      </p>
      {target ? (
        <>
          <p className="mt-1 text-lg font-bold uppercase text-white">Nominate {target.player_key}</p>
          <div className="mt-1 flex gap-6 text-sm">
            <span className="text-slate-400">
              Fair value <span className="ml-1 font-mono text-slate-200">{fmtBid(target.value)}</span>
            </span>
            <span className="text-slate-400">
              Your max <span className="ml-1 font-mono font-semibold" style={{ color: ACCENT }}>{fmtBid(target.max_bid)}</span>
            </span>
          </div>
        </>
      ) : (
        <p className="mt-1 text-sm text-slate-400">No target needed — this plan&apos;s roster is complete.</p>
      )}
      {fallback && fallback.plan_id !== activePlan?.plan_id && fallback.player_key && (
        <div className="mt-3 flex items-center gap-2 border-t border-dashed border-pg-border pt-2 text-xs text-slate-400">
          <Redo2 className="h-3.5 w-3.5 flex-none" style={{ color: ACCENT }} />
          If you miss → <span className="font-semibold text-slate-200">{fallback.label}</span> has{' '}
          <span className="font-semibold uppercase text-slate-200">{fallback.player_key}</span> ready · max{' '}
          <span className="font-mono">{fmtBid(fallback.max_bid)}</span>
        </div>
      )}
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* Relax (spec §2 criterion 6: graceful degradation when every plan breaks)   */
/* -------------------------------------------------------------------------- */

function RelaxCard({
  proposal,
  onRelax,
  onAccept,
  pending,
  error,
}: {
  proposal: DraftRelaxProposal | null
  onRelax: () => void
  onAccept: () => void
  pending: boolean
  error: string | null
}) {
  return (
    <Card className="border-rose-500/40 bg-rose-500/[0.04]">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-rose-400">
        Every saved plan is broken
      </p>
      {!proposal ? (
        <>
          <p className="mt-1 text-sm text-slate-400">
            Find the least-costly way back to a feasible roster (re-solves dropping one category at a
            time — up to ~30s).
          </p>
          <button
            type="button"
            onClick={onRelax}
            disabled={pending}
            className="mt-2 rounded-md border border-rose-500/40 px-3 py-1.5 text-sm font-semibold text-rose-300 hover:bg-rose-500/10 disabled:opacity-50"
          >
            {pending ? 'Searching…' : 'Find a way out'}
          </button>
        </>
      ) : (
        <>
          <p className="mt-1 text-sm text-slate-300">
            Punt <span className="font-semibold text-white">{proposal.dropped_category}</span> to stay
            feasible — objective score <span className="font-mono">{fmtStat(proposal.objective_score)}</span>.
          </p>
          <button
            type="button"
            onClick={onAccept}
            className="mt-2 rounded-md px-3 py-1.5 text-sm font-semibold text-black"
            style={{ backgroundColor: ACCENT }}
          >
            Accept this plan
          </button>
        </>
      )}
      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* Pivot plans (D8/D9)                                                        */
/* -------------------------------------------------------------------------- */

function PivotPlansStrip({
  plans,
  activePlanId,
  onSelect,
}: {
  plans: DraftPlanSnapshot[]
  activePlanId: string | null
  onSelect: (id: string) => void
}) {
  return (
    <Card>
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Pivot plans</p>
      <div className="flex gap-2 overflow-x-auto pb-1">
        {plans.map((p) => {
          const active = p.plan_id === activePlanId
          const disabled = p.health === 'broken'
          return (
            <button
              key={p.plan_id}
              type="button"
              disabled={disabled}
              onClick={() => onSelect(p.plan_id)}
              className={`flex flex-none items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed ${
                active ? '' : 'border-pg-border bg-black/20 hover:border-slate-500'
              }`}
              style={active ? { borderColor: ACCENT, backgroundColor: `${ACCENT}1f` } : undefined}
            >
              <span className="text-sm font-semibold text-white">{p.label}</span>
              <span className={`rounded border px-1.5 py-0.5 text-[10px] font-mono ${healthPillClass(p.health)}`}>
                {p.health === 'alive' ? 'Alive' : 'Broken'}
              </span>
            </button>
          )
        })}
      </div>
    </Card>
  )
}

/* -------------------------------------------------------------------------- */
/* Roster table (D5: $, max bid, VOR-ish value, all 9 cats)                   */
/* -------------------------------------------------------------------------- */

function RosterTable({
  plan,
  ownedKeys,
  targetKeys,
}: {
  plan: DraftPlanSnapshot | null
  ownedKeys: Set<string>
  targetKeys: Set<string>
}) {
  if (!plan) return null
  return (
    <Card>
      <div className="mb-2 flex items-baseline gap-2">
        <p className="text-sm font-semibold text-white">{plan.label} — target roster</p>
        <span className="text-xs text-slate-500">{plan.players.length} players</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-pg-border text-[10px] uppercase tracking-wider text-slate-500">
              <th className="py-1.5 pr-2 text-left">Pos</th>
              <th className="py-1.5 pr-2 text-left">Player</th>
              <th className="py-1.5 pr-2 text-right">$</th>
              <th className="py-1.5 pr-2 text-right">Max</th>
              {CATS.map((c) => (
                <th key={c} className="px-1 py-1.5 text-right">
                  {c}
                </th>
              ))}
              <th className="py-1.5 pl-2 text-right">Status</th>
            </tr>
          </thead>
          <tbody>
            {plan.players.map((p) => (
              <PlayerRowView
                key={p.player_key}
                player={p}
                owned={ownedKeys.has(p.player_key)}
                targeted={targetKeys.has(p.player_key)}
              />
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function PlayerRowView({
  player,
  owned,
  targeted,
}: {
  player: DraftPlayerRow
  owned: boolean
  targeted: boolean
}) {
  return (
    <tr className="border-b border-pg-border/60 font-mono text-xs">
      <td className="py-1.5 pr-2 text-slate-400">{player.pos ?? '—'}</td>
      <td className="py-1.5 pr-2 font-sans text-sm font-medium uppercase text-white">{player.player_key}</td>
      <td className="py-1.5 pr-2 text-right text-slate-300">{fmtBid(player.value)}</td>
      <td className="py-1.5 pr-2 text-right font-semibold" style={{ color: ACCENT }}>
        {fmtBid(player.max_bid)}
      </td>
      <td className="px-1 py-1.5 text-right text-slate-300">{fmtStat(player.pts)}</td>
      <td className="px-1 py-1.5 text-right text-slate-300">{fmtStat(player.reb)}</td>
      <td className="px-1 py-1.5 text-right text-slate-300">{fmtStat(player.ast)}</td>
      <td className="px-1 py-1.5 text-right text-slate-300">{fmtStat(player.stl)}</td>
      <td className="px-1 py-1.5 text-right text-slate-300">{fmtStat(player.blk)}</td>
      <td className="px-1 py-1.5 text-right text-slate-300">{fmtStat(player.tpm)}</td>
      <td className="px-1 py-1.5 text-right text-slate-300">{fmtPct(player.fg_pct)}</td>
      <td className="px-1 py-1.5 text-right text-slate-300">{fmtPct(player.ft_pct)}</td>
      <td className="px-1 py-1.5 text-right text-slate-300">{fmtStat(player.to)}</td>
      <td className="py-1.5 pl-2 text-right">
        {owned ? (
          <span className="rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-400">
            ✓ you
          </span>
        ) : targeted ? (
          <span
            className="rounded border px-1.5 py-0.5 text-[10px]"
            style={{ borderColor: ACCENT, backgroundColor: `${ACCENT}1a`, color: '#fbbf24' }}
          >
            ★ target
          </span>
        ) : (
          <span className="rounded border border-dashed border-pg-border px-1.5 py-0.5 text-[10px] text-slate-500">
            planned
          </span>
        )}
      </td>
    </tr>
  )
}

/* -------------------------------------------------------------------------- */
/* Rail: budget, value board, picks log                                       */
/* -------------------------------------------------------------------------- */

function BudgetCard({ spent, remaining, total }: { spent: number; remaining: number; total: number }) {
  const pct = total > 0 ? Math.min(100, (spent / total) * 100) : 0
  return (
    <Card>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">Budget</p>
      <div className="mt-1 flex items-baseline justify-between">
        <span className="font-mono text-2xl font-semibold text-white">{fmtBid(remaining)}</span>
        <span className="font-mono text-xs text-slate-500">of {fmtBid(total)}</span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-black/30">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, backgroundColor: ACCENT }} />
      </div>
    </Card>
  )
}

function ValueBoardCard({ rows }: { rows: DraftPlayerRow[] }) {
  return (
    <Card>
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        Best value on the board
      </p>
      <div className="divide-y divide-pg-border/60">
        {rows.slice(0, 8).map((r) => (
          <div key={r.player_key} className="flex items-center justify-between py-1.5 text-sm">
            <span className="uppercase text-slate-200">
              {r.player_key} <span className="ml-1 font-mono text-[10px] normal-case text-slate-500">{r.pos}</span>
            </span>
            <span className="font-mono text-xs text-slate-400">{fmtBid(r.value)}</span>
          </div>
        ))}
        {rows.length === 0 && <p className="py-2 text-xs text-slate-500">No data yet.</p>}
      </div>
    </Card>
  )
}

function PicksLogCard({
  picks,
  onUndo,
  pending,
}: {
  picks: DraftPickEntry[]
  onUndo: (index: number) => void
  pending: boolean
}) {
  return (
    <Card>
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Picks logged</p>
      <div className="divide-y divide-pg-border/60">
        {[...picks]
          .map((p, i) => ({ p, i }))
          .reverse()
          .map(({ p, i }) => (
            <div key={`${p.player_key}-${i}`} className="group flex items-start gap-2 py-1.5 text-sm">
              <span
                className="mt-1.5 h-1.5 w-1.5 flex-none rounded-full"
                style={{ backgroundColor: p.is_user ? ACCENT : '#64748b' }}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold uppercase text-slate-200" title={p.player_key}>
                  {p.player_key}
                </p>
                <p className="font-mono text-xs text-slate-500">
                  {fmtBid(p.price)} · {p.is_user ? 'you' : p.team_id}
                </p>
              </div>
              <button
                type="button"
                onClick={() => onUndo(i)}
                disabled={pending}
                title="Undo this pick"
                className="ml-1 rounded p-1 text-slate-500 opacity-0 transition-opacity hover:text-rose-400 group-hover:opacity-100 disabled:opacity-30"
              >
                <Undo2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        {picks.length === 0 && <p className="py-2 text-xs text-slate-500">No picks logged yet.</p>}
      </div>
    </Card>
  )
}
