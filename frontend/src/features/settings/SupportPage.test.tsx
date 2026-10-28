import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { qk } from "../../api/keys";
import { toasts } from "../../lib/toast";
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

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  toasts.set([]);
});

function draw(deviceKind: "phone" | "kiosk", shell: ShellKind = "phone", feedback = true) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(qk.session(), { device_kind: deviceKind });
  client.setQueryData(qk.diagnostics(), { version: "0.12.0", install_kind: "pi", feedback });
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

  it("sends feedback to GitHub's new issue where the server has feedback off", () => {
    draw("phone", "phone", false);
    expect(screen.getByText(/It needs a GitHub account/)).toBeTruthy();
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
    draw("kiosk", "display", false);
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

  it("sends feedback itself, with no account, and says thank you (ADR 0042)", async () => {
    const sent: unknown[] = [];
    vi.spyOn(api, "POST").mockImplementation((path: string, init: { body: unknown }) => {
      sent.push([path, init.body]);
      return Promise.resolve({ data: undefined, response: new Response(null, { status: 204 }) });
    });
    draw("phone");
    expect(screen.getByText(/It goes straight to the people who make Sunroom/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Send Feedback" }));
    const sheet = screen.getByRole("dialog", { name: "Send Feedback" });
    const send = within(sheet).getByRole<HTMLButtonElement>("button", { name: "Send Feedback" });
    expect(send.disabled).toBe(true); // a title first
    expect(within(sheet).queryByRole("link", { name: "Open GitHub" })).toBeNull();
    fireEvent.click(within(sheet).getByRole("button", { name: "An idea" }));
    fireEvent.change(within(sheet).getByLabelText("In a few words"), {
      target: { value: "Dark tiles" },
    });
    fireEvent.change(within(sheet).getByLabelText("What happened, or what would help"), {
      target: { value: "At night the tiles glare." },
    });
    const contact = within(sheet).getByLabelText("How to reach you (optional)");
    expect(contact.getAttribute("aria-describedby")).toBeTruthy();
    expect(
      within(sheet).getByText("An email or a Discord name, if you'd like an answer."),
    ).toBeTruthy();
    fireEvent.change(contact, { target: { value: "ana@sample.invalid" } });
    fireEvent.click(send);
    await waitFor(() => {
      expect(toasts.get().map((toast) => toast.message)).toEqual(["Feedback sent. Thank you!"]);
    });
    expect(sent).toEqual([
      [
        "/api/feedback",
        {
          kind: "idea",
          title: "Dark tiles",
          body: "At night the tiles glare.",
          contact: "ana@sample.invalid",
        },
      ],
    ]);
    expect(screen.queryByRole("dialog", { name: "Send Feedback" })).toBeNull();
  });

  it("takes the words on a paired screen too, on its keyboard", () => {
    draw("kiosk", "display");
    fireEvent.click(screen.getByRole("button", { name: "Send Feedback" }));
    const sheet = screen.getByRole("dialog", { name: "Send Feedback" });
    const words = within(sheet).getByLabelText("What happened, or what would help");
    expect(words.dataset.osk).toBe("text");
    expect(within(sheet).getByLabelText("How to reach you (optional)").dataset.osk).toBe("text");
    expect(within(sheet).queryByRole("img")).toBeNull(); // no code to scan
  });

  it("says why under the button when it can't send, and stays open", async () => {
    vi.spyOn(api, "POST").mockResolvedValue({
      error: {
        error: { code: "feedback_failed", message: "Couldn't send it. Try again in a moment." },
      },
      response: new Response(null, { status: 502 }),
    });
    draw("phone");
    fireEvent.click(screen.getByRole("button", { name: "Send Feedback" }));
    const sheet = screen.getByRole("dialog", { name: "Send Feedback" });
    fireEvent.change(within(sheet).getByLabelText("In a few words"), {
      target: { value: "The week is blank" },
    });
    fireEvent.click(within(sheet).getByRole("button", { name: "Send Feedback" }));
    expect((await within(sheet).findByRole("alert")).textContent).toBe(
      "Couldn't send it. Try again in a moment.",
    );
    expect(screen.getByRole("dialog", { name: "Send Feedback" })).toBeTruthy();
    expect(toasts.get()).toEqual([]);
  });

  it("turns to GitHub's way when the server answers that feedback is off", async () => {
    vi.spyOn(api, "POST").mockResolvedValue({
      error: { error: { code: "feedback_off", message: "Feedback isn't set up on this Sunroom." } },
      response: new Response(null, { status: 409 }),
    });
    draw("phone");
    fireEvent.click(screen.getByRole("button", { name: "Send Feedback" }));
    const sheet = screen.getByRole("dialog", { name: "Send Feedback" });
    fireEvent.change(within(sheet).getByLabelText("In a few words"), {
      target: { value: "The week is blank" },
    });
    fireEvent.click(within(sheet).getByRole("button", { name: "Send Feedback" }));
    const open = await within(sheet).findByRole("link", { name: "Open GitHub" });
    expect(new URL(open.getAttribute("href") ?? "").searchParams.get("title")).toBe(
      "Problem: The week is blank",
    );
    expect(within(sheet).queryByRole("alert")).toBeNull();
  });
});
