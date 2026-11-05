import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { api } from "../../api/client";
import { qk } from "../../api/keys";
import { toasts } from "../../lib/toast";
import { AccountSheet } from "./AccountSheet";
import type { Account, RemoteCalendar } from "./data";

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

const FAMILY = [
  { id: "a", name: "Ana", color: "clay", role: "parent" },
  { id: "m", name: "Mia", color: "rose", role: "kid" },
];

function calendar(overrides: Partial<RemoteCalendar> & Pick<RemoteCalendar, "id" | "name">) {
  return {
    mapped: true,
    read_only: false,
    color: "sky",
    owner_member_id: null,
    suggested_owner_id: null,
    visible_on_display: true,
    last_error: null,
    ...overrides,
  } as RemoteCalendar;
}

function account(overrides: Partial<Account> = {}): Account {
  return {
    id: "acct",
    label: "Apple",
    provider: "caldav",
    address: "ana@example.com",
    status: "connected",
    syncing: false,
    read_only: false,
    last_error: null,
    last_success_at: null,
    helper_email: null,
    calendars: [
      calendar({ id: "school", name: "School" }),
      calendar({ id: "work", name: "Work", mapped: false, suggested_owner_id: "a" }),
    ],
    ...overrides,
  } as Account;
}

interface Sent {
  method: string;
  path: string;
  body: unknown;
}

/** The sheet over a server that says yes to everything, with `screens` paired. */
function draw(shown: Account, { screens = ["Kitchen"], kiosk = false } = {}) {
  const sent: Sent[] = [];
  const answer =
    (method: string) =>
    (path: string, init?: { body?: unknown }): Promise<unknown> => {
      sent.push({ method, path, body: init?.body ?? null });
      return Promise.resolve({
        data: path.endsWith("/google/start") ? { authorize_url: "about:blank#google" } : shown,
        response: new Response(null, { status: 200 }),
      });
    };
  vi.spyOn(api, "GET").mockImplementation((() =>
    Promise.resolve({ data: [], response: new Response(null, { status: 200 }) })) as never);
  vi.spyOn(api, "PUT").mockImplementation(answer("PUT") as never);
  vi.spyOn(api, "POST").mockImplementation(answer("POST") as never);
  vi.spyOn(api, "DELETE").mockImplementation(answer("DELETE") as never);
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  client.setQueryData(["members", false], FAMILY);
  client.setQueryData(qk.devices(), [
    ...screens.map((label, index) => ({ id: `k${String(index)}`, kind: "kiosk", label })),
    { id: "p", kind: "phone", label: "Ana's phone" },
  ]);
  const onClose = vi.fn();
  const sheet = (next: Account | null) => (
    <QueryClientProvider client={client}>
      <AccountSheet account={next} kiosk={kiosk} onClose={onClose} />
    </QueryClientProvider>
  );
  const view = render(sheet(shown));
  /** The same sheet given another account, or none (closed). */
  const again = (next: Account | null) => {
    view.rerender(sheet(next));
  };
  return { sent, onClose, again };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  toasts.set([]);
});

