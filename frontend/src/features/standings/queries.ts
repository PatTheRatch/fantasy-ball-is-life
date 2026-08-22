import { useQuery } from "@tanstack/react-query";
import { api } from "../../shared/api/client";

// Query keys mirror the resource + all of its parameters. `through_period`
// joins this key when S1-11c adds the selector — a key missing a parameter
// serves one view's data for another.
export const standingsKeys = {
  detail: (leagueSeasonId: string) => ["standings", leagueSeasonId] as const,
};

/** An error that carries the HTTP status so the page can distinguish 403/404. */
export class StandingsError extends Error {
  constructor(public readonly status: number) {
    super(`standings request failed with status ${status}`);
    this.name = "StandingsError";
  }
}

export function useStandings(leagueSeasonId: string) {
  return useQuery({
    queryKey: standingsKeys.detail(leagueSeasonId),
    queryFn: async () => {
      const { data, error, response } = await api.GET(
        "/api/v1/leagues/{league_season_id}/standings",
        { params: { path: { league_season_id: leagueSeasonId } } },
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
