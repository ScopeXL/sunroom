import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { qk } from "../api/keys";
import {
  forgetScreenAgent,
  noteOwnScreenAgent,
  runProgress,
  type ScreenState,
} from "../lib/screenAgent";
import { ShellContext } from "../ui/shell";
import { CantReachPage } from "./pages/CantReachPage";
import { FindPage } from "./pages/FindPage";
import { HerePage } from "./pages/HerePage";
import { OpeningPage } from "./pages/OpeningPage";
import { needsWifi, WelcomePage } from "./pages/WelcomePage";
import { afterWifi, go, route } from "./route";

vi.mock("./route", async (original) => ({
  ...(await original<typeof import("./route")>()),
  openSunroom: vi.fn(),
}));
const { openSunroom } = await import("./route");

const SUNROOM = "http://192.168.1.20:8080";

function state(overrides: Partial<ScreenState> = {}): ScreenState {
  return {
    version: "0.13.0",
    platform: "pi",
    model: "Raspberry Pi 5 Model B",
    session: "wayland",
    capabilities: ["restart", "shutdown", "update", "wifi", "rotate", "run_sunroom"],
    sunroom: null,
    network: { kind: "wifi", ssid: "HomeNet", ip: "192.168.1.30", strength: 82 },
    update: {
      check: "nightly",
      state: "unknown",
      installed: "0.13.0",
      latest: null,
      checked_at: null,
      message: null,
      sunroom_outdated: false,
    },
    display: { rotation: 0, brightness_method: "none" },
    open_url: null,
    ...overrides,
  };
}

const chosen = (reachable: boolean) =>
  state({
    sunroom: {
      url: SUNROOM,
      id: "00000000-0000-7000-8000-0000000000e1",
      name: "The Sample Family",
      found: "discovered",
      reachable,
    },
    open_url: `${SUNROOM}/display?dimmer=page&screen=7800`,
  });

let calls: { method: string; path: string; body: unknown }[];
let answers: Record<string, unknown>;

beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.removeAttribute("open");
  };
  HTMLElement.prototype.getAnimations = () => [];
});

beforeEach(() => {
  calls = [];
  answers = {};
  noteOwnScreenAgent();
  window.history.replaceState(null, "", "/");
  route.set("/");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      const path = new URL(request.url).pathname;
      const text = request.method === "GET" ? "" : await request.text();
      calls.push({
        method: request.method,
        path,
        body: text ? (JSON.parse(text) as unknown) : null,
      });
      const body = answers[`${request.method} ${path}`] ?? { ok: true };
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});

afterEach(() => {
  cleanup();
  forgetScreenAgent();
  vi.unstubAllGlobals();
  vi.mocked(openSunroom).mockClear();
});

function draw(page: ReactNode, cache: (client: QueryClient) => void = () => undefined) {
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
  cache(client);
  render(
    <QueryClientProvider client={client}>
      <ShellContext.Provider value="display">{page}</ShellContext.Provider>
    </QueryClientProvider>,
  );
}

