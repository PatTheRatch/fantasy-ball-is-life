import { useMutation, useQuery } from '@tanstack/react-query'
import { Redo2, Search, Undo2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type {
  DraftPickEntry,
  DraftPlanSnapshot,
  DraftPlayerRow,
  DraftPoolParams,
  DraftPortfolioResponse,
  DraftRelaxProposal,
  DraftTriageResponse,
} from '../api'
import {
  formatApiError,
  getLeagueTeams,
  postDraftPick,
  postDraftPlans,
  postDraftRelax,
  postDraftTriage,
} from '../api'
import { Card } from '../components/Card'

/* -------------------------------------------------------------------------- */
/* Draft Room — docs/specs/DRAFT_ROOM.md. Scoped "data-dense terminal" look   */
/* (D3): amber accent + tabular numerals, layered on the app's existing dark  */
/* chrome (Card, pg-* tokens) rather than reskinning the whole product.       */
/* -------------------------------------------------------------------------- */

const ACCENT = '#e7a93c'
const CATS = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'FG%', 'FT%', 'TO'] as const

const STORAGE_KEY = 'draft-room-v1'
const SCHEMA_VERSION = 1

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
  const [triageResult, setTriageResult] = useState<DraftTriageResponse | null>(null)
  const [relaxProposal, setRelaxProposal] = useState<DraftRelaxProposal | null>(null)

  const [pickName, setPickName] = useState('')
  const [pickPrice, setPickPrice] = useState('')
  const [pickTeamId, setPickTeamId] = useState('you')

  // D12: same-device autosave, so an accidental refresh mid-draft loses nothing.
  useEffect(() => {
    const state: StoredState = { schemaVersion: SCHEMA_VERSION, picks, portfolio, activePlanId, params }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  }, [picks, portfolio, activePlanId, params])

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
      />

      {portfolio && (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
            <div className="space-y-4">
              <OnBlockCard
                onBlockKey={onBlockKey}
                setOnBlockKey={setOnBlockKey}
                onCheck={() => onBlockKey.trim() && triageMutation.mutate(onBlockKey.trim().toLowerCase())}
                pending={triageMutation.isPending}
                result={triageResult}
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

              <RosterTable plan={activePlan} ownedKeys={ownedKeys} />
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
}: {
  params: DraftPoolParams
  onChange: (p: DraftPoolParams) => void
  onGenerate: () => void
  pending: boolean
  error: string | null
  hasPortfolio: boolean
  pickCount: number
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
          onClick={onGenerate}
          disabled={pending}
          className="ml-auto rounded-lg px-4 py-2 text-sm font-semibold text-black transition-opacity disabled:opacity-50"
          style={{ backgroundColor: ACCENT }}
        >
          {pending ? 'Generating…' : hasPortfolio ? 'Regenerate portfolio' : 'Generate portfolio'}
        </button>
      </div>
      {pickCount > 0 && (
        <p className="mt-2 text-xs text-slate-500">{pickCount} pick(s) logged so far will be applied.</p>
      )}
      {error && <p className="mt-2 text-xs text-rose-400">{error}</p>}
    </Card>
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
/* On the block / triage (spec §2 criterion 3)                                */
/* -------------------------------------------------------------------------- */

function OnBlockCard({
  onBlockKey,
  setOnBlockKey,
  onCheck,
  pending,
  result,
}: {
  onBlockKey: string
  setOnBlockKey: (v: string) => void
  onCheck: () => void
  pending: boolean
  result: DraftTriageResponse | null
}) {
  return (
    <Card>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        On the block — you set who&apos;s up
      </p>
      <div className="mt-2 flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={onBlockKey}
            onChange={(e) => setOnBlockKey(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && onCheck()}
            placeholder="Player just nominated…"
            className="w-full rounded-md border border-pg-border bg-black/30 py-1.5 pl-8 pr-2 text-sm text-white focus:outline-none"
          />
        </div>
        <button
          type="button"
          onClick={onCheck}
          disabled={pending || !onBlockKey.trim()}
          className="rounded-md border border-pg-border px-3 py-1.5 text-sm font-semibold text-slate-200 hover:border-slate-500 disabled:opacity-50"
        >
          {pending ? '…' : 'Check'}
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
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={pickName}
          onChange={(e) => setPickName(e.target.value)}
          placeholder="Player name…"
          className="min-w-[10rem] flex-1 rounded-md border border-pg-border bg-black/30 px-2.5 py-1.5 text-sm text-white focus:outline-none"
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
          <p className="mt-1 text-lg font-bold text-white">Nominate {target.player_key}</p>
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
          <span className="font-semibold text-slate-200">{fallback.player_key}</span> ready · max{' '}
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

function RosterTable({ plan, ownedKeys }: { plan: DraftPlanSnapshot | null; ownedKeys: Set<string> }) {
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
              <PlayerRowView key={p.player_key} player={p} owned={ownedKeys.has(p.player_key)} />
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function PlayerRowView({ player, owned }: { player: DraftPlayerRow; owned: boolean }) {
  return (
    <tr className="border-b border-pg-border/60 font-mono text-xs">
      <td className="py-1.5 pr-2 text-slate-400">{player.pos ?? '—'}</td>
      <td className="py-1.5 pr-2 font-sans text-sm font-medium text-white">{player.player_key}</td>
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
            <span className="text-slate-200">
              {r.player_key} <span className="ml-1 font-mono text-[10px] text-slate-500">{r.pos}</span>
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
                <p className="truncate font-semibold text-slate-200" title={p.player_key}>
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
