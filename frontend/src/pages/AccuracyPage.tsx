import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import {
  getProjectionAccuracy,
  type AccuracyCategoryScore,
  type ProjectionAccuracyResponse,
} from '../api'
import {
  Skeleton,
  TableRoot,
  TableHead,
  TableBody,
  Th,
  Td,
  Tr,
} from '../ui'

/** Category display order — the league's 9-cat plus games played. */
const CATEGORY_ORDER = ['PTS', 'REB', 'AST', 'STL', 'BLK', '3PM', 'TO', 'FG%', 'FT%', 'GP']

const UNSCOREABLE_LABELS: Record<string, string> = {
  week_in_progress: 'week still in progress',
  no_actuals_for_week: 'no stored results for this week yet',
  no_roster_mapping: 'no roster snapshot to map players to fantasy teams',
  set_file_missing: 'projection file missing from the store',
  empty_actuals: 'stored week results are empty',
  no_team_overlap: 'team names did not match the scoreboard',
}

function fmt(value: number | null | undefined, digits: number): string {
  return value === null || value === undefined ? '—' : value.toFixed(digits)
}

/** MAE/bias formatting: percentages are tiny ratios, counting stats aren't. */
function fmtStat(cat: string, value: number | null | undefined): string {
  return fmt(value, cat.includes('%') ? 3 : 1)
}

function categoriesOf(data: ProjectionAccuracyResponse): string[] {
  const present = new Set<string>()
  for (const s of data.sources) {
    for (const cat of Object.keys(s.per_category)) present.add(cat)
  }
  const ordered = CATEGORY_ORDER.filter((c) => present.has(c))
  const extras = [...present].filter((c) => !CATEGORY_ORDER.includes(c)).sort()
  return [...ordered, ...extras]
}

function SummaryCell({ score }: { score: AccuracyCategoryScore | undefined; cat: string }) {
  if (!score) return <Td className="text-slate-600">—</Td>
  return (
    <Td>
      <span className="text-slate-200">{score.mae_pct !== null ? `${(score.mae_pct * 100).toFixed(1)}%` : '—'}</span>
      <span className="ml-2 text-xs text-slate-500">
        ρ {fmt(score.rank_corr, 2)}
      </span>
    </Td>
  )
}

/**
 * M-2: the projection accuracy scoreboard (internal page).
 * Every stored projection source, scored against what actually happened —
 * this is the referee that decides whether the FCP model earns its place.
 */
export function AccuracyPage() {
  const { slug = '' } = useParams()
  const { data, isLoading, isError } = useQuery({
    queryKey: ['projection-accuracy', slug],
    queryFn: () => getProjectionAccuracy(slug),
    staleTime: 60 * 60 * 1000,
    retry: false,
  })

  const sources = data?.sources ?? []
  const weeks = data?.weeks ?? []
  const unscoreable = data?.unscoreable ?? []
  const categories = data ? categoriesOf(data) : []

  return (
    <div className="mx-auto max-w-5xl px-4 py-6">
      <h1 className="text-xl font-semibold text-white">Projection accuracy</h1>
      <p className="mt-1 text-sm text-slate-500">
        Every projection source, scored against actual weekly team totals.
        MAE% is the average miss as a share of the category&apos;s actual level
        (lower is better); ρ is rank correlation across teams (1.0 = perfect
        ordering). Bias marks systematic over- or under-projection.
      </p>

      {isLoading && (
        <div className="mt-4 space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      )}

      {!isLoading && (isError || sources.length === 0) && (
        <p className="mt-4 text-sm text-slate-500">
          Nothing scoreable yet. Weeks become scoreable once a projection
          snapshot exists for a completed week — the worker snapshots ESPN-15
          automatically each week during the season, and weekly BBM uploads
          are scored from the week they cover.
        </p>
      )}

      {!isLoading && sources.length > 0 && (
        <section className="mt-5">
          <h2 className="text-lg font-semibold text-white">
            Source vs source{' '}
            <span className="text-sm font-normal text-slate-500">
              (avg across scored weeks, season {data?.season})
            </span>
          </h2>
          <div className="mt-3">
            <TableRoot variant="dense">
              <TableHead>
                <Th className="text-left">Category</Th>
                {sources.map((s) => (
                  <Th key={s.source} className="text-left">
                    {s.source.toUpperCase()}
                    <span className="ml-1 font-normal text-slate-500">
                      ({s.weeks_scored}w)
                    </span>
                  </Th>
                ))}
              </TableHead>
              <TableBody>
                {categories.map((cat) => (
                  <Tr key={cat}>
                    <Td className="font-medium text-white">{cat}</Td>
                    {sources.map((s) => (
                      <SummaryCell key={s.source} score={s.per_category[cat]} cat={cat} />
                    ))}
                  </Tr>
                ))}
              </TableBody>
            </TableRoot>
          </div>
        </section>
      )}

      {!isLoading && weeks.length > 0 && (
        <section className="mt-6">
          <h2 className="text-lg font-semibold text-white">Scored weeks</h2>
          <div className="mt-3">
            <TableRoot variant="dense">
              <TableHead>
                <Th className="text-left">Week</Th>
                <Th className="text-left">Source</Th>
                <Th>Teams</Th>
                <Th>PTS MAE</Th>
                <Th>REB MAE</Th>
                <Th>AST MAE</Th>
                <Th>FG% MAE</Th>
                <Th>Unassigned</Th>
              </TableHead>
              <TableBody>
                {weeks.map((w) => (
                  <Tr key={`${w.source}-${w.week}`}>
                    <Td className="font-medium text-white">W{w.week}</Td>
                    <Td className="text-left">{w.source.toUpperCase()}</Td>
                    <Td>
                      {w.teams_matched}/{w.teams_total}
                    </Td>
                    <Td>{fmtStat('PTS', w.per_category['PTS']?.mae)}</Td>
                    <Td>{fmtStat('REB', w.per_category['REB']?.mae)}</Td>
                    <Td>{fmtStat('AST', w.per_category['AST']?.mae)}</Td>
                    <Td>{fmtStat('FG%', w.per_category['FG%']?.mae)}</Td>
                    <Td className={w.players_unassigned > 0 ? 'text-amber-400' : ''}>
                      {w.players_unassigned}
                    </Td>
                  </Tr>
                ))}
              </TableBody>
            </TableRoot>
          </div>
        </section>
      )}

      {!isLoading && unscoreable.length > 0 && (
        <section className="mt-6">
          <h2 className="text-sm font-semibold text-slate-400">Not scoreable</h2>
          <ul className="mt-2 space-y-1 text-xs text-slate-500">
            {unscoreable.map((u) => (
              <li key={`${u.source}-${u.week}`}>
                {u.source.toUpperCase()} week {u.week} —{' '}
                {UNSCOREABLE_LABELS[u.reason] ?? u.reason}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