describe("the screen's own pages (ADR 0035, ADR 0038)", () => {
  it("joins Wi-Fi first only with no network at all, where the screen can join one", () => {
    const offline = { kind: "none", ssid: null, ip: null, strength: null } as const;
    expect(needsWifi(state({ network: offline }))).toBe(true);
    expect(needsWifi(state())).toBe(false);
    expect(
      needsWifi(state({ network: offline, capabilities: ["restart", "shutdown", "update"] })),
    ).toBe(false);
  });

  it("welcomes a fresh screen with its two ways on as one choice, then Continue (ADR 0042)", () => {
    draw(<WelcomePage state={state()} />);
    expect(screen.getByRole("heading", { name: "Sunroom", level: 1 })).toBeTruthy();
    const ways = screen.getByRole("radiogroup", { name: "Where will your family’s Sunroom run?" });
    const here = within(ways).getByRole("radio", { name: "On This Computer" });
    const elsewhere = within(ways).getByRole("radio", { name: "Connect to a Sunroom" });
    // Each card says what it is and when to choose it; this computer is chosen from the start.
    expect(here.getAttribute("aria-checked")).toBe("true");
    expect(elsewhere.getAttribute("aria-checked")).toBe("false");
    expect(within(here).getByText("Run Sunroom right here.")).toBeTruthy();
    expect(within(here).getByText(/Choose this if your family is new to Sunroom/)).toBeTruthy();
    expect(
      within(elsewhere).getByText("Your family already runs Sunroom somewhere else."),
    ).toBeTruthy();
    // Only the chosen card is in the tab order, as in any radio group.
    expect([here.tabIndex, elsewhere.tabIndex]).toEqual([0, -1]);
    fireEvent.click(elsewhere);
    expect(elsewhere.getAttribute("aria-checked")).toBe("true");
    expect(here.getAttribute("aria-checked")).toBe("false");
    expect(route.get()).toBe("/"); // a tap chooses; Continue goes
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(route.get()).toBe("/find");
    expect(window.location.pathname).toBe("/find");
  });

  it("moves the choice with the arrow keys, and Continue goes the chosen way", () => {
    draw(<WelcomePage state={state()} />);
    const here = screen.getByRole("radio", { name: "On This Computer" });
    fireEvent.keyDown(here, { key: "ArrowRight" });
    const elsewhere = screen.getByRole("radio", { name: "Connect to a Sunroom" });
    expect(elsewhere.getAttribute("aria-checked")).toBe("true");
    expect(document.activeElement).toBe(elsewhere);
    fireEvent.keyDown(elsewhere, { key: "ArrowRight" }); // round to the first
    expect(here.getAttribute("aria-checked")).toBe("true");
    fireEvent.keyDown(here, { key: "End" });
    fireEvent.keyDown(elsewhere, { key: "Home" });
    expect(here.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(route.get()).toBe("/here");
  });

  it("offers only Connect to a Sunroom, chosen, where Sunroom can't run on this computer", () => {
    draw(<WelcomePage state={state({ capabilities: ["restart", "shutdown", "update"] })} />);
    expect(screen.queryByRole("radio", { name: "On This Computer" })).toBeNull();
    const elsewhere = screen.getByRole("radio", { name: "Connect to a Sunroom" });
    expect(elsewhere.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(route.get()).toBe("/find");
  });

  it("joins Wi-Fi first when offline, then goes on the way chosen", () => {
    afterWifi.set("/find");
    const offline = state({ network: { kind: "none", ssid: null, ip: null, strength: null } });
    draw(<WelcomePage state={offline} />);
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(route.get()).toBe("/wifi");
    expect(afterWifi.get()).toBe("/here");
  });

  it("sets Sunroom up on this computer as its page opens, and says how far it is", async () => {
    runProgress.set(null);
    draw(<HerePage state={state({ platform: "macos" })} />);
    expect(screen.getByRole("heading", { name: "Setting Up Sunroom" })).toBeTruthy();
    await waitFor(() => {
      expect(calls.filter((call) => call.path === "/api/screen/run-sunroom")).toHaveLength(1);
    });
    expect(screen.getByRole("status").textContent).toBe("Getting ready…");
    act(() => {
      runProgress.set({ percent: 40, step: "Downloading Sunroom…", message: null });
    });
    const status = screen.getByRole("status");
    expect(status.textContent).toMatch(/^Downloading Sunroom… /);
    expect(within(status).getByText("40%")).toBeTruthy(); // what a screen reader hears
    expect(screen.getByText(/choose Allow, so your family’s devices can reach it/)).toBeTruthy();
  });

  it("says why setting Sunroom up stopped, and Try Again runs it again", async () => {
    runProgress.set(null);
    draw(<HerePage state={state()} />);
    await waitFor(() => {
      expect(calls.filter((call) => call.path === "/api/screen/run-sunroom")).toHaveLength(1);
    });
    expect(screen.queryByText(/choose Allow/)).toBeNull();
    act(() => {
      runProgress.set({
        percent: 100,
        step: "Stopped",
        message: "Sunroom didn't start. Restart this screen, then try again.",
      });
    });
    expect(screen.getByRole("alert").textContent).toBe(
      "Sunroom didn't start. Restart this screen, then try again.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Try Again" }));
    await waitFor(() => {
      expect(calls.filter((call) => call.path === "/api/screen/run-sunroom")).toHaveLength(2);
    });
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    expect(route.get()).toBe("/");
  });

  it("lists what it found, a new Sunroom by name and an older one by version", async () => {
    answers["GET /api/screen/sunrooms"] = {
      scanning: false,
      found: [
        {
          url: SUNROOM,
          id: "00000000-0000-7000-8000-0000000000e1",
          name: "The Sample Family",
          version: "0.13.0",
          setup_complete: true,
          older: false,
        },
        {
          url: "http://192.168.1.21:8080",
          id: null,
          name: null,
          version: "0.11.0",
          setup_complete: true,
          older: true,
        },
      ],
    };
    answers["POST /api/screen/sunrooms/scan"] = answers["GET /api/screen/sunrooms"];
    draw(<FindPage state={state()} />);
    const network = screen.getByRole("region", { name: "On Your Network" });
    expect(await within(network).findByText("The Sample Family’s Sunroom")).toBeTruthy();
    expect(within(network).getByText(`${SUNROOM} · version 0.13.0`)).toBeTruthy();
    expect(within(network).getByText("A Sunroom")).toBeTruthy();
    // Running it here is Welcome's other way now (ADR 0038), not a card here.
    expect(screen.queryByRole("region", { name: "Run It on This Screen" })).toBeNull();
    const [first] = within(network).getAllByRole("button", { name: "Use This Sunroom" });
    if (!first) throw new Error("nothing to use");
    fireEvent.click(first);
    await waitFor(() => {
      expect(route.get()).toBe("/opening");
    });
    expect(calls.find((call) => call.method === "PUT")).toEqual({
      method: "PUT",
      path: "/api/screen/sunroom",
      body: { url: SUNROOM, found: "discovered" },
    });
  });

  it("checks a typed address when the field is left, and says plainly what it found", async () => {
    answers["GET /api/screen/sunrooms"] = { scanning: false, found: [] };
    answers["POST /api/screen/sunroom/check"] = {
      ok: false,
      sunroom: null,
      message: "That address isn't a Sunroom. Check it and try again.",
    };
    draw(<FindPage state={state({ capabilities: ["restart"] })} />);
    const elsewhere = screen.getByRole("region", { name: "Somewhere Else" });
    const field = within(elsewhere).getByLabelText(/^Sunroom address/);
    expect((field as HTMLInputElement).value).toBe("");
    const checks = () => calls.filter((call) => call.path === "/api/screen/sunroom/check");
    // Nothing worth asking about: an empty field, or only a scheme.
    fireEvent.blur(field);
    fireEvent.change(field, { target: { value: "https://" } });
    fireEvent.blur(field);
    expect(checks()).toHaveLength(0);
    fireEvent.change(field, { target: { value: "https://calendar.example.com" } });
    fireEvent.blur(field);
    expect(
      await within(elsewhere).findByText("That address isn't a Sunroom. Check it and try again."),
    ).toBeTruthy();
    expect(checks().map((call) => call.body)).toEqual([{ url: "https://calendar.example.com" }]);
    expect(within(elsewhere).getByRole("button", { name: "Not Found" })).toBeTruthy();
    expect(within(elsewhere).queryByRole("button", { name: "Use This Sunroom" })).toBeNull();
    // Leaving it again unchanged asks nothing more; the button tries again.
    fireEvent.blur(field);
    expect(checks()).toHaveLength(1);
    fireEvent.click(within(elsewhere).getByRole("button", { name: "Not Found" }));
    await waitFor(() => {
      expect(checks()).toHaveLength(2);
    });
    // Typing again puts the button back to rest.
    fireEvent.change(field, { target: { value: "192.168.1.20:8080" } });
    expect(within(elsewhere).getByRole("button", { name: "Check Address" })).toBeTruthy();
  });

  it("says Found on the button and offers Use This Sunroom in the same row", async () => {
    answers["GET /api/screen/sunrooms"] = { scanning: false, found: [] };
    answers["POST /api/screen/sunroom/check"] = {
      ok: true,
      sunroom: {
        url: SUNROOM,
        id: "00000000-0000-7000-8000-0000000000e1",
        name: "The Sample Family",
        version: "0.17.0",
        older: false,
      },
      message: null,
    };
    draw(<FindPage state={state({ capabilities: ["restart"] })} />);
    const elsewhere = screen.getByRole("region", { name: "Somewhere Else" });
    const field = within(elsewhere).getByLabelText(/^Sunroom address/);
    fireEvent.change(field, { target: { value: "192.168.1.20:8080" } });
    fireEvent.submit(field); // ↵, or the wall keyboard's enter key
    const found = await within(elsewhere).findByRole("button", { name: "Found" });
    expect(within(elsewhere).getByRole("status").textContent).toBe(
      "That’s The Sample Family’s Sunroom.",
    );
    const use = within(elsewhere).getByRole("button", { name: "Use This Sunroom" });
    expect(use.parentElement).toBe(found.parentElement);
    fireEvent.click(use);
    await waitFor(() => {
      expect(route.get()).toBe("/opening");
    });
    expect(calls.find((call) => call.method === "PUT")?.body).toEqual({
      url: SUNROOM,
      found: "typed",
    });
  });

  it("opens the Sunroom the moment it answers", () => {
    draw(<OpeningPage state={chosen(true)} />);
    expect(
      screen.getByRole("heading", { name: "Opening The Sample Family’s Sunroom…" }),
    ).toBeTruthy();
    expect(openSunroom).toHaveBeenCalledWith(`${SUNROOM}/display?dimmer=page&screen=7800`);
  });

  it("gives up opening after two minutes, for Can't Reach", () => {
    vi.useFakeTimers();
    try {
      draw(<OpeningPage state={chosen(false)} />);
      expect(openSunroom).not.toHaveBeenCalled();
      act(() => {
        vi.advanceTimersByTime(119_000);
      });
      expect(route.get()).toBe("/");
      act(() => {
        vi.advanceTimersByTime(2_000);
      });
      expect(route.get()).toBe("/cant-reach");
    } finally {
      vi.useRealTimers();
    }
  });

  it("Can't Reach tries again on a tap, and goes back by itself when it answers", async () => {
    answers["POST /api/screen/sunroom/check"] = {
      ok: false,
      sunroom: null,
      message: "Can't reach that address from here.",
    };
    draw(<CantReachPage state={chosen(false)} />, (client) => {
      client.setQueryData(qk.screen.state(), chosen(false));
    });
    expect(
      screen.getByRole("heading", { name: "Can’t Reach The Sample Family’s Sunroom" }),
    ).toBeTruthy();
    for (const name of ["Try Again", "Wi-Fi", "Change Address", "Restart"]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
    fireEvent.click(screen.getByRole("button", { name: "Try Again" }));
    expect(await screen.findByText("Can't reach that address from here.")).toBeTruthy();
    expect(openSunroom).not.toHaveBeenCalled();
    cleanup();
    draw(<CantReachPage state={chosen(true)} />);
    expect(openSunroom).toHaveBeenCalledWith(`${SUNROOM}/display?dimmer=page&screen=7800`);
  });

  it("goes between its pages with the browser's history", () => {
    go("/find");
    go("/settings");
    expect(route.get()).toBe("/settings");
    go("/opening", true);
    expect(window.location.pathname).toBe("/opening");
  });
});
