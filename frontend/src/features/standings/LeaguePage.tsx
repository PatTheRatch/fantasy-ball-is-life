import { useParams } from "react-router-dom";
import { useStandings, StandingsError } from "./queries";
import { Card } from "../../shared/ui/Card";
import { StateMessage } from "../../shared/ui/StateMessage";

// The standings endpoint emits `win_pct` as a 0-100 percentage (the domain
// folds it as `ratio * 100`, rounded to one decimal). Basketball convention is
// a 0-1 ratio with three decimals and no leading zero, so divide by 100 first:
// 66.7 -> ".667", 100.0 -> "1.000".
function formatWinPct(winPct: number): string {
  return (winPct / 100).toFixed(3).replace(/^0+/, "");
}

// `as_of` is a date-only string (YYYY-MM-DD). Use a UTC parse so the browser's
// local timezone can't shift it to the previous day.
function formatDate(isoDate: string): string {
  return new Date(isoDate).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function LeaguePage() {
  const { leagueSeasonId } = useParams<"leagueSeasonId">();
  const { data, isPending, isError, error } = useStandings(
    leagueSeasonId ?? "",
  );

  if (isPending) {
    return <StateMessage kind="loading" />;
  }

  if (isError) {
    const status = error instanceof StandingsError ? error.status : undefined;
    const isForbiddenOrMissing = status === 403 || status === 404;
    return (
      <StateMessage
        kind="error"
        message={
          isForbiddenOrMissing
            ? "This league doesn't exist or you're not a member."
            : undefined
        }
      />
    );
  }

  if (data.as_of === null) {
    return (
      <StateMessage
        kind="not-synced"
        message="This league hasn't synced a completed week yet."
      />
    );
  }

  if (data.data.length === 0) {
    return <StateMessage kind="empty" />;
  }

  return (
    <div className="space-y-4">
      {data.stale && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-2 text-sm text-amber-800">
          Showing data as of {formatDate(data.as_of)}
        </div>
      )}
      <Card>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 text-left text-xs uppercase tracking-wide text-gray-500">
              <th className="py-2 pr-2">#</th>
              <th className="py-2 pr-2">Team</th>
              <th className="py-2 pr-2 text-right">W</th>
              <th className="py-2 pr-2 text-right">L</th>
              <th className="py-2 pr-2 text-right">T</th>
              <th className="py-2 pr-2 text-right">Pct</th>
              <th className="py-2 text-right">GP</th>
            </tr>
          </thead>
          <tbody>
            {data.data.map((row) => (
              <tr key={row.team_id} className="border-b border-gray-100">
                <td className="py-2 pr-2 text-gray-500">{row.rank}</td>
                <td className="py-2 pr-2 font-medium">
                  {row.team_name}
                  {row.team_abbreviation && (
                    <span className="ml-1 font-normal text-gray-400">
                      {row.team_abbreviation}
                    </span>
                  )}
                </td>
                <td className="py-2 pr-2 text-right">{row.wins}</td>
                <td className="py-2 pr-2 text-right">{row.losses}</td>
                <td className="py-2 pr-2 text-right">{row.ties}</td>
                <td className="py-2 pr-2 text-right">
                  {formatWinPct(row.win_pct)}
                </td>
                <td className="py-2 text-right">{row.played}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-xs text-gray-500">
          Final through {formatDate(data.as_of)}
        </p>
      </Card>
    </div>
  );
}
