import { useQuery } from '@tanstack/react-query'
import {
  Award,
  Zap,
  Camera,
  TrendingDown,
  TrendingUp,
  RefreshCw,
  ArrowUpDown,
  Trophy,
} from 'lucide-react'
import { getSnapshot, getPublishedRecap } from '../api'
import { AiTakeBadge } from './AiTakeBadge'

// ── per-award_id presentation map ──────────────────────────────────

interface AwardPresentation {
  icon: React.FC<{ className?: string }>
  factLine: (facts: Record<string, unknown>) => string
}

const PRESENTATION: Record<string, AwardPresentation> = {
  'team-of-the-week': {
    icon: Trophy,
    factLine: (f) =>
      `beat ${f.matchup_wins ?? '?'} of the field (${f.total_wins ?? '?'} total cat-wins)`,
  },
  'blowout-of-the-week': {
    icon: Zap,
    factLine: (f) =>
      `by a ${f.margin ?? '?'}-category margin over ${f.opponent ?? 'opponent'}`,
  },
  'photo-finish': {
    icon: Camera,
    factLine: (f) =>
      `by a ${f.margin ?? '?'}-category margin over ${f.opponent ?? 'opponent'}`,
  },
  'biggest-upset': {
    icon: ArrowUpDown,
    factLine: (f) => `upset by ${f.rank_gap ?? '?'} ranking spots`,
  },
  'luckiest-team': {
    icon: TrendingUp,
    factLine: (f) => `luck ratio: ${f.luck_ratio ?? '?'}`,
  },
  'unluckiest-team': {
    icon: TrendingDown,
    factLine: (f) => `luck ratio: ${f.luck_ratio ?? '?'}`,
  },
  'stock-rising': {
    icon: TrendingUp,
    factLine: (f) => `climbed ${f.places ?? '?'} spots`,
  },
  'falling-fast': {
    icon: TrendingDown,
    factLine: (f) => `dropped ${f.places ?? '?'} spots`,
  },
  'transaction-addict': {
    icon: RefreshCw,
    factLine: (f) => `${f.transaction_count ?? '?'} moves this week`,
  },
}

// ── helpers ─────────────────────────────────────────────────────────

function resolvePresentation(
  awardId: string,
): AwardPresentation {
  return (
    PRESENTATION[awardId] ?? {
      icon: Award,
      factLine: (f) =>
        Object.entries(f)
          .map(([k, v]) => `${k}: ${v}`)
          .join(' · ') || '',
    }
  )
}

// ── card ────────────────────────────────────────────────────────────

function AwardCard({
  award,
  explanation,
}: {
  award: Record<string, unknown>
  explanation?: string | null
}) {
  const awardId = String(award.award_id ?? '')
  const title = String(award.title ?? awardId)
  const winner = String(award.winner ?? '—')
  const facts = (award.facts ?? {}) as Record<string, unknown>
  const pres = resolvePresentation(awardId)
  const Icon = pres.icon

  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-900/60 p-4">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 shrink-0 text-amber-400">
          <Icon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold text-amber-300">{title}</div>
          <div className="mt-0.5 text-base font-bold text-white">{winner}</div>
          <div className="mt-1 text-xs text-slate-400">{pres.factLine(facts)}</div>
          {explanation ? (
            <div className="mt-2 flex items-start gap-1.5">
              <AiTakeBadge />
              <p className="text-xs leading-relaxed text-slate-300">
                {explanation}
              </p>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

// ── tab ─────────────────────────────────────────────────────────────

export function AwardsTab({
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

  if (snapshotQuery.isLoading) return <p className="text-slate-400">Loading awards…</p>
  if (snapshotQuery.error) {
    const status = (snapshotQuery.error as { response?: { status: number } })?.response?.status
    if (status === 404) return <p className="text-slate-500">No awards data for this week.</p>
    return <p className="text-red-400">Could not load awards.</p>
  }

  const snapshot = snapshotQuery.data?.snapshot as Record<string, unknown> | undefined
  const content = recapQuery.data?.edition?.structured_content_json as Record<string, unknown> | undefined

  if (!snapshot) {
    return <p className="text-slate-500">No awards data for this week.</p>
  }

  const awards = (snapshot.award_candidates ?? []) as Record<string, unknown>[]
  if (!Array.isArray(awards) || awards.length === 0) {
    return (
      <div className="flex min-h-[120px] items-center justify-center rounded-2xl border border-dashed border-slate-700 bg-slate-900/40 p-8">
        <p className="text-center text-slate-500">
          <Trophy className="mx-auto mb-2 h-8 w-8 opacity-30" />
          No awards this week
        </p>
      </div>
    )
  }

  // Build explanation lookup by award_id
  const explanations: Record<string, string> = {}
  const rawExplanations = (content?.award_explanations ?? []) as Record<string, unknown>[]
  for (const e of rawExplanations) {
    explanations[String(e.award_id ?? '')] = String(e.text ?? '')
  }

  return (
    <div className="space-y-4 pb-8">
      <p className="text-xs text-slate-600">
        Awards are computed from matchup results. AI flavor text may reflect model opinion.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        {awards.map((award) => (
          <AwardCard
            key={String(award.award_id ?? '')}
            award={award}
            explanation={explanations[String(award.award_id ?? '')] ?? null}
          />
        ))}
      </div>
    </div>
  )
}
