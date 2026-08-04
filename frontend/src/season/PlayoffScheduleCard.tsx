import { useQuery } from '@tanstack/react-query'
import { getPlayoffSchedule } from '../api'
import {
  Skeleton,
  TableRoot,
  TableHead,
  TableBody,
  Th,
  Td,
  Tr,
} from '../ui'

/**
 * W-2: games per NBA team during THIS league's playoff weeks.
 * Fantasy playoffs are won in October — a late-round pick whose NBA team
 * plays 4 games in your playoff weeks quietly beats a better player with 2.
 * Auto-loads (D-P6); the NBA schedule changes ~never, so cache hard.
 */
export function PlayoffScheduleCard({ slug }: { slug: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['playoff-schedule', slug],
    queryFn: () => getPlayoffSchedule(slug),
    staleTime: 24 * 60 * 60 * 1000,
    retry: false,
  })

  const teams = data?.teams ?? []
  const weeks = data?.playoff_weeks ?? []

  // Best/worst highlighting by total (backend sorts most-games-first).
  const totals = teams.map((t) => t.total)
  const best = totals.length ? Math.max(...totals) : 0
  const worst = totals.length ? Math.min(...totals) : 0

  return (
    <section className="border-t border-slate-800/80 pt-4">
      <h2 className="text-lg font-semibold text-white">Playoff schedule</h2>
      <p className="mt-1 text-xs text-slate-500">
        NBA games per team during your league&apos;s playoff weeks
        {weeks.length > 0 && ` (weeks ${weeks[0]}–${weeks[weeks.length - 1]})`} —
        more games = more counting stats from that team&apos;s players.
      </p>

      {isLoading && (
        <div className="mt-3 space-y-2">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      )}

      {!isLoading && (isError || teams.length === 0) && (
        <p className="mt-3 text-sm text-slate-500">
          {data?.reason === 'settings_unavailable'
            ? 'League settings haven’t synced yet — playoff weeks are derived from your ESPN playoff format.'
            : 'NBA schedule not yet released for this season — check back after the schedule drops (usually August).'}
        </p>
      )}

      {!isLoading && teams.length > 0 && (
        <div className="mt-3">
          <TableRoot variant="dense">
            <TableHead>
              <Th className="text-left">Team</Th>
              {weeks.map((w) => (
                <Th key={w}>W{w}</Th>
              ))}
              <Th>Total</Th>
            </TableHead>
            <TableBody>
              {teams.map((t) => (
                <Tr key={t.pro_team}>
                  <Td className="font-medium text-white">{t.pro_team}</Td>
                  {weeks.map((w) => (
                    <Td key={w}>{t.games_by_week[String(w)] ?? 0}</Td>
                  ))}
                  <Td
                    className={
                      t.total === best
                        ? 'font-bold text-emerald-400'
                        : t.total === worst
                          ? 'text-red-400'
                          : 'text-slate-300'
                    }
                  >
                    {t.total}
                  </Td>
                </Tr>
              ))}
            </TableBody>
          </TableRoot>
        </div>
      )}
    </section>
  )
}
