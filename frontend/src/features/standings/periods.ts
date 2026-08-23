import { useQuery } from "@tanstack/react-query";
import { api } from "../../shared/api/client";

export const periodsKeys = {
  detail: (leagueSeasonId: string) => ["periods", leagueSeasonId] as const,
};

/**
 * The season's matchup periods — every one, not just final. The selector reads
 * this and decides what is selectable from `status`. A failed fetch leaves
 * `data` undefined, which the page treats as "no periods" (the selector simply
 * does not render) rather than blocking the standings the way a standings
 * failure does.
 */
export function usePeriods(leagueSeasonId: string) {
  return useQuery({
    queryKey: periodsKeys.detail(leagueSeasonId),
    queryFn: async () => {
      const { data, error } = await api.GET(
        "/api/v1/leagues/{league_season_id}/periods",
        { params: { path: { league_season_id: leagueSeasonId } } },
      );
      if (error) {
        throw new Error("periods request failed");
      }
      return data;
    },
    retry: false,
  });
}
