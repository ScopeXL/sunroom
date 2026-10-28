/**
 * Settings → This Screen on the wall (ADR 0035, docs/M7.md T4): a wall run by Sunroom Screen
 * opens /display?screen=7800, and its parent-only page talks to the agent on 127.0.0.1:7800.
 * Here the agent is pretend, answered by page.route with the CORS headers the real one sends.
 * The page and its sheets, Restart, Shut Down's question, Wi-Fi typed on the wall's keyboard,
 * Rotation, Update Now's progress, and no page at all without ?screen=. Synthetic data only.
 */
import type { Page, Route } from "@playwright/test";

import { check } from "./checks";
import { expect, pairWall, PASSWORD, PIN, seed, test } from "./fixtures";

const AGENT = "http://127.0.0.1:7800";
const ORIGIN = "http://127.0.0.1:4173";
const CORS = {
  "Access-Control-Allow-Origin": ORIGIN,
  "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE",
  "Access-Control-Allow-Headers": "Content-Type, X-Sunroom-Screen",
  "Access-Control-Allow-Private-Network": "true",
  Vary: "Origin",
};

test.beforeEach(() => {
  test.skip(!test.info().project.name.startsWith("display"), "a wall screen's own page");
});

function state(overrides: Record<string, unknown> = {}): Record<string, unknown> {
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
      state: "available",
      installed: "0.13.0",
      latest: "0.14.0",
      checked_at: null,
      message: null,
    },
    display: { rotation: 0, brightness_method: "ddc" },
    open_url: `${ORIGIN}/display?dimmer=screen&screen=7800`,
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

/** The pretend agent: what it was asked, and its state as those asks change it. */
class FakeAgent {
  calls: string[] = [];
  bodies: Record<string, unknown> = {};
  current = state();
  updating = false;

  async install(page: Page): Promise<void> {
    await page.route(`${AGENT}/api/screen**`, (route) => this.answer(route));
  }

