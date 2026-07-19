import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ArrowRight, Newspaper } from 'lucide-react'
import { getPublishedArchive, getSnapshot } from '../api'
import { useAuth } from '../lib/authContext'
import { getMyLeagues } from '../lib/memberships'
import { recapLeagueSlug } from '../lib/supabase'
import { MovementBadge } from '../ui'

const RECAP_SEASON = Number(import.meta.env.VITE_RECAP_SEASON ?? 2026)

type Row = Record<string, unknown>

/* ── Your matchup (above the fold) ──────────────────────────────────────── */

function MatchupCard({
  matchup,
  myTeam,
  matchupsPath,
  mine,
  claimHint,
}: {
  matchup: Row
  myTeam: string | null
  matchupsPath: string
  mine: boolean
  claimHint: boolean
}) {
  const home = String(matchup.home_team ?? '')
  const away = String(matchup.away_team ?? '')
  const homeWins = Number(matchup.home_category_wins ?? 0)
  const awayWins = Number(matchup.away_category_wins ?? 0)
  const homeGp = matchup.home_games_played
  const awayGp = matchup.away_games_played

  const side = (team: string, wins: number, gp: unknown) => (
    <div className="flex-1">
      <p
        className={`truncate font-semibold ${
          myTeam === team ? 'text-pg-accent' : 'text-white'
        }`}
      >
        {team}
        {myTeam === team && (
          <span className="ml-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-500">
            you
          </span>
        )}
      </p>
      <p className="mt-1 text-3xl font-black tabular-nums text-white">{wins}</p>
      {typeof gp === 'number' && (
        <p className="text-xs text-slate-500 tabular-nums">{gp} GP</p>
      )}
    </div>
  )

  return (
    <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400">
          {mine ? 'Your matchup' : 'This week'}
        </h2>
        <Link
          to={matchupsPath}
          className="flex items-center gap-1 text-xs font-semibold text-pg-accent hover:underline"
        >
          All matchups <ArrowRight className="h-3 w-3" aria-hidden />
        </Link>
      </div>
      <div className="flex items-center gap-4">
        {side(home, homeWins, homeGp)}
        <span className="text-sm font-bold text-slate-600">vs</span>
        {side(away, awayWins, awayGp)}
      </div>
      {claimHint && (
        <p className="mt-3 border-t border-pg-border pt-3 text-sm text-slate-400">
          <Link to="/settings" className="font-semibold text-pg-accent">
            Claim your team in Settings
          </Link>{' '}
          to pin your own matchup here.
        </p>
      )}
    </section>
  )
}

/* ── Below the fold: movers · recap · transactions ──────────────────────── */

