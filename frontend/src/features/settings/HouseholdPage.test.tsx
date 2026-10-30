import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { qk } from "../../api/keys";
import type { HouseholdSettings } from "../../lib/household";
import { HouseholdPage } from "./HouseholdPage";

const SETTINGS = {
  household_name: "Sample Family",
  timezone: "America/New_York",
  week_starts_on: 6,
  time_format: "12h",
  language: "en",
} as HouseholdSettings;

function draw() {
  const client = new QueryClient();
  client.setQueryData(qk.settings(), SETTINGS);
  client.setQueryData(qk.plugins(), []);
  render(
    <QueryClientProvider client={client}>
      <HouseholdPage />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("Settings → Household (UX §4)", () => {
  it("starts with the language, the complete ones by their own names, saving itself", async () => {
    const patch = vi.spyOn(api, "PATCH").mockResolvedValue({
      data: SETTINGS,
      error: undefined,
      response: new Response(),
    } as never);
    draw();
    const language = screen.getByRole("group", { name: "Language" });
    expect(screen.getAllByRole("group")[0]).toBe(language);
    const english = within(language).getByRole("button", { name: "English" });
    expect(english.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(english);
    await waitFor(() => {
      expect(patch).toHaveBeenCalledWith("/api/settings", { body: { language: "en" } });
    });
  });

  it("names the week's first day and the clock in words", () => {
    draw();
    expect(
      within(screen.getByRole("group", { name: "Week starts on" }))
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Sunday", "Monday"]);
    expect(screen.getByRole("group", { name: "Time format" }).textContent).toBe("12-hour24-hour");
  });
});
