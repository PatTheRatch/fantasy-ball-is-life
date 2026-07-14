import { ChevronDown, ChevronUp } from 'lucide-react'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getPublishedRecap, type RecapGeneratedContent } from '../api'
import { rankPillClass, rankPillEntries } from '../lib/inSeasonUtils'
import { AiTakeBadge } from './AiTakeBadge'

export function PowerRankingsTab({
  slug,
  season,
  week,
}: {
  slug: string
  season: number
  week: number
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['recap', 'published', slug, season, week],
    queryFn: () => getPublishedRecap(slug, season, week),
    retry: false,
  })

  if (isLoading) return <p className="text-slate-400">Loading power rankings…</p>

  if (error) {
    const status = (error as { response?: { status: number } })?.response?.status
    if (status === 404) {
      return <p className="text-slate-500">No rankings published for this week.</p>
    }
    return <p className="text-red-400">Could not load power rankings.</p>
  }

  const edition = data?.edition ?? null
  const snapshot = edition?.snapshot
  const content = edition?.structured_content_json

  if (!edition || !snapshot) {
    return <p className="text-slate-500">No rankings published for this week.</p>
  }

  const rankings = snapshot.power_rankings || []
  const standings = snapshot.standings || []

  if (rankings.length === 0) {
    return <p className="text-slate-500">No ranking data for this week.</p>
  }

  const standingMap: Record<string, { wins: number; losses: number; ties: number }> = {}
  for (const s of standings) {
    standingMap[String(s.team_id)] = {
      wins: Number(s.wins ?? 0),
      losses: Number(s.losses ?? 0),
      ties: Number(s.ties ?? 0),
    }
  }

  return (
    <div className="space-y-4 pb-8">
      <p className="text-xs text-slate-600">
        Rankings are algorithmic (all-play win rate, category dominance, recent form).
        AI explanations may reflect model opinion.
      </p>
      <div className="space-y-3">
        {rankings.map((row) => (
          <RankingCard
            key={String(row.team_id ?? '')}
            row={row as Record<string, unknown>}
            standing={standingMap[String(row.team_id)] ?? null}
            content={content ?? null}
          />
        ))}
      </div>
    </div>
  )
}

function movementArrow(change: unknown): string {
  const n = Number(change)
  if (!Number.isFinite(n) || n === 0) return '—'
  return n > 0 ? `▲${Math.abs(n)}` : `▼${Math.abs(n)}`
}

function movementColor(change: unknown): string {
  const n = Number(change)
  if (!Number.isFinite(n) || n === 0) return 'text-slate-500'
  return n > 0 ? 'text-emerald-400' : 'text-red-400'
}

function RankBadge({ rank }: { rank: unknown }) {
  const n = Number(rank)
  if (!Number.isFinite(n)) return null
  return (
    <span className="inline-flex h-8 w-8 items-center justify-center rounded-full bg-slate-800 text-sm font-bold text-white tabular-nums">
      {n}
    </span>
  )
}

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

  const explanation = ((content?.ranking_explanations) || []).find(
    (item) => item.team_id === row.team_id,
  )

  const record = standing
    ? `${standing.wins}–${standing.losses}${standing.ties ? `–${standing.ties}` : ''}`
    : '—'

  const team = String(row.team ?? '')

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-4 p-4 text-left"
      >
        <RankBadge rank={row.rank} />
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
          <span className={`text-sm font-semibold ${movementColor(row.rank_change)}`}>
            {movementArrow(row.rank_change)}
          </span>
        </div>
        {open ? (
          <ChevronUp className="h-5 w-5 flex-shrink-0 text-slate-500" />
        ) : (
          <ChevronDown className="h-5 w-5 flex-shrink-0 text-slate-500" />
        )}
      </button>
      {open && pills.length > 0 && (
        <div className="border-t border-slate-800 px-4 pb-4">
          <div className="flex flex-wrap gap-2 pt-3">
            {pills
              .sort((a, b) => a.rank - b.rank)
              .map((p) => (
                <span
                  key={p.label}
                  className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${rankPillClass(p.rank)}`}
                >
                  {p.label} #{p.rank}
                </span>
              ))}
          </div>
        </div>
      )}
    </div>
  )
}
