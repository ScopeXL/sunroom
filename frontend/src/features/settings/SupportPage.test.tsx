import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { qk } from "../../api/keys";
import { ShellContext, type ShellKind } from "../../ui/shell";
import { SupportPage } from "./SupportPage";

// The owner's constants, filled in as the owner would (the real file starts empty).
vi.mock("./support", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./support")>()),
  PATREON_URL: "https://www.patreon.com/sample",
  ADDRESSES: [
    { name: "Bitcoin", address: "bc1qsampleaddress0000000000000000000000000" },
    { name: "Ether", address: "" },
  ],
}));

beforeAll(() => {
  // jsdom has no modal dialogs and no animations; these stand in for what the sheet uses.
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
  HTMLElement.prototype.getAnimations = () => [];
});

afterEach(cleanup);

function draw(deviceKind: "phone" | "kiosk", shell: ShellKind = "phone") {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(qk.session(), { device_kind: deviceKind });
  client.setQueryData(qk.diagnostics(), { version: "0.12.0", install_kind: "pi" });
  render(
    <QueryClientProvider client={client}>
      <ShellContext.Provider value={shell}>
        <SupportPage />
      </ShellContext.Provider>
    </QueryClientProvider>,
  );
}

describe("Settings → Support Sunroom (ADR 0034)", () => {
  it("says what Sunroom is, links Patreon and shows each address set, with Copy", () => {
    draw("phone");
    // The heart is beside the heading, hidden from screen readers.
    expect(screen.getByRole("heading", { name: "Support Sunroom" })).toBeTruthy();
    expect(screen.getByText(/not for profit/)).toBeTruthy();
    const patreon = screen.getByRole("link", { name: "Open Patreon" });
    expect(patreon.getAttribute("href")).toBe("https://www.patreon.com/sample");
    expect(patreon.getAttribute("target")).toBe("_blank");
    expect(screen.getByText("bc1qsampleaddress0000000000000000000000000")).toBeTruthy();
    expect(screen.getByRole("img", { name: "A code of the Bitcoin address" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Copy" })).toBeTruthy();
    // An address left empty isn't drawn.
    expect(screen.queryByText("Ether")).toBeNull();
  });

  it("gives a paired screen codes to scan instead of links, and no Copy", () => {
    draw("kiosk", "display");
    expect(screen.queryByRole("link", { name: "Open Patreon" })).toBeNull();
    expect(screen.getByRole("img", { name: "A code that opens Patreon" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Copy" })).toBeNull();
  });

  it("opens the Sunroom Discord first, in a new tab, or as a code on a screen (ADR 0042)", () => {
    draw("phone");
    const discord = screen.getByRole("link", { name: "Open Discord" });
    expect(discord.getAttribute("href")).toBe("https://discord.gg/y6AeQRpsPQ");
    expect(discord.getAttribute("target")).toBe("_blank");
    expect(discord.getAttribute("rel")).toBe("noreferrer noopener");
    expect(discord.textContent).toContain(
      "Join the Sunroom Discord for help, ideas and what's new.",
    );
    // The first of the group's rows, before Patreon.
    const links = screen.getAllByRole("link").map((link) => link.getAttribute("aria-label"));
    expect(links.slice(0, 2)).toEqual(["Open Discord", "Open Patreon"]);
    cleanup();
    draw("kiosk", "display");
    expect(screen.queryByRole("link", { name: "Open Discord" })).toBeNull();
    expect(screen.getByText("discord.gg/y6AeQRpsPQ")).toBeTruthy();
    expect(screen.getByRole("img", { name: "A code that opens the Sunroom Discord" })).toBeTruthy();
  });

  it("sends feedback to GitHub's new issue, once it has a title", () => {
    draw("phone");
    fireEvent.click(screen.getByRole("button", { name: "Send Feedback" }));
    const sheet = screen.getByRole("dialog", { name: "Send Feedback" });
    expect(
      within(sheet).getByText(
        "Sunroom 0.12.0 on a Raspberry Pi is added for you. Nothing else is.",
      ),
    ).toBeTruthy();
    const open = within(sheet).getByRole("link", { name: "Open GitHub" });
    expect(open.getAttribute("href")).toBeNull();
    expect(open.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(within(sheet).getByRole("button", { name: "An idea" }));
    fireEvent.change(within(sheet).getByLabelText("In a few words"), {
      target: { value: "Dark tiles" },
    });
    fireEvent.change(within(sheet).getByLabelText("What happened, or what would help"), {
      target: { value: "At night the tiles glare." },
    });
    const url = new URL(open.getAttribute("href") ?? "");
    expect(url.pathname).toBe("/ScopeXL/sunroom/issues/new");
    expect(url.searchParams.get("title")).toBe("Idea: Dark tiles");
    expect(url.searchParams.get("body")).toBe(
      "At night the tiles glare.\n\n---\nSunroom 0.12.0, a Raspberry Pi",
    );
  });

  it("shows a paired screen a code of the link, the title only, and no words to type", () => {
    draw("kiosk", "display");
    fireEvent.click(screen.getByRole("button", { name: "Send Feedback" }));
    const sheet = screen.getByRole("dialog", { name: "Send Feedback" });
    expect(within(sheet).queryByLabelText("What happened, or what would help")).toBeNull();
    expect(within(sheet).queryByRole("img")).toBeNull();
    fireEvent.change(within(sheet).getByLabelText("In a few words"), {
      target: { value: "The wall froze" },
    });
    expect(
      within(sheet).getByRole("img", { name: "A code that opens GitHub's new issue" }),
    ).toBeTruthy();
    expect(within(sheet).getByText("Scan this with your phone to finish on GitHub.")).toBeTruthy();
    expect(within(sheet).getByRole("button", { name: "Done" })).toBeTruthy();
    expect(within(sheet).queryByRole("link", { name: "Open GitHub" })).toBeNull();
  });
});
