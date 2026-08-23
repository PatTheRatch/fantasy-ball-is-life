import { useQuery } from "@tanstack/react-query";
import { api } from "../../shared/api/client";

// Query keys mirror the resource + all of its parameters. `through_period`
// joins this key when a period is selected — a key missing a parameter serves
// one view's data for another (week-3 standings under a week-7 heading).
export const standingsKeys = {
  detail: (leagueSeasonId: string, throughPeriod?: number) =>
    [
      "standings",
      leagueSeasonId,
      ...(throughPeriod !== undefined ? [throughPeriod] : []),
    ] as const,
};

/** An error that carries the HTTP status so the page can distinguish 403/404. */
export class StandingsError extends Error {
  constructor(public readonly status: number) {
    super(`standings request failed with status ${status}`);
    this.name = "StandingsError";
  }
}

export function useStandings(leagueSeasonId: string, throughPeriod?: number) {
  return useQuery({
    queryKey: standingsKeys.detail(leagueSeasonId, throughPeriod),
    queryFn: async () => {
      const { data, error, response } = await api.GET(
        "/api/v1/leagues/{league_season_id}/standings",
        {
          params: {
            path: { league_season_id: leagueSeasonId },
            // "Full season" omits the parameter entirely (not 0, not null).
            ...(throughPeriod !== undefined
              ? { query: { through_period: throughPeriod } }
              : {}),
          },
        },
      );
      if (error) {
        throw new StandingsError(response.status);
      }
      return data;
    },
    // 401/403/404 won't succeed on retry.
    retry: false,
  });
}
