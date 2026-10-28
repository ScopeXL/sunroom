import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { qk } from "../../api/keys";
import {
  forgetScreenAgent,
  noteScreenAgent,
  openScreenPage,
  sunroomName,
  type ScreenState,
} from "../../lib/screenAgent";
import { toasts } from "../../lib/toast";
import { ShellContext } from "../../ui/shell";
import { ThisScreenPage } from "./ThisScreenPage";

vi.mock("../../lib/screenAgent", async (original) => ({
  ...(await original<typeof import("../../lib/screenAgent")>()),
  openScreenPage: vi.fn(),
}));

const AGENT = "http://127.0.0.1:7800";

function piState(overrides: Partial<ScreenState> = {}): ScreenState {
  return {
    version: "0.13.0",
    platform: "pi",
    model: "Raspberry Pi 5 Model B",
    session: "wayland",
    capabilities: ["restart", "shutdown", "update", "wifi", "rotate", "brightness"],
    sunroom: {
      url: "http://192.168.1.20:8080",
      id: "00000000-0000-7000-8000-0000000000e1",
      name: "The Sample Family",
      found: "discovered",
      reachable: true,
    },
    network: { kind: "wifi", ssid: "HomeNet", ip: "192.168.1.30", strength: 82 },
    update: {
      check: "nightly",
      state: "up_to_date",
      installed: "0.13.0",
      latest: "0.13.0",
      checked_at: null,
      message: null,
      sunroom_outdated: false,
    },
    display: { rotation: 0, brightness_method: "ddc" },
    open_url: "http://192.168.1.20:8080/display?dimmer=screen&screen=7800",
    ...overrides,
  };
}

const NETWORKS = [
  { id: "HomeNet", ssid: "HomeNet", strength: 82, secured: true, connected: true, saved: true },
  {
    id: null,
    ssid: "SampleStreet-5G",
    strength: 54,
    secured: true,
    connected: false,
    saved: false,
  },
];

interface Call {
  method: string;
  path: string;
  body: unknown;
  header: string | null;
}

let calls: Call[];
let answers: Record<string, { status: number; body: unknown }>;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

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
  noteScreenAgent("/display", "?screen=7800");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (request: Request) => {
      const path = request.url.replace(AGENT, "");
      const text = request.method === "GET" ? "" : await request.text();
      calls.push({
        method: request.method,
        path,
        body: text ? (JSON.parse(text) as unknown) : null,
        header: request.headers.get("X-Sunroom-Screen"),
      });
      const planned = answers[`${request.method} ${path}`];
      if (planned) return json(planned.status, planned.body);
      if (path === "/api/screen") return json(200, piState());
      if (path === "/api/screen/wifi") return json(200, { networks: NETWORKS });
      if (path === "/api/screen/display")
        return json(200, piState({ display: { rotation: 90, brightness_method: "ddc" } }));
      return json(202, { ok: true });
    }),
  );
});

afterEach(() => {
  cleanup();
  vi.mocked(openScreenPage).mockClear();
  forgetScreenAgent();
  vi.unstubAllGlobals();
  toasts.set([]);
});

function draw(state: ScreenState = piState()) {
  const client = new QueryClient({
    defaultOptions: { queries: { staleTime: Infinity, retry: false } },
  });
  client.setQueryData(qk.screen.state(), state);
  render(
    <QueryClientProvider client={client}>
      <ShellContext.Provider value="display">
        <ThisScreenPage />
      </ShellContext.Provider>
    </QueryClientProvider>,
  );
}

const said = () => toasts.get().map((toast) => toast.message);

