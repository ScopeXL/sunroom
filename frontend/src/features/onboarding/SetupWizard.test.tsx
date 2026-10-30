import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { setLanguage } from "../../lib/lang";
import { SetupWizard, type SetupStep } from "./SetupWizard";

vi.mock("@tanstack/react-router", () => ({ useNavigate: () => vi.fn() }));

/** The wizard as the wall runs it (ADR 0039): its steps move by `go`. */
function Wizard() {
  const [step, setStep] = useState<SetupStep>("password");
  return (
    <SetupWizard
      step={step}
      onScreen={{ go: setStep, leave: vi.fn(), open: vi.fn(), address: "http://sunroom.local" }}
    />
  );
}

async function reachTheHouseholdStep() {
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Wizard />
    </QueryClientProvider>,
  );
  fireEvent.change(screen.getByLabelText(/^Household password/), {
    target: { value: "sample-passphrase" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  return screen.findByRole("heading", { name: "Name Your Household" });
}

afterEach(async () => {
  cleanup();
  vi.restoreAllMocks();
  await setLanguage("en", { remember: false });
});

describe("setup's household step (UX §6, ADR 0043)", () => {
  it("asks the language first, as the page speaks it, and saves it with the household", async () => {
    const post = vi.spyOn(api, "POST").mockResolvedValue({
      data: undefined,
      error: { error: { code: "invalid", message: "Stop here." } },
      response: new Response(null, { status: 422 }),
    });
    await reachTheHouseholdStep();
    const language = screen.getByRole("group", { name: "Language" });
    expect(screen.getAllByRole("group")[0]).toBe(language);
    expect(
      within(language).getByRole("button", { name: "English" }).getAttribute("aria-pressed"),
    ).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith("/api/setup", {
        body: expect.objectContaining({ language: "en", on_screen: true }) as unknown,
      });
    });
  });
});