  private async answer(route: Route): Promise<void> {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const method = request.method();
    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers: CORS });
      return;
    }
    if (path === "/api/screen/events") {
      // A short reconnect, so each new connection carries what changed (the real stream is
      // one long connection).
      const frames = [`retry: 300\n\n`, `event: state\ndata: ${JSON.stringify(this.current)}\n\n`];
      if (this.updating) {
        frames.push(`event: update.progress\ndata: {"percent":40,"step":"Installing…"}\n\n`);
      }
      await route.fulfill({
        status: 200,
        headers: { ...CORS, "Content-Type": "text/event-stream" },
        body: frames.join(""),
      });
      return;
    }
    this.calls.push(`${method} ${path}`);
    const body = request.postData();
    if (body) this.bodies[`${method} ${path}`] = JSON.parse(body) as unknown;
    const json = (status: number, data: unknown) =>
      route.fulfill({
        status,
        headers: { ...CORS, "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
    if (method === "GET" && path === "/api/screen") return json(200, this.current);
    if (method === "GET" && path === "/api/screen/wifi") return json(200, { networks: NETWORKS });
    if (method === "POST" && path === "/api/screen/wifi") {
      this.current = state({
        network: { kind: "wifi", ssid: "SampleStreet-5G", ip: "192.168.1.30", strength: 54 },
      });
      return json(200, { networks: NETWORKS });
    }
    if (method === "PUT" && path === "/api/screen/display") {
      const rotation = (JSON.parse(body ?? "{}") as { rotation: number }).rotation;
      this.current = state({ display: { rotation, brightness_method: "ddc" } });
      return json(200, this.current);
    }
    if (method === "POST" && path === "/api/screen/update") this.updating = true;
    if (method === "GET" && path === "/api/screen/about") {
      return json(200, {
        version: "0.13.0",
        platform: "pi",
        model: "Raspberry Pi 5 Model B",
        system: "Debian GNU/Linux 13 (trixie)",
        browser: "Chromium",
        hostname: "sunroom",
        ip: "192.168.1.30",
        uptime_s: 7200,
        sunroom_url: "http://192.168.1.20:8080",
        log: ["Oct 20 09:00:00 Sunroom at http://192.168.1.20:8080 answers."],
      });
    }
    return json(202, { ok: true });
  }
}

/** Settings opens on This Screen (ADR 0039): first, in a box of its own, apart from the
 * household's pages under the household's Sunroom. */
async function openThisScreen(page: Page): Promise<void> {
  await page.getByRole("button", { name: "Settings" }).click();
  const pin = page.getByRole("dialog", { name: "Parent PIN" });
  for (const digit of PIN) await pin.getByRole("button", { name: digit, exact: true }).click();
  await expect(pin).toBeHidden();
  await expect(page.getByRole("heading", { name: "This Screen", level: 2 })).toBeVisible();
  await expect(page.getByText("These settings are for this screen only")).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Settings" });
  const link = nav.getByRole("link", { name: "This Screen", exact: true });
  await expect(nav.getByRole("link").first()).toHaveAccessibleName("This Screen");
  await expect(link).toHaveAttribute("aria-current", "page");
  await expect(link).toHaveAccessibleDescription("Network, updates and power");
  await expect(nav.getByText("Sample Family’s Sunroom")).toBeVisible();
}

function toast(page: Page, message: string) {
  return page.locator("[data-toast]").filter({ hasText: message });
}

test("This Screen restarts, shuts down, joins Wi-Fi, turns and updates the screen", async ({
  page,
  request,
}) => {
  test.slow(); // two axe passes and a sheet's typing
  await seed(request, { pin: PIN });
  await pairWall(page);
  const agent = new FakeAgent();
  await agent.install(page);
  await page.goto("/display?dimmer=screen&screen=7800");
  await expect(page.getByRole("region", { name: "This Week" })).toBeVisible();
  await openThisScreen(page);

  await expect(page.getByText("Wi-Fi: HomeNet, strong")).toBeVisible();
  await expect(page.getByText("http://192.168.1.20:8080 · found on your network")).toBeVisible();
  await expect(page.getByText("0.14.0 is ready")).toBeVisible();
  await check(page, "This Screen");

  // Restart: the toast, and the agent asked (it waits a moment before it acts).
  await page.getByRole("button", { name: "Restart" }).click();
  await expect(toast(page, "Restarting…")).toBeVisible();
  expect(agent.calls).toContain("POST /api/screen/restart");

  // Shut Down asks first; Keep It On asks nothing of the screen.
  await page.getByRole("button", { name: "Shut Down" }).click();
  const shutDown = page.getByRole("dialog", { name: "Shut Down This Screen?" });
  await expect(shutDown).toBeVisible();
  await shutDown.getByRole("button", { name: "Keep It On" }).click();
  await expect(shutDown).toBeHidden();
  expect(agent.calls).not.toContain("POST /api/screen/shutdown");
  await page.getByRole("button", { name: "Shut Down" }).click();
  await shutDown.getByRole("button", { name: "Shut Down" }).click();
  await expect(toast(page, "Shutting down…")).toBeVisible();
  expect(agent.calls).toContain("POST /api/screen/shutdown");

  // Change Wi-Fi: the networks, then the password on the wall's own keyboard.
  await page.getByRole("button", { name: "Change Wi-Fi" }).click();
  const wifi = page.getByRole("dialog", { name: "Wi-Fi" });
  await wifi.getByRole("button", { name: /^SampleStreet-5G, fair signal/ }).click();
  const joining = page.getByRole("dialog", { name: "SampleStreet-5G" });
  await joining.getByLabel("Password").click();
  const keys = joining.getByRole("group", { name: "On-screen keyboard" });
  await expect(keys).toBeVisible();
  await check(page, "This Screen's Wi-Fi sheet");
  for (const letter of "samplestreet") {
    await keys.getByRole("button", { name: new RegExp(`^${letter}$`, "i") }).click();
  }
  await expect(joining.getByLabel("Password")).toHaveValue("samplestreet");
  await joining.getByRole("button", { name: "Connect" }).click();
  await expect(toast(page, "Joined SampleStreet-5G")).toBeVisible();
  await expect(joining).toBeHidden();
  expect(agent.bodies["POST /api/screen/wifi"]).toEqual({
    ssid: "SampleStreet-5G",
    password: "samplestreet",
  });
  await expect(page.getByText("Wi-Fi: SampleStreet-5G, fair")).toBeVisible();

  // Rotation turns it at once.
  const rotation = page.getByRole("group", { name: "Rotation" });
  await rotation.getByRole("button", { name: "Portrait, left" }).click();
  await expect(rotation.getByRole("button", { name: "Portrait, left" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(agent.bodies["PUT /api/screen/display"]).toEqual({ rotation: 90 });

  // Update Now: the toast, then the progress the agent streams.
  await page.getByRole("button", { name: "Update Now" }).click();
  await expect(toast(page, "Updating… this takes a few minutes")).toBeVisible();
  await expect(page.getByText(/Updating…\s*40%/)).toBeVisible();

  // Help: what the screen runs, for whoever helps the family.
  await page.getByRole("button", { name: "Help", exact: true }).click();
  const help = page.getByRole("dialog", { name: "About This Screen" });
  await expect(help.getByText("Raspberry Pi 5 Model B")).toBeVisible();
  await expect(help.getByText("Having trouble? Settings → Support Sunroom.")).toBeVisible();
  await help.getByRole("button", { name: "Close" }).last().click();

  // Change Address: the agent forgets it and restarts nothing (ADR 0042), so the wall goes to
  // the agent's own Where Is Your Sunroom? by itself.
  await page.route(`${AGENT}/find`, (route) =>
    route.fulfill({ contentType: "text/html", body: "<title>Where Is Your Sunroom?</title>" }),
  );
  await page.getByRole("button", { name: "Change Address" }).click();
  const different = page.getByRole("dialog", { name: "Use a Different Sunroom?" });
  await different.getByRole("button", { name: "Change Address" }).click();
  await expect(toast(page, "Address changed. Looking for another Sunroom…")).toBeVisible();
  expect(agent.calls).toContain("DELETE /api/screen/sunroom");
  await page.waitForURL(`${AGENT}/find`);
});

test("a wall paired on the screen has Sunroom Screen keep the pairing at once (ADR 0040)", async ({
  page,
  request,
}) => {
  await seed(request, { pin: PIN });
  const agent = new FakeAgent();
  await agent.install(page);
  await page.goto("/display?dimmer=screen&screen=7800");
  await page.getByRole("button", { name: "Type the household password here instead" }).click();
  await page.getByLabel("Household password").fill(PASSWORD);
  await page.getByRole("button", { name: "Pair This Screen" }).click();
  await expect(page.getByRole("heading", { name: "Name this screen" })).toBeVisible();
  await expect.poll(() => agent.calls).toContain("POST /api/screen/keep-pairing");
});

test("a wall opened without ?screen= has no This Screen, and asks no agent", async ({
  page,
  request,
}) => {
  await seed(request, { pin: PIN });
  await pairWall(page);
  const agent = new FakeAgent();
  await agent.install(page);
  await page.goto("/display");
  await expect(page.getByRole("region", { name: "This Week" })).toBeVisible();
  await page.getByRole("button", { name: "Settings" }).click();
  const pin = page.getByRole("dialog", { name: "Parent PIN" });
  for (const digit of PIN) await pin.getByRole("button", { name: digit, exact: true }).click();
  const pages = page.getByRole("navigation", { name: "Settings" });
  await expect(pages.getByRole("link", { name: "Display", exact: true })).toBeVisible();
  await expect(pages.getByRole("link", { name: "This Screen", exact: true })).toHaveCount(0);
  // Settings opens on Family, with no device box and no caption over the household's pages.
  await expect(page.getByRole("heading", { name: "Family", level: 2 })).toBeVisible();
  await expect(pages.getByText("Sample Family’s Sunroom")).toHaveCount(0);
  expect(agent.calls).toEqual([]);
});