describe("Settings → This Screen (ADR 0035)", () => {
  it("says what this screen is on, shows, runs and can do", () => {
    draw();
    expect(screen.getByText("Wi-Fi: HomeNet, strong")).toBeTruthy();
    expect(screen.getByText("http://192.168.1.20:8080 · on another computer")).toBeTruthy();
    // Found on the network: the one way it still differs from a typed one (ADR 0042).
    expect(
      screen.getByText("Found on your network: this screen follows it if its address changes."),
    ).toBeTruthy();
    expect(screen.getByText("Sunroom Screen 0.13.0 · up to date")).toBeTruthy();
    for (const name of ["Change Wi-Fi", "Change Address", "Restart", "Shut Down", "Help"]) {
      expect(screen.getByRole("button", { name })).toBeTruthy();
    }
    expect(screen.getByRole("group", { name: "Rotation" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Updates" })).toBeTruthy();
    // A wall screen never quits, and has no update to install yet.
    expect(screen.queryByRole("button", { name: "Quit Sunroom Screen" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Update Now" })).toBeNull();
  });

  it("shows a computer only what it can do", () => {
    draw(
      piState({
        platform: "linux",
        session: "desktop",
        capabilities: ["restart", "shutdown", "update", "quit"],
        network: { kind: "wired", ssid: null, ip: "192.168.1.31", strength: null },
        sunroom: {
          url: "https://calendar.example.com",
          id: null,
          name: null,
          found: "typed",
          reachable: true,
        },
      }),
    );
    expect(screen.getByText("Wired")).toBeTruthy();
    expect(screen.getByText("https://calendar.example.com · on another computer")).toBeTruthy();
    expect(screen.queryByText(/^Found on your network/)).toBeNull();
    expect(screen.queryByRole("button", { name: "Change Wi-Fi" })).toBeNull();
    expect(screen.queryByRole("group", { name: "Rotation" })).toBeNull();
    // The connection, and nothing to open (ADR 0042).
    expect(screen.queryByRole("button", { name: "Open Network Settings" })).toBeNull();
    expect(screen.getByRole("button", { name: "Quit Sunroom Screen" })).toBeTruthy();
  });

  it("restarts at once, with the toast first", async () => {
    draw();
    fireEvent.click(screen.getByRole("button", { name: "Restart" }));
    await waitFor(() => {
      expect(said()).toEqual(["Restarting…"]);
    });
    expect(calls).toEqual([
      { method: "POST", path: "/api/screen/restart", body: null, header: "1" },
    ]);
  });

  it("asks before shutting down, because nothing brings it back", async () => {
    draw();
    fireEvent.click(screen.getByRole("button", { name: "Shut Down" }));
    const sheet = screen.getByRole("dialog", { name: "Shut Down This Screen?" });
    expect(
      within(sheet).getByText("It stays off until it’s unplugged and plugged back in."),
    ).toBeTruthy();
    fireEvent.click(within(sheet).getByRole("button", { name: "Keep It On" }));
    expect(calls).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "Shut Down" }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Shut Down This Screen?" })).getByRole("button", {
        name: "Shut Down",
      }),
    );
    await waitFor(() => {
      expect(said()).toEqual(["Shutting down…"]);
    });
    expect(calls.map((call) => call.path)).toEqual(["/api/screen/shutdown"]);
  });

  it("asks before leaving this Sunroom, by its name", async () => {
    draw();
    fireEvent.click(screen.getByRole("button", { name: "Change Address" }));
    const sheet = screen.getByRole("dialog", { name: "Use a Different Sunroom?" });
    expect(
      within(sheet).getByText(
        "This screen leaves The Sample Family’s Sunroom and looks for another. Its pairing is kept.",
      ),
    ).toBeTruthy();
    fireEvent.click(within(sheet).getByRole("button", { name: "Change Address" }));
    await waitFor(() => {
      expect(said()).toEqual(["Address changed. Looking for another Sunroom…"]);
    });
    expect(calls).toEqual([
      { method: "DELETE", path: "/api/screen/sunroom", body: null, header: "1" },
    ]);
    // Nothing restarts the browser any more (ADR 0042): the wall goes to the agent's Find page.
    await waitFor(
      () => {
        expect(openScreenPage).toHaveBeenCalledWith("/find");
      },
      { timeout: 3000 }, // a moment after the toast
    );
  });

  it("offers an update that's ready, and says it's under way", async () => {
    draw(
      piState({
        update: {
          check: "nightly",
          state: "available",
          installed: "0.13.0",
          latest: "0.14.0",
          checked_at: null,
          message: null,
          sunroom_outdated: false,
        },
      }),
    );
    expect(screen.getByText("0.14.0 is ready")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Update Now" }));
    await waitFor(() => {
      expect(said()).toEqual(["Updating… this takes a few minutes"]);
    });
    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual(["POST /api/screen/update"]);
  });

  it("updates the Sunroom on this screen too, when it runs here and is behind", async () => {
    draw(
      piState({
        capabilities: ["restart", "shutdown", "update", "update_sunroom"],
        sunroom: {
          url: "http://localhost:8080",
          id: "00000000-0000-7000-8000-0000000000e1",
          name: "The Sample Family",
          found: "local",
          reachable: true,
        },
        update: {
          check: "nightly",
          state: "up_to_date",
          installed: "0.14.0",
          latest: "0.14.0",
          checked_at: null,
          message: null,
          sunroom_outdated: true,
        },
      }),
    );
    expect(screen.getByText("http://localhost:8080 · on this computer")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Update Sunroom Too" }));
    await waitFor(() => {
      expect(said()).toEqual(["Updating Sunroom… this takes a few minutes"]);
    });
    expect(calls.map((call) => `${call.method} ${call.path}`)).toEqual([
      "POST /api/screen/update-sunroom",
    ]);
  });

  it("turns the picture, and keeps the update setting", async () => {
    draw();
    fireEvent.click(screen.getByRole("button", { name: "Portrait, left" }));
    fireEvent.click(screen.getByRole("button", { name: "Off" }));
    await waitFor(() => {
      expect(calls.length).toBeGreaterThanOrEqual(2);
    });
    expect(calls.slice(0, 2)).toEqual([
      { method: "PUT", path: "/api/screen/display", body: { rotation: 90 }, header: "1" },
      { method: "PUT", path: "/api/screen/update-policy", body: { check: "off" }, header: "1" },
    ]);
  });

  it("joins a Wi-Fi network with its password, and says why when it can't", async () => {
    draw();
    fireEvent.click(screen.getByRole("button", { name: "Change Wi-Fi" }));
    const pick = await screen.findByRole("button", { name: /^SampleStreet-5G, fair signal/ });
    fireEvent.click(pick);
    const password = screen.getByLabelText("Password");
    answers["POST /api/screen/wifi"] = {
      status: 409,
      body: {
        error: {
          code: "device",
          message: "That password didn't work for SampleStreet-5G. Check it and try again.",
        },
      },
    };
    fireEvent.change(password, { target: { value: "wrong-password" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(
      await screen.findByText(
        "That password didn't work for SampleStreet-5G. Check it and try again.",
      ),
    ).toBeTruthy();
    delete answers["POST /api/screen/wifi"];
    fireEvent.change(password, { target: { value: "sample-pass-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() => {
      expect(said()).toEqual(["Joined SampleStreet-5G"]);
    });
    expect(calls.filter((call) => call.method === "POST")).toEqual([
      {
        method: "POST",
        path: "/api/screen/wifi",
        body: { ssid: "SampleStreet-5G", password: "wrong-password" },
        header: "1",
      },
      {
        method: "POST",
        path: "/api/screen/wifi",
        body: { ssid: "SampleStreet-5G", password: "sample-pass-1" },
        header: "1",
      },
    ]);
  });

  it("says plainly when the screen doesn't answer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
    draw();
    fireEvent.click(screen.getByRole("button", { name: "Restart" }));
    await waitFor(() => {
      expect(said()).toEqual(["This screen didn’t answer. Try again in a moment."]);
    });
  });

  it("names a household's Sunroom as people would", () => {
    expect(sunroomName("The Sample Family")).toBe("The Sample Family’s Sunroom");
    expect(sunroomName("The Joneses")).toBe("The Joneses’ Sunroom");
    expect(sunroomName("Home")).toBe("Sunroom");
    expect(sunroomName(null)).toBe("Sunroom");
  });
});