function Movers({ rankings }: { rankings: Row[] }) {
  const movers = rankings
    .filter((r) => Number(r.rank_change) !== 0 && r.rank_change != null)
    .sort((a, b) => Math.abs(Number(b.rank_change)) - Math.abs(Number(a.rank_change)))
    .slice(0, 3)
  return (
    <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
      <h2 className="mb-3 text-sm font-bold uppercase tracking-wider text-slate-400">
        Ranking movers
      </h2>
      {movers.length === 0 ? (
        <p className="text-sm text-slate-500">No movement this week.</p>
      ) : (
        <ul className="space-y-2">
          {movers.map((r) => (
            <li
              key={String(r.team_id ?? r.team)}
              className="flex items-center justify-between gap-2"
            >
              <span className="truncate text-sm text-slate-200">
                <span className="mr-2 tabular-nums text-slate-500">
                  #{String(r.rank ?? '—')}
                </span>
                {String(r.team ?? '')}
              </span>
              <MovementBadge change={Number(r.rank_change)} />
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function RecapCard({
  headline,
  newsroomPath,
}: {
  headline: string | null
  newsroomPath: string
}) {
  return (
    <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
      <h2 className="mb-3 text-sm font-bold uppercase tracking-wider text-slate-400">
        Latest recap
      </h2>
      {headline ? (
        <Link to={newsroomPath} className="group block">
          <p className="font-bold leading-snug text-white group-hover:text-pg-accent">
            {headline}
          </p>
          <p className="mt-2 flex items-center gap-1 text-xs font-semibold text-pg-accent">
            <Newspaper className="h-3 w-3" aria-hidden /> Read in the newsroom
          </p>
        </Link>
      ) : (
        <p className="text-sm text-slate-500">No recap published yet.</p>
      )}
    </section>
  )
}

function TransactionTicker({ transactions }: { transactions: Row[] }) {
  const recent = [...transactions]
    .sort((a, b) => String(b.date ?? '').localeCompare(String(a.date ?? '')))
    .slice(0, 5)
  return (
    <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
      <h2 className="mb-3 text-sm font-bold uppercase tracking-wider text-slate-400">
        Recent moves
      </h2>
      {recent.length === 0 ? (
        <p className="text-sm text-slate-500">No transactions this week.</p>
      ) : (
        <ul className="space-y-2">
          {recent.map((t, i) => (
            <li key={i} className="text-sm text-slate-300">
              <span className="font-medium text-white">
                {String(t.team_name ?? '')}
              </span>
              <span className="ml-2 text-xs text-slate-500">
                {String(t.date ?? '').slice(0, 10)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

/* ── League Home ────────────────────────────────────────────────────────── */

/**
 * P-6b: League Home (spec §8) — the app's default league surface at
 * `/leagues/:slug`. Everything auto-loads from P-3 snapshots on mount;
 * there are no manual "Load" buttons here by design (D-P6).
 */
export function LeagueHome() {
  const { slug } = useParams<{ slug: string }>()
  const effectiveSlug = slug || recapLeagueSlug
  const season = RECAP_SEASON
  const { session, user } = useAuth()

  const archiveQuery = useQuery({
    queryKey: ['standings-page', 'archive', effectiveSlug, season],
    queryFn: () => getPublishedArchive(effectiveSlug, season),
    retry: false,
  })
  const archive = archiveQuery.data
  const latest = archive && archive.length > 0 ? archive[archive.length - 1] : null
  const week = latest?.week ?? 1

  const snapshotQuery = useQuery({
    queryKey: ['recap', 'snapshot', effectiveSlug, season, week],
    queryFn: () => getSnapshot(effectiveSlug, season, week),
    enabled: !archiveQuery.isLoading,
    retry: false,
  })

  const membershipsQuery = useQuery({
    queryKey: ['my-leagues', user?.id],
    queryFn: () => getMyLeagues(user!.id),
    enabled: Boolean(session && user),
    retry: false,
  })

  if (archiveQuery.isLoading || snapshotQuery.isLoading) {
    return (
      <div className="flex min-h-[200px] items-center justify-center">
        <p className="text-slate-400">Loading league…</p>
      </div>
    )
  }

  const snapshot = (snapshotQuery.data?.snapshot ?? {}) as Row
  const matchups = (Array.isArray(snapshot.matchups) ? snapshot.matchups : []) as Row[]
  const rankings = (Array.isArray(snapshot.power_rankings) ? snapshot.power_rankings : []) as Row[]
  const transactions = (Array.isArray(snapshot.transactions) ? snapshot.transactions : []) as Row[]
  const roundLabel = (snapshot.playoff_context as Row | undefined)?.round_label

  const myTeam =
    membershipsQuery.data?.find((l) => l.slug === effectiveSlug)?.teamName ?? null
  const myMatchup = myTeam
    ? matchups.find(
        (m) => m.home_team === myTeam || m.away_team === myTeam,
      ) ?? null
    : null
  const featured = myMatchup ?? matchups[0] ?? null

  const newsroomPath = `/leagues/${effectiveSlug}/newsroom/${season}/${week}`
  const matchupsPath = `/leagues/${effectiveSlug}/matchups/${week}`

  return (
    <div className="space-y-4 pb-8">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-2xl font-bold text-white">League Home</h1>
        <p className="text-sm font-semibold text-slate-400">
          Week {week}
          {roundLabel ? (
            <span className="ml-2 text-amber-400">{String(roundLabel)}</span>
          ) : null}
        </p>
      </header>

      {featured ? (
        <MatchupCard
          matchup={featured}
          myTeam={myTeam}
          matchupsPath={matchupsPath}
          mine={myMatchup !== null}
          claimHint={Boolean(session) && myMatchup === null}
        />
      ) : (
        <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
          <p className="text-sm text-slate-500">
            No matchup data yet — check back once the week is underway.
          </p>
        </section>
      )}

      <div className="grid gap-4 md:grid-cols-3">
        <Movers rankings={rankings} />
        <RecapCard headline={latest?.headline ?? null} newsroomPath={newsroomPath} />
        <TransactionTicker transactions={transactions} />
      </div>
    </div>
  )
}