describe("an account's sheet (UX §4 Calendars & Accounts)", () => {
  it("lists the calendars that sync first, then by name, and keeps that order while open", () => {
    const first = account({
      calendars: [
        calendar({ id: "zoo", name: "Zoo trips", mapped: false }),
        calendar({ id: "work", name: "Work" }),
        calendar({ id: "art", name: "Art club", mapped: false }),
        calendar({ id: "band", name: "Band" }),
      ],
    });
    const { again } = draw(first);
    const order = () =>
      screen
        .getAllByRole("switch")
        .map((input) => input.getAttribute("aria-label"))
        .filter(Boolean);
    expect(order()).toEqual(["Sync Band", "Sync Work", "Sync Art club", "Sync Zoo trips"]);
    // Art club switched on: its row stays under the finger until the sheet opens again (ADR 0032).
    const switched = account({
      calendars: first.calendars.map((one) => (one.id === "art" ? { ...one, mapped: true } : one)),
    });
    again(switched);
    expect(order()).toEqual(["Sync Band", "Sync Work", "Sync Art club", "Sync Zoo trips"]);
    again(null);
    again(switched);
    expect(order()).toEqual(["Sync Art club", "Sync Band", "Sync Work", "Sync Zoo trips"]);
  });

  it("lists its calendars under Sync, and the synced ones under Show on the screen's name", () => {
    draw(account());
    const sheet = screen.getByRole("dialog", { name: /^Edit Apple/ });
    expect(within(sheet).getByText("ana@example.com")).toBeTruthy();
    expect(within(sheet).getByRole("button", { name: "Refresh Now" })).toBeTruthy();
    expect(within(sheet).getByRole("heading", { name: "Sync" })).toBeTruthy();
    expect(
      within(sheet).getByRole<HTMLInputElement>("switch", { name: "Sync School" }).checked,
    ).toBe(true);
    expect(within(sheet).getByRole<HTMLInputElement>("switch", { name: "Sync Work" }).checked).toBe(
      false,
    );
    // Only a synced calendar opens a page of its own.
    expect(within(sheet).getByRole("button", { name: /^Edit School/ })).toBeTruthy();
    expect(within(sheet).queryByRole("button", { name: /^Edit Work/ })).toBeNull();
    expect(within(sheet).getByRole("heading", { name: "Show on Kitchen" })).toBeTruthy();
    expect(
      within(sheet)
        .getAllByRole("switch")
        .map((input) => input.getAttribute("aria-label")),
    ).toEqual(["Sync School", "Sync Work", null]);
    expect(within(sheet).getByRole<HTMLInputElement>("switch", { name: "School" }).checked).toBe(
      true,
    );
  });

  it("names the screens together when there are several, and says nothing with none", () => {
    draw(account(), { screens: ["Kitchen", "Hallway"] });
    expect(screen.getByRole("heading", { name: "Show on the Screens" })).toBeTruthy();
    cleanup();
    draw(account(), { screens: [] });
    expect(screen.queryByRole("heading", { name: /^Show on/ })).toBeNull();
    expect(screen.getByRole("heading", { name: "Sync" })).toBeTruthy();
  });

  it("saves each switch as it changes", async () => {
    const { sent } = draw(account());
    fireEvent.click(screen.getByRole("switch", { name: "Sync Work" }));
    fireEvent.click(screen.getByRole("switch", { name: "School" }));
    await waitFor(() => {
      expect(sent).toHaveLength(2);
    });
    expect(sent.map(({ method, body }) => [method, body])).toEqual([
      // A calendar that starts syncing goes to the person Sunroom guessed.
      ["PUT", { clear_owner: false, mapped: true, owner_member_id: "a" }],
      ["PUT", { clear_owner: false, visible_on_display: false }],
    ]);
  });

  it("opens a synced calendar's page: whose it is, and the free colors first", async () => {
    const { sent } = draw(account());
    fireEvent.click(screen.getByRole("button", { name: /^Edit School/ }));
    const page = screen.getByRole("dialog", { name: /^Edit School/ });
    const whose = within(page).getByRole("group", { name: "Whose is School" });
    expect(
      within(whose).getByRole("button", { name: "Everyone" }).getAttribute("aria-pressed"),
    ).toBe("true");
    const colors = within(page)
      .getAllByRole("radio")
      .map((radio) => (radio as HTMLInputElement).value);
    // Red is Ana's and Pink is Mia's: they come last.
    expect(colors).toEqual([
      "olive",
      "moss",
      "sea",
      "sky",
      "iris",
      "berry",
      "copper",
      "bark",
      "slate",
      "lime",
      "clay",
      "rose",
    ]);
    fireEvent.click(within(page).getByRole("radio", { name: "Teal" }));
    fireEvent.click(within(whose).getByRole("button", { name: "Mia" }));
    await waitFor(() => {
      expect(sent).toHaveLength(2);
    });
    expect(sent.map(({ body }) => body)).toEqual([
      { clear_owner: false, color: "sea" },
      { clear_owner: false, owner_member_id: "m" },
    ]);
    fireEvent.click(within(page).getByRole("button", { name: "Back to Apple" }));
    expect(screen.getByRole("dialog", { name: /^Edit Apple/ })).toBeTruthy();
  });

  it("removes the account only after asking", async () => {
    const { sent, onClose } = draw(account());
    fireEvent.click(screen.getByRole("button", { name: "Remove Account" }));
    const asking = screen.getByRole("dialog", { name: "Remove Apple?" });
    fireEvent.click(within(asking).getByRole("button", { name: "Keep It" }));
    expect(screen.getByRole("dialog", { name: /^Edit Apple/ })).toBeTruthy();
    expect(sent).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Remove Account" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove Apple" }));
    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
    expect(sent.map(({ method }) => method)).toEqual(["DELETE"]);
  });

  it("offers the way back in that fits an account that stopped working", () => {
    const broken = { status: "needs_reconnect", last_error: "Apple needs its password again." };
    draw(account(broken as Partial<Account>));
    expect(screen.queryByRole("button", { name: "Refresh Now" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Connect Again" }));
    const again = screen.getByRole("dialog", { name: "Connect Apple Again" });
    expect(within(again).getByLabelText("Password")).toBeTruthy();
    cleanup();
    // Google signs in on its own page: no password to type.
    const google = { ...broken, provider: "google", label: "Google", address: null };
    draw(account(google as Partial<Account>));
    expect(screen.getByRole("button", { name: "Sign In Again" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Connect Again" })).toBeNull();
    cleanup();
    // Its page can't open on a paired screen: a code opens Calendars & Accounts on a device.
    draw(account(google as Partial<Account>), { kiosk: true });
    expect(screen.queryByRole("button", { name: "Sign In Again" })).toBeNull();
    expect(screen.getByText("Sign in again from a device:")).toBeTruthy();
    expect(
      screen.getByRole("img", { name: "A code that opens Calendars & Accounts on a device" }),
    ).toBeTruthy();
    cleanup();
    // A helper's key is a file: the account is added again.
    draw(account({ ...google, helper_email: "helper@example.com" } as Partial<Account>));
    expect(screen.queryByRole("button", { name: /again$/ })).toBeNull();
    expect(screen.getByText(/add it again with a new key file/)).toBeTruthy();
  });
});
