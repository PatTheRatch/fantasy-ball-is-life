import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ArrowRight, ChevronDown, ChevronUp, Newspaper, Star } from 'lucide-react'
import { useState } from 'react'
import { getPublishedArchive, getSnapshot } from '../api'
import { useAuth } from '../lib/authContext'
import { getMyLeagues } from '../lib/memberships'
import { recapLeagueSlug, supabase } from '../lib/supabase'
import { formatStatValue, STAT_ORDER } from '../lib/inSeasonUtils'
import { MovementBadge } from '../ui'
import { JoinLeague } from '../components/JoinLeague'

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
  const [open, setOpen] = useState(false)
  const home = String(matchup.home_team ?? '')
  const away = String(matchup.away_team ?? '')
  const homeWins = Number(matchup.home_category_wins ?? 0)
  const awayWins = Number(matchup.away_category_wins ?? 0)
  const homeGp = matchup.home_games_played
  const awayGp = matchup.away_games_played
  const categories = (Array.isArray(matchup.categories) ? matchup.categories : []) as Row[]

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
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-4 text-left"
      >
        {side(home, homeWins, homeGp)}
        <span className="text-sm font-bold text-slate-600">vs</span>
        {side(away, awayWins, awayGp)}
        {categories.length > 0 && (
          <span className="ml-auto flex-shrink-0 text-slate-500">
            {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </span>
        )}
      </button>
      {open && categories.length > 0 && (
        <div className="mt-4 overflow-x-auto border-t border-pg-border pt-4">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-700 text-slate-500">
                <th className="pb-1 font-medium">Category</th>
                <th className="pb-1 pr-2 text-right font-medium">Home</th>
                <th className="pb-1 text-right font-medium">Away</th>
                <th className="pb-1 text-center font-medium">Edge</th>
              </tr>
            </thead>
            <tbody>
              {STAT_ORDER.map((stat) => {
                const r = categories.find((c) => String(c.stat) === stat)
                if (!r) {
                  return (
                    <tr key={stat} className="border-b border-slate-800/50">
                      <td className="py-1.5 text-slate-400">{stat}</td>
                      <td className="py-1.5 pr-2 text-right text-slate-600">—</td>
                      <td className="py-1.5 text-right text-slate-600">—</td>
                      <td className="py-1.5 text-center text-slate-600">—</td>
                    </tr>
                  )
                }
                const hVal = formatStatValue(stat, r.home_value)
                const aVal = formatStatValue(stat, r.away_value)
                const w = String(r.winner ?? '')
                const complete = r.complete !== false && w !== 'unavailable'
                return (
                  <tr
                    key={stat}
                    className={`border-b border-slate-800/50 ${!complete ? 'opacity-40' : ''}`}
                  >
                    <td className="py-1.5 font-medium text-slate-300">{stat}</td>
                    <td
                      className={`py-1.5 pr-2 text-right tabular-nums ${
                        w === 'home' ? 'font-bold text-emerald-400' : 'text-slate-400'
                      }`}
                    >
                      {complete ? hVal : '—'}
                    </td>
                    <td
                      className={`py-1.5 text-right tabular-nums ${
                        w === 'away' ? 'font-bold text-emerald-400' : 'text-slate-400'
                      }`}
                    >
                      {complete ? aVal : '—'}
                    </td>
                    <td className="py-1.5 text-center">
                      {w === 'home' ? (
                        <span className="text-emerald-500">H</span>
                      ) : w === 'away' ? (
                        <span className="text-emerald-500">A</span>
                      ) : w === 'tie' ? (
                        <span className="text-slate-500">T</span>
                      ) : null}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
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

/* ── Below the fold: movers · recap · transactions · standings ──────────── */

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
    .filter((t) => String(t.action_type ?? '').toUpperCase() === 'ADD')
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
              </span>{' '}
              added{' '}
              <span className="font-medium text-pg-accent">
                {String(t.player ?? '')}
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

function StandingsCard({
  standings,
  standingsPath,
}: {
  standings: Row[]
  standingsPath: string
}) {
  const top5 = [...standings]
    .sort((a, b) => Number(a.standing ?? 99) - Number(b.standing ?? 99))
    .slice(0, 5)
  return (
    <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-bold uppercase tracking-wider text-slate-400">
          Standings
        </h2>
        <Link
          to={standingsPath}
          className="flex items-center gap-1 text-xs font-semibold text-pg-accent hover:underline"
        >
          Full standings <ArrowRight className="h-3 w-3" aria-hidden />
        </Link>
      </div>
      {top5.length === 0 ? (
        <p className="text-sm text-slate-500">No standings data yet.</p>
      ) : (
        <ul className="space-y-1.5">
          {top5.map((r) => (
            <li
              key={`${r.standing ?? ''}-${r.team_name ?? ''}`}
              className="flex items-center gap-2 text-sm"
            >
              <span className="w-5 text-right tabular-nums text-slate-500">
                {String(r.standing ?? '—')}
              </span>
              <span className="truncate text-slate-200">
                {String(r.team_name ?? '')}
                {r.in_playoffs === true && (
                  <Star className="ml-1 inline-block h-3 w-3 text-amber-400" aria-label="playoffs" />
                )}
              </span>
              <span className="ml-auto flex-shrink-0 tabular-nums text-slate-400">
                {String(r.wins ?? 0)}–{String(r.losses ?? 0)}
                {r.ties ? `–${r.ties}` : ''}
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
  const queryClient = useQueryClient()

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

  // N-2b: fetch league visibility for non-member join prompt
  const visibilityQuery = useQuery({
    queryKey: ['league-visibility', effectiveSlug],
    queryFn: async () => {
      if (!supabase) return null
      const { data } = await supabase
        .from('leagues')
        .select('visibility')
        .eq('slug', effectiveSlug)
        .maybeSingle()
      return (data as { visibility: string } | null)?.visibility ?? null
    },
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
  const standings = (Array.isArray(snapshot.standings) ? snapshot.standings : []) as Row[]
  const roundLabel = (snapshot.playoff_context as Row | undefined)?.round_label

  const myLeague = membershipsQuery.data?.find((l) => l.slug === effectiveSlug) ?? null
  const myTeam = myLeague?.teamName ?? null
  const isMember = Boolean(session && membershipsQuery.data && myLeague)
  const leagueId = (snapshot as Record<string, unknown>).league_id as string | undefined
  const isPublic = visibilityQuery.data === 'public'

  const teamNames: string[] = standings
    .map((s) => String(s.team_name ?? ''))
    .filter(Boolean)

  const myMatchup = myTeam
    ? matchups.find(
        (m) => m.home_team === myTeam || m.away_team === myTeam,
      ) ?? null
    : null
  const featured = myMatchup ?? matchups[0] ?? null

  const newsroomPath = `/leagues/${effectiveSlug}/newsroom/${season}/${week}`
  const matchupsPath = `/leagues/${effectiveSlug}/matchups/${week}`
  const standingsPath = `/leagues/${effectiveSlug}/standings`

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
          claimHint={Boolean(session) && isMember && myTeam === null}
        />
      ) : (
        <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5">
          <p className="text-sm text-slate-500">
            No matchup data yet — check back once the week is underway.
          </p>
        </section>
      )}

      {/* N-2b: non-member → Join prompt; member-no-team → claim hint */}
      {Boolean(session) && !isMember && isPublic && leagueId && (
        <JoinLeague
          leagueId={leagueId}
          teams={teamNames}
          onJoined={() => queryClient.invalidateQueries({ queryKey: ['my-leagues'] })}
        />
      )}
      {Boolean(session) && !isMember && !isPublic && (
        <section className="rounded-pg-lg border border-pg-border bg-pg-card p-5 text-center">
          <p className="text-sm text-slate-500">
            This league is private — ask an admin for an invite.
          </p>
        </section>
      )}

      <div className="grid gap-4 md:grid-cols-4">
        <Movers rankings={rankings} />
        <RecapCard headline={latest?.headline ?? null} newsroomPath={newsroomPath} />
        <TransactionTicker transactions={transactions} />
        <StandingsCard standings={standings} standingsPath={standingsPath} />
      </div>
    </div>
  )
}
