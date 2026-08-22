import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MePage } from "./MePage";
import { api } from "../../shared/api/client";

// The generated client is the contract boundary — mock it here so the test
// exercises the query + component data shaping without a backend.
vi.mock("../../shared/api/client", () => ({
  api: { GET: vi.fn() },
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MePage />
    </QueryClientProvider>,
  );
}

describe("MePage", () => {
  it("renders the user's name and email from the generated client", async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: { id: "u1", email: "pat@x.com", display_name: "Pat" },
      error: undefined,
      response: new Response(),
    } as never);

    renderPage();

    expect(await screen.findByText("Pat")).toBeInTheDocument();
    expect(screen.getByText("pat@x.com")).toBeInTheDocument();
  });

  it("renders an error state when the client fails", async () => {
    vi.mocked(api.GET).mockResolvedValue({
      data: undefined,
      error: { status: 401 },
      response: new Response(),
    } as never);

    renderPage();

    expect(await screen.findByRole("alert")).toBeInTheDocument();
  });
});
