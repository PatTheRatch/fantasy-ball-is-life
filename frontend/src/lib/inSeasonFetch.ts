import type { JsonRecord, MatchupCommentaryBody, ProjectedRosterPlayer } from '../api'
import {
  getMatchupConfidence,
  getRostersCurrent,
  getScoreboardCurrent,
  postProjectedScoreboard,
} from '../api'
import {
  clampDateToWeekWindow,
  enrichCurrentRows,
  mapProjectionSource,
  type MatchupGroup,
  type ProjectionSource,
  prepareMatchupGroups,
  sumNumGamesLeft,
} from './inSeasonUtils'
import { MATCHUP_WEEKS_2025_26 } from './matchupWeeks'

export const inSeasonQueryKeys = {
  projected: (slug: string, week: number, proj: string, fileKey: string) =>
    ['in-season', 'projected', slug, week, proj, fileKey] as const,
  current: (slug: string, week: number) =>
    ['in-season', 'current', slug, week] as const,
  power: (slug: string, week: number) =>
    ['in-season', 'power', slug, week] as const,
}

export async function fetchProjectedMatchupGroups(
  slug: string,
  week: number,
  projectionSource: ProjectionSource,
  bbmFile: File | null,
): Promise<MatchupGroup[]> {
  const weekMeta = MATCHUP_WEEKS_2025_26[week]
  const proj = mapProjectionSource(projectionSource)
  const weekEnd = weekMeta?.end
  const useUpload = projectionSource === 'bbm' && bbmFile
  if (useUpload) {
    const rows = await postProjectedScoreboard(
      slug,
      {
        current_matchup_period: week,
        projections: proj,
        week_end_date: weekEnd,
      },
      bbmFile,
    )
    return prepareMatchupGroups(rows)
  }
  let gamesPlayed = 0
  let totalGames = 1
  if (weekMeta?.start && weekMeta?.end) {
    const todayStr = new Date().toISOString().slice(0, 10)
    const remStart = clampDateToWeekWindow(
      todayStr,
      weekMeta.start,
      weekMeta.end,
    )
    try {
      const [totalRows, remRows] = await Promise.all([
        getRostersCurrent(slug, {
          week_start_date: weekMeta.start,
          week_end_date: weekMeta.end,
          current_matchup_period: week,
          projections: proj,
        }),
        getRostersCurrent(slug, {
          week_start_date: remStart,
          week_end_date: weekMeta.end,
          current_matchup_period: week,
          projections: proj,
        }),
      ])
      const totalSum = sumNumGamesLeft(totalRows)
      const remSum = sumNumGamesLeft(remRows)
      const gp = Math.max(0, Math.round(totalSum - remSum))
      const tg = Math.max(1, Math.round(totalSum))
      gamesPlayed = gp
      totalGames = tg
    } catch {
      /* keep defaults */
    }
  }
  const confRows = await getMatchupConfidence(slug, {
    current_matchup_period: week,
    projections: proj,
    games_played: gamesPlayed,
    total_games: totalGames,
  })
  return prepareMatchupGroups(confRows)
}

export async function fetchCurrentMatchupGroups(
  slug: string,
  week: number,
): Promise<MatchupGroup[]> {
  const raw = await getScoreboardCurrent(slug, week)
  return prepareMatchupGroups(enrichCurrentRows(raw))
}

export function buildProjectedRosterPlayers(
  rows: JsonRecord[],
  teamName: string,
  proj: ProjectionSource,
): ProjectedRosterPlayer[] {
  const suffix =
    proj === 'bbm' ? 'BBM' : proj === '15' ? 'Last 15' : 'Last 30'
  const projKey = (stat: string) =>
    proj === 'bbm'
      ? `Projected ${stat} BBM`
      : `Projected ${stat} ${suffix}`

  return rows
    .filter((r) => String(r.team_name) === teamName)
    .filter((r) => String(r.injuryStatus ?? '').toUpperCase() !== 'OUT')
    .map((r) => ({
      player_name: String(r.player_name ?? ''),
      pts: Number(r[projKey('PTS')] ?? 0) || 0,
      reb: Number(r[projKey('REB')] ?? 0) || 0,
      ast: Number(r[projKey('AST')] ?? 0) || 0,
      stl: Number(r[projKey('STL')] ?? 0) || 0,
      blk: Number(r[projKey('BLK')] ?? 0) || 0,
      '3pm': Number(r[projKey('3PM')] ?? 0) || 0,
      fg_pct: Number(r[projKey('FGM')] ?? 0) / Math.max(Number(r[projKey('FGA')] ?? 0), 1) || 0,
      ft_pct: Number(r[projKey('FTM')] ?? 0) / Math.max(Number(r[projKey('FTA')] ?? 0), 1) || 0,
      to: Number(r[projKey('TO')] ?? 0) || 0,
      games_left:
        r.num_games_left != null ? Number(r.num_games_left) : undefined,
    }))
}

export function projectedCommentaryRows(
  stats: JsonRecord[],
): MatchupCommentaryBody['matchup_data'] {
  return stats.map((s) => {
    const hr = String(s.projected_home_result ?? '').toUpperCase()
    let conf: number | undefined
    const hc = s.home_confidence_pct
    const ac = s.away_confidence_pct
    if (hr === 'W' && hc != null) conf = Number(hc)
    else if (hr === 'L' && ac != null) conf = Number(ac)
    else if (hr === 'T') {
      const a = hc != null ? Number(hc) : NaN
      const b = ac != null ? Number(ac) : NaN
      if (Number.isFinite(a) && Number.isFinite(b)) conf = (a + b) / 2
      else if (Number.isFinite(a)) conf = a
      else if (Number.isFinite(b)) conf = b
    }
    return {
      stat: String(s.stat),
      home_score: Number(s.projected_home_score),
      away_score: Number(s.projected_away_score),
      result: String(s.projected_home_result ?? 'T'),
      confidence_pct: conf,
    }
  })
}

export function currentCommentaryRows(
  stats: JsonRecord[],
): MatchupCommentaryBody['matchup_data'] {
  return stats.map((s) => ({
    stat: String(s.stat),
    home_score: Number(s.current_home_score),
    away_score: Number(s.current_away_score),
    result: String((s as JsonRecord)._home_res ?? 'T'),
    confidence_pct: undefined,
  }))

}
