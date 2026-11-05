import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { qk } from "../../api/keys";
import { ShellContext } from "../../ui/shell";
import { UpdatesGroup } from "./AboutPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const STATUS = {
  enabled: true,
  locked: false,
  current: "1.0.0",
  latest: "1.0.0",
  available: false,
  checked_at: "2026-10-07T14:00:00Z",
  problem: null,
  how: "In Sunroom's folder on the server, run docker compose pull, then docker compose up -d.",
  how_key: "api.update.how.docker",
};

function draw(status: Partial<typeof STATUS> = {}, settings = { update_check: true }) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(qk.settings(), settings);
  client.setQueryData(qk.update(), { ...STATUS, ...status });
  render(
    <QueryClientProvider client={client}>
      <ShellContext.Provider value="phone">
        <UpdatesGroup />
      </ShellContext.Provider>
    </QueryClientProvider>,
  );
  return client;
}

describe("Settings → About → Updates (ADR 0046)", () => {
  it("is on, and says what it does and how to turn it off", () => {
    draw();
    const daily = screen.getByRole("switch", { name: /^Tell me about new versions/ });
    expect((daily as HTMLInputElement).checked).toBe(true);
    expect(
      screen.getByText("Checked once a day. Turn it off to keep Sunroom from asking GitHub."),
    ).toBeTruthy();
    expect(screen.getByText(/GitHub sees your server's address/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Check Now" })).toBeTruthy();
  });

  it("says a new version is out, and how to update this install", () => {
    draw({ latest: "1.1.0", available: true });
    expect(screen.getByRole("status").textContent).toBe(
      "Sunroom 1.1.0 is available. In Sunroom's folder on the server, run docker compose pull, then docker compose up -d.",
    );
  });

  it("is grey when the server keeps it off", () => {
    draw({ enabled: false, locked: true }, { update_check: false });
    const daily = screen.getByRole("switch", { name: /^Tell me about new versions/ });
    expect((daily as HTMLInputElement).disabled).toBe(true);
    expect(screen.getByText("This server keeps update checks off.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Check Now" })).toBeNull();
  });

  it("asks Needs Attention again after Check Now", async () => {
    const client = draw();
    const fresh = { ...STATUS, latest: "1.1.0", available: true };
    vi.spyOn(api, "POST").mockResolvedValue({ data: fresh, response: new Response() });
    const asked = vi.spyOn(client, "invalidateQueries");
    fireEvent.click(screen.getByRole("button", { name: "Check Now" }));
    await waitFor(() => {
      expect(asked).toHaveBeenCalledWith({ queryKey: qk.problems() });
    });
    expect(screen.getByRole("status").textContent).toContain("Sunroom 1.1.0 is available.");
  });
});
