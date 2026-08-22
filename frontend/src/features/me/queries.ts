import { useQuery } from "@tanstack/react-query";
import { api } from "../../shared/api/client";

// Query keys mirror the resource + all of its parameters. The me endpoint has
// none; the standings query (S1-11b) will be `["standings", leagueSeasonId,
// throughPeriod]` — missing a parameter serves one view's data for another.
export const meKeys = {
  all: ["me"] as const,
};

export function useMe() {
  return useQuery({
    queryKey: meKeys.all,
    queryFn: async () => {
      const { data, error } = await api.GET("/api/v1/me");
      if (error) {
        throw new Error("failed to load profile");
      }
      return data;
    },
    // An auth failure (401/403) won't succeed on retry.
    retry: false,
  });
}
