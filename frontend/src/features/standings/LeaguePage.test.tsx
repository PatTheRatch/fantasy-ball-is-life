import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { LeaguePage } from "./LeaguePage";
import { api } from "../../shared/api/client";

// The generated client is the contract boundary — mock it here so the test
// exercises the query + page state mapping without a backend.
vi.mock("../../shared/api/client", () => ({
  api: { GET: vi.fn() },
}));

const LEAGUE_ID = "11111111-1111-1111-1111-111111111111";

// Server order is intentionally NOT alphabetical (Cavs, Bulls, Pistons) so the
// order assertion proves the page does not re-sort client-side.
const ROWS = [
  { rank: 1, team_id: "t1", team_name: "Cavs", team_abbreviation: "CLE", wins: 30, losses: 10, ties: 0, win_pct: 66.7, played: 40 },
  { rank: 2, team_id: "t2", team_name: "Bulls", team_abbreviation: "CHI", wins: 20, losses: 20, ties: 0, win_pct: 50.0, played: 40 },
  { rank: 3, team_id: "t3", team_name: "Pistons", team_abbreviation: null, wins: 10, losses: 30, ties: 0, win_pct: 33.3, played: 40 },
];

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/leagues/${LEAGUE_ID}`]}>
        <Routes>
          <Route path="/leagues/:leagueSeasonId" element={<LeaguePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("LeaguePage", () => {
  it("calls the standings endpoint with the path param from the URL", async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: { data: [], as_of: null, freshness: "final", stale: false },
      error: undefined,
      response: new Response(),
    } as never);

    renderPage();

    await screen.findByText("This league hasn't synced a completed week yet.");
    expect(api.GET).toHaveBeenCalledWith(
      "/api/v1/leagues/{league_season_id}/standings",
      { params: { path: { league_season_id: LEAGUE_ID } } },
    );
  });

  it("renders rows in server order with basketball win_pct", async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: { data: ROWS, as_of: "2026-01-11", freshness: "final", stale: false },
      error: undefined,
      response: new Response(),
    } as never);

    renderPage();

    const bodyRows = (await screen.findAllByRole("row")).slice(1);
    expect(bodyRows).toHaveLength(3);
    // rank cells in server order (1, 2, 3)
    expect(
      bodyRows.map((r) => within(r).getAllByRole("cell")[0].textContent),
    ).toEqual(["1", "2", "3"]);
    // team names in server order — Cavs before Bulls before Pistons, which is
    // NOT alphabetical, proving no client-side re-sort.
    expect(bodyRows[0]).toHaveTextContent("Cavs");
    expect(bodyRows[1]).toHaveTextContent("Bulls");
    expect(bodyRows[2]).toHaveTextContent("Pistons");
    // 66.7% renders as .667 (three decimals, no leading zero)
    expect(screen.getByText(".667")).toBeInTheDocument();
    expect(screen.getByText(".500")).toBeInTheDocument();
  });

  it("renders not-synced (not error) when as_of is null", async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: { data: [], as_of: null, freshness: "final", stale: false },
      error: undefined,
      response: new Response(),
    } as never);

    renderPage();

    expect(
      await screen.findByText("This league hasn't synced a completed week yet."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders empty state when data is empty but as_of is set", async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: { data: [], as_of: "2026-01-11", freshness: "final", stale: false },
      error: undefined,
      response: new Response(),
    } as never);

    renderPage();

    expect(await screen.findByText("No results yet.")).toBeInTheDocument();
  });

  it("renders a 403/404 as a combined not-found-or-forbidden error", async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: undefined,
      error: { status: 403 },
      response: new Response("", { status: 403 }),
    } as never);

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This league doesn't exist or you're not a member.",
    );
  });
});
