import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getSnapshot, getPublishedRecap, type RecapGeneratedContent } from '../api'
import {
  Card,
  StateBlock,
  inferStateBlock,
  AiTakeBadge,
  RankPill,
  MovementBadge,
} from '../ui'

const normTeam = (name: unknown) => String(name ?? '').trim().toLowerCase()

/* ── Move from rankPillClass / rankPillEntries (inSeasonUtils) ──── */

function rankPillEntries(row: Record<string, unknown>): { label: string; rank: number }[] {
  const statKeys: [string, string][] = [
    ['pts_rank', 'PTS'], ['reb_rank', 'REB'], ['ast_rank', 'AST'],
    ['stl_rank', 'STL'], ['blk_rank', 'BLK'], ['3pm_rank', '3PM'],
    ['fg_pct_rank', 'FG%'], ['ft_pct_rank', 'FT%'], ['to_rank', 'TO'],
  ]
  return statKeys
    .map(([key, label]) => {
      const r = Number(row[key])
      return Number.isFinite(r) ? { label, rank: r } : null
    })
    .filter((x): x is { label: string; rank: number } => x !== null)
}

/* ── main component ──────────────────────────────────────────────── */

export function PowerRankingsTab({
  slug,
  season,
  week,
}: {
  slug: string
  season: number
  week: number
}) {
  const snapshotQuery = useQuery({
    queryKey: ['recap', 'snapshot', slug, season, week],
    queryFn: () => getSnapshot(slug, season, week),
    retry: false,
  })

  const recapQuery = useQuery({
    queryKey: ['recap', 'published', slug, season, week],
    queryFn: () => getPublishedRecap(slug, season, week),
    retry: false,
  })

  const stateBlock = inferStateBlock({
    isLoading: snapshotQuery.isLoading,
    isError: snapshotQuery.isError,
    error: snapshotQuery.error,
    data: snapshotQuery.data?.snapshot,
    isEmpty: (d) => {
      if (!d) return true
      const rankings = (d as Record<string, unknown>).power_rankings
      return !Array.isArray(rankings) || rankings.length === 0
    },
  })

  if (stateBlock.show) {
    return <StateBlock {...stateBlock} />
  }

  const snapshot = snapshotQuery.data!.snapshot as Record<string, unknown>
  const content = recapQuery.data?.edition?.structured_content_json
  const rankings = (snapshot.power_rankings as Record<string, unknown>[]) || []
  const standings = (snapshot.standings as Record<string, unknown>[]) || []

  const standingMap: Record<string, { wins: number; losses: number; ties: number }> = {}
  for (const s of standings) {
    standingMap[String(s.team_name)] = {
      wins: Number(s.wins ?? 0),
      losses: Number(s.losses ?? 0),
      ties: Number(s.ties ?? 0),
    }
  }

  return (
    <div className="space-y-4 pb-8">
      <p className="text-xs text-slate-500">
        Rankings are algorithmic (all-play win rate, category dominance, recent form).
        Team blurbs are AI-written and may reflect model opinion.
      </p>
      <div className="space-y-3">
        {rankings.map((row) => (
          <RankingCard
            key={String(row.team_id ?? '')}
            row={row as Record<string, unknown>}
            standing={standingMap[String(row.team)] ?? null}
            content={content ?? null}
          />
        ))}
      </div>
    </div>
  )
}

/* ── Rank badge (numeric circle) ─────────────────────────────────── */

function RankCircle({ rank }: { rank: unknown }) {
  const n = Number(rank)
  if (!Number.isFinite(n)) return null
  return (
    <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-slate-800 text-sm font-bold text-white tabular-nums">
      {n}
    </span>
  )
}

/* ── ranking card ────────────────────────────────────────────────── */

function RankingCard({
  row,
  standing,
  content,
}: {
  row: Record<string, unknown>
  standing: { wins: number; losses: number; ties: number } | null
  content: RecapGeneratedContent | null
}) {
  const [open, setOpen] = useState(false)
  const pills = rankPillEntries(row)

  const explanations = (content?.ranking_explanations ?? []) as { team: string; text: string }[]
  const explanation = explanations.find(
    (item) => normTeam(item.team) === normTeam(row.team),
  )

  const record = standing
    ? `${standing.wins}–${standing.losses}${standing.ties ? `–${standing.ties}` : ''}`
    : '—'

  const team = String(row.team ?? '')
  const rankChange = Number(row.rank_change) || 0

  return (
    <Card variant="default">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-4 p-4 text-left"
      >
        <RankCircle rank={row.rank} />
        <div className="min-w-0 flex-1">
          <p className="font-bold text-white">{team}</p>
          <p className="text-sm text-slate-400">
            {record} · All-play {Number(row.allplay_win_pct ?? 0).toFixed(0)}%
            {row.recent_allplay_win_pct != null
              ? ` (recent ${Number(row.recent_allplay_win_pct).toFixed(0)}%)`
              : ''}
          </p>
          {explanation?.text && (
            <p className="mt-1 text-sm leading-relaxed text-slate-300">
              {explanation.text}
              <AiTakeBadge />
            </p>
          )}
        </div>
        <div className="flex flex-col items-end gap-1">
          <MovementBadge change={rankChange} />
        </div>
        {open ? (
          <ChevronUp className="h-5 w-5 flex-shrink-0 text-slate-500" />
        ) : (
          <ChevronDown className="h-5 w-5 flex-shrink-0 text-slate-500" />
        )}
      </button>
      {open && pills.length > 0 && (
        <div className="border-t border-pg-border px-4 pb-4">
          <div className="flex flex-wrap gap-2 pt-3">
            {pills
              .sort((a, b) => a.rank - b.rank)
              .map((p) => (
                <RankPill key={p.label} label={p.label} rank={p.rank} />
              ))}
          </div>
        </div>
      )}
    </Card>
  )
}
