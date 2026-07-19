import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import type {
  CustomPlanSpec,
  DraftPickEntry,
  DraftPlanSnapshot,
  DraftPortfolioResponse,
  DraftPoolParams,
  DraftRelaxProposal,
  DraftTriageResponse,
} from '../api'
import {
  formatApiError,
  getLeagueSettings,
  getLeagueTeams,
  postDraftCustomPlan,
  postDraftPick,
  postDraftPlans,
  postDraftRelax,
  postDraftTriage,
} from '../api'
import { ProjectionBadge } from '../components/ProjectionBadge'
import { Board } from '../draft/Board'
import { ControlsSheet } from '../draft/ControlsSheet'
import {
  PRESETS_STORAGE_KEY,
  SCHEMA_VERSION,
  STORAGE_KEY,
} from '../draft/constants'
import { CustomPlanCard } from '../draft/CustomPlanCard'
import { firstAlive } from '../draft/formatters'
import { PlanRail } from '../draft/PlanRail'
import { SetupPanel } from '../draft/SetupPanel'
import { loadPresets, loadStored } from '../draft/storage'
import type { StoredState } from '../draft/types'

export function DraftPage() {
  const [picks, setPicks] = useState<DraftPickEntry[]>(() => loadStored().picks)
  const [portfolio, setPortfolio] = useState<DraftPortfolioResponse | null>(
    () => loadStored().portfolio,
  )
  const [activePlanId, setActivePlanId] = useState<string | null>(
    () => loadStored().activePlanId,
  )
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
  const [advancedOpen, setAdvancedOpen] = useState(false)

  useEffect(() => {
    const state: StoredState = {
      schemaVersion: SCHEMA_VERSION,
      picks,
      portfolio,
      activePlanId,
      params,
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  }, [picks, portfolio, activePlanId, params])

  useEffect(() => {
    localStorage.setItem(PRESETS_STORAGE_KEY, JSON.stringify(presets))
  }, [presets])

  const teamsQuery = useQuery({
    queryKey: ['draft', 'teams'],
    queryFn: getLeagueTeams,
    retry: 0,
  })

  const leagueSettingsQuery = useQuery({
    queryKey: ['draft', 'league-settings'],
    queryFn: getLeagueSettings,
    retry: 0,
  })

  const generateMutation = useMutation({
    mutationFn: () => postDraftPlans({ ...params, picks }),
    onSuccess: (data) => {
      setPortfolio(data)
      setActivePlanId(
        data.fallback_next?.plan_id ?? firstAlive(data.plans)?.plan_id ?? null,
      )
      setRelaxProposal(null)
      setTriageResult(null)
    },
  })

  const customPlanMutation = useMutation({
    mutationFn: (spec: CustomPlanSpec) =>
      postDraftCustomPlan({ ...params, ...spec, picks }),
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
          fallback_next:
            base.fallback_next ?? {
              plan_id: data.plan.plan_id,
              label: data.plan.label,
              player_key: data.plan.next_target?.player_key ?? null,
              max_bid: data.plan.next_target?.max_bid ?? null,
            },
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
      return postDraftPick({
        ...params,
        picks: newPicks,
        new_pick: newPick,
        prior_plans: portfolio.plans,
      }).then((data) => ({ data, newPicks }))
    },
    onSuccess: ({ data, newPicks }) => {
      setPicks(newPicks)
      setPortfolio(data)
      setActivePlanId((prev) => {
        const stillAlive = data.plans.find(
          (p) => p.plan_id === prev && p.health === 'alive',
        )
        return (
          stillAlive?.plan_id ??
          data.fallback_next?.plan_id ??
          firstAlive(data.plans)?.plan_id ??
          null
        )
      })
      setRelaxProposal(null)
      setPickName('')
      setPickPrice('')
      setOnBlockKey('')
      setOnBlockPrice('')
      setTriageResult(null)
    },
  })

  const undoMutation = useMutation({
    mutationFn: (index: number) => {
      const newPicks = picks.filter((_, i) => i !== index)
      return postDraftPlans({ ...params, picks: newPicks }).then((data) => ({
        data,
        newPicks,
      }))
    },
    onSuccess: ({ data, newPicks }) => {
      setPicks(newPicks)
      setPortfolio(data)
      setActivePlanId(
        data.fallback_next?.plan_id ?? firstAlive(data.plans)?.plan_id ?? null,
      )
      setRelaxProposal(null)
    },
  })

  const triageMutation = useMutation({
    mutationFn: (playerKey: string) => {
      if (!portfolio) throw new Error('Generate a portfolio first.')
      return postDraftTriage({
        ...params,
        picks,
        prior_plans: portfolio.plans,
        player_key: playerKey,
      })
    },
    onSuccess: (data) => setTriageResult(data),
  })

  const relaxMutation = useMutation({
    mutationFn: () => {
      if (!portfolio) throw new Error('Generate a portfolio first.')
      return postDraftRelax({
        ...params,
        picks,
        prior_plans: portfolio.plans,
        plan_id: activePlanId,
      })
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
    const nextPlans = portfolio.plans.map((p) =>
      p.plan_id === cleaned.plan_id ? cleaned : p,
    )
    setPortfolio({ ...portfolio, plans: nextPlans })
    setActivePlanId(cleaned.plan_id)
    setRelaxProposal(null)
  }

  function submitPick() {
    const key = pickName.trim().toLowerCase()
    const price = Number(pickPrice)
    if (!key || Number.isNaN(price)) return
    const isUser = pickTeamId === 'you'
    logPickMutation.mutate({
      player_key: key,
      price,
      team_id: pickTeamId,
      is_user: isUser,
    })
  }

  function submitOnBlockPick() {
    const key = onBlockKey.trim().toLowerCase()
    const price = Number(onBlockPrice)
    if (!key || Number.isNaN(price)) return
    const isUser = onBlockTeamId === 'you'
    logPickMutation.mutate({
      player_key: key,
      price,
      team_id: onBlockTeamId,
      is_user: isUser,
    })
  }

  return (
    <div className="space-y-4" style={{ fontVariantNumeric: 'tabular-nums' }}>
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-white md:text-3xl">
          Draft Room
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Build and pivot your target roster live, against the real optimizer.
        </p>
        <div className="mt-2">
          <ProjectionBadge horizon="season" />
        </div>
      </div>

      <SetupPanel
        params={params}
        onChange={setParams}
        onGenerate={() => generateMutation.mutate()}
        pending={generateMutation.isPending}
        error={
          generateMutation.isError ? formatApiError(generateMutation.error) : null
        }
        hasPortfolio={portfolio != null}
        pickCount={picks.length}
        skippedTargets={portfolio?.skipped_targets ?? []}
        onOpenAdvanced={() => setAdvancedOpen(true)}
      />

      <ControlsSheet
        open={advancedOpen}
        onClose={() => setAdvancedOpen(false)}
        params={params}
        onChange={setParams}
        leagueTeamCount={leagueSettingsQuery.data?.team_count ?? null}
      />

      <CustomPlanCard
        presets={presets}
        onDeletePreset={deletePreset}
        onSolve={(spec) => customPlanMutation.mutate(spec)}
        pending={customPlanMutation.isPending}
        error={
          customPlanMutation.isError
            ? formatApiError(customPlanMutation.error)
            : null
        }
      />

      {portfolio && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-[1fr_320px]">
          <Board
            onBlockKey={onBlockKey}
            setOnBlockKey={setOnBlockKey}
            onCheck={() =>
              onBlockKey.trim() &&
              triageMutation.mutate(onBlockKey.trim().toLowerCase())
            }
            checkPending={triageMutation.isPending}
            triageResult={triageResult}
            onBlockPrice={onBlockPrice}
            setOnBlockPrice={setOnBlockPrice}
            onBlockTeamId={onBlockTeamId}
            setOnBlockTeamId={setOnBlockTeamId}
            teams={(teamsQuery.data ?? []) as Record<string, unknown>[]}
            onLogOnBlockPick={submitOnBlockPick}
            logPending={logPickMutation.isPending}
            logError={
              logPickMutation.isError
                ? formatApiError(logPickMutation.error)
                : null
            }
            pickName={pickName}
            setPickName={setPickName}
            pickPrice={pickPrice}
            setPickPrice={setPickPrice}
            pickTeamId={pickTeamId}
            setPickTeamId={setPickTeamId}
            onSubmitPick={submitPick}
            activePlan={activePlan}
            fallbackNext={portfolio.fallback_next}
            everyPlanBroken={everyPlanBroken}
            relaxProposal={relaxProposal}
            onRelax={() => relaxMutation.mutate()}
            onAcceptRelax={acceptRelaxProposal}
            relaxPending={relaxMutation.isPending}
            relaxError={
              relaxMutation.isError ? formatApiError(relaxMutation.error) : null
            }
            plans={portfolio.plans}
            activePlanId={activePlanId}
            onSelectPlan={setActivePlanId}
            ownedKeys={ownedKeys}
            targetKeys={targetKeys}
          />
          <PlanRail
            budgetSpent={budgetSpent}
            budgetRemaining={budgetRemaining}
            budgetTotal={params.initial_budget ?? 200}
            valueBoardRows={portfolio.value_board}
            picks={picks}
            onUndoPick={(i) => undoMutation.mutate(i)}
            undoPending={undoMutation.isPending}
          />
        </div>
      )}
    </div>
  )
}
