import { Redo2 } from 'lucide-react'
import type {
  DraftFallbackNext,
  DraftPlanSnapshot,
  DraftPlayerRow,
  DraftRelaxProposal,
  DraftTriageResponse,
} from '../api'
import { Card } from '../components/Card'
import { ACCENT, CATS } from './constants'
import { fmtBid, fmtPct, fmtStat, healthPillClass } from './formatters'
import { PlayerSearch } from './shared/PlayerSearch'

export function OnBlockCard({
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

export function AddPickCard({
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

export function NextMoveCard({
  activePlan,
  fallback,
}: {
  activePlan: DraftPlanSnapshot | null
  fallback: DraftFallbackNext | null
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

export function RelaxCard({
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

export function PivotPlansStrip({
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

export function RosterTable({
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

export function PlayerRowView({
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

export function Board(props: {
  onBlockKey: string
  setOnBlockKey: (v: string) => void
  onCheck: () => void
  checkPending: boolean
  triageResult: DraftTriageResponse | null
  onBlockPrice: string
  setOnBlockPrice: (v: string) => void
  onBlockTeamId: string
  setOnBlockTeamId: (v: string) => void
  teams: Record<string, unknown>[]
  onLogOnBlockPick: () => void
  logPending: boolean
  logError: string | null
  pickName: string
  setPickName: (v: string) => void
  pickPrice: string
  setPickPrice: (v: string) => void
  pickTeamId: string
  setPickTeamId: (v: string) => void
  onSubmitPick: () => void
  activePlan: DraftPlanSnapshot | null
  fallbackNext: DraftFallbackNext | null | undefined
  everyPlanBroken: boolean
  relaxProposal: DraftRelaxProposal | null
  onRelax: () => void
  onAcceptRelax: () => void
  relaxPending: boolean
  relaxError: string | null
  plans: DraftPlanSnapshot[]
  activePlanId: string | null
  onSelectPlan: (id: string) => void
  ownedKeys: Set<string>
  targetKeys: Set<string>
}) {
  const {
    onBlockKey, setOnBlockKey, onCheck, checkPending, triageResult,
    onBlockPrice, setOnBlockPrice, onBlockTeamId, setOnBlockTeamId,
    teams, onLogOnBlockPick, logPending, logError,
    pickName, setPickName, pickPrice, setPickPrice, pickTeamId, setPickTeamId,
    onSubmitPick, activePlan, fallbackNext, everyPlanBroken,
    relaxProposal, onRelax, onAcceptRelax, relaxPending, relaxError,
    plans, activePlanId, onSelectPlan, ownedKeys, targetKeys,
  } = props

  return (
    <div className="space-y-4">
      <OnBlockCard
        onBlockKey={onBlockKey}
        setOnBlockKey={setOnBlockKey}
        onCheck={onCheck}
        checkPending={checkPending}
        result={triageResult}
        price={onBlockPrice}
        setPrice={setOnBlockPrice}
        teamId={onBlockTeamId}
        setTeamId={setOnBlockTeamId}
        teams={teams}
        onLogPick={onLogOnBlockPick}
        logPending={logPending}
        logError={logError}
      />
      <AddPickCard
        pickName={pickName}
        setPickName={setPickName}
        pickPrice={pickPrice}
        setPickPrice={setPickPrice}
        pickTeamId={pickTeamId}
        setPickTeamId={setPickTeamId}
        teams={teams}
        onSubmit={onSubmitPick}
        pending={logPending}
        error={logError}
      />
      <NextMoveCard activePlan={activePlan} fallback={fallbackNext ?? null} />
      {everyPlanBroken && (
        <RelaxCard
          proposal={relaxProposal}
          onRelax={onRelax}
          onAccept={onAcceptRelax}
          pending={relaxPending}
          error={relaxError}
        />
      )}
      <PivotPlansStrip plans={plans} activePlanId={activePlanId} onSelect={onSelectPlan} />
      <RosterTable plan={activePlan} ownedKeys={ownedKeys} targetKeys={targetKeys} />
    </div>
  )
}
