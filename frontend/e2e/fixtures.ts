import {
  devices,
  expect,
  test as base,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";

export const PASSWORD = "e2e-household-passphrase";
export const PIN = "2468";
const CSRF = { "X-Sunroom": "1" };

/**
 * Every test: a server that has never been set up, and a guard that fails the test on any CSP
 * violation, uncaught page error or browser dialog ("never an error wall"), on every page of the
 * test, the wall screen's included.
 */
export const test = base.extend<{
  cspGuard: boolean;
  guard: undefined;
  watch: (page: Page) => Promise<void>;
}>({
  cspGuard: [true, { option: true }],
  watch: [
    async ({ cspGuard }, use) => {
      const problems: string[] = [];
      await use(async (page: Page) => {
        page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
        page.on("dialog", (dialog) => {
          problems.push(`dialog: ${dialog.message()}`);
          void dialog.dismiss();
        });
        // Awaited: a test that skips itself at once ended under the pending call ("Test ended.").
        await page.addInitScript(() => {
          document.addEventListener("securitypolicyviolation", (event) => {
            console.error(`CSP violation: ${event.violatedDirective} ${event.blockedURI}`);
          });
        });
        page.on("console", (message) => {
          if (cspGuard && message.text().startsWith("CSP violation")) problems.push(message.text());
        });
      });
      expect(problems, "no CSP violations, page errors or dialogs").toEqual([]);
    },
    { scope: "test" },
  ],
  guard: [
    async ({ page, request, watch }, use) => {
      await resetServer(request);
      await watch(page);
      await use(undefined);
    },
    { auto: true },
  ],
});

export { expect };

export async function resetServer(request: APIRequestContext): Promise<void> {
  const response = await request.post("/api/_test/reset", { headers: CSRF });
  expect(response.status()).toBe(204);
}

/** The synthetic Sample Family, set up through the test API (fake data only). */
export async function seed(
  request: APIRequestContext,
  options: { pin?: string } = {},
): Promise<void> {
  const response = await request.post("/api/_test/seed", {
    headers: CSRF,
    data: options.pin ? { pin: options.pin } : {},
  });
  expect(response.status()).toBe(204);
}

/** A phone (390 × 844, touch) in its own browser context: its own cookies. */
export async function phone(
  browser: Browser,
  watch: (page: Page) => Promise<void>,
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    isMobile: true,
    // A phone's own words, so the server knows it for one (Settings → Devices, ADR 0032).
    userAgent: devices["Pixel 7"].userAgent,
    baseURL: "http://127.0.0.1:4173",
    timezoneId: "America/New_York",
    locale: "en-US",
  });
  const page = await context.newPage();
  await watch(page);
  return { context, page };
}

/** The wall screen (1920 × 1080, touch) in its own context. */
export async function wall(
  browser: Browser,
  watch: (page: Page) => Promise<void>,
  viewport = { width: 1920, height: 1080 },
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({
    viewport,
    hasTouch: true,
    baseURL: "http://127.0.0.1:4173",
    timezoneId: "America/New_York",
    locale: "en-US",
  });
  const page = await context.newPage();
  await watch(page);
  return { context, page };
}

/** Sign a phone in with the household password, and pick a person if asked. */
export async function signInPhone(page: Page, name = "Ana"): Promise<void> {
  await page.goto("/sign-in");
  await page.getByLabel("Household password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page.getByRole("heading", { name: "Who’s using this device?" })).toBeVisible();
  // Anchored: on a laptop the Today panel beside it can name the person too ("Pizza night Ana
  // cooks" on the seed's Fridays).
  await page.getByRole("button", { name: new RegExp(`^${name}`) }).click();
  // On a laptop the Today panel shows beside Who's using this, too: wait for the address, then
  // for the question to go. Not for "Up next", which only shows while events are still to come.
  await page.waitForURL((url) => url.pathname === "/");
  await expect(page.getByRole("heading", { name: "Who’s using this device?" })).toBeHidden();
}

/** Pair a wall screen through the API with the household password, in its own context. */
export async function pairWall(page: Page): Promise<void> {
  const response = await page.request.post("/api/auth/kiosk/pair-with-password", {
    headers: CSRF,
    data: { password: PASSWORD, label: "Wall screen" },
  });
  expect(response.status()).toBe(200);
}

/** Pick one of the board's views from the wall header's View menu (ADR 0042). */
export async function pickView(page: Page, view: string): Promise<void> {
  await page
    .getByRole("banner")
    .getByRole("button", { name: /^View: / })
    .click();
  await page
    .getByRole("menu", { name: "View" })
    .getByRole("menuitemradio", { name: view, exact: true })
    .click();
}

/**
 * Wait until every finite animation has ended, so a check sees the final look. Headless Chromium
 * draws no frame until something asks for one, and a transition (even Reduce Motion's 0.01 ms)
 * holds its starting value until a frame comes. A theme change then settles one level of the page
 * per frame, as each child's inherited color starts its own transition: so ask for frames until
 * nothing is left running.
 */
export async function settled(page: Page): Promise<void> {
  await page.evaluate(async () => {
    const frame = () =>
      new Promise<void>((resolve) => {
        requestAnimationFrame(() => {
          resolve();
        });
      });
    for (let round = 0; round < 60; round++) {
      await frame();
      // Not the Hours grid's now line, which glides over a whole minute.
      const running = document.getAnimations().filter((animation) => {
        const end = animation.effect?.getComputedTiming().endTime;
        return (
          typeof end === "number" &&
          Number.isFinite(end) &&
          end <= 10_000 &&
          animation.playState === "running"
        );
      });
      if (!running.length) return;
      await Promise.all(running.map((animation) => animation.finished.catch(() => undefined)));
    }
  });
}

/**
 * A scripted calendar account (the test server's stand-in for Apple or Google) with one
 * calendar, "School", synced and (unless `mapped` is false) mapped: Settings → Calendars &
 * Accounts then shows a real row. `request` must be a parent's (a signed-in phone's
 * `page.request`).
 */
export async function scriptedAccount(
  request: APIRequestContext,
  { mapped = true }: { mapped?: boolean } = {},
): Promise<string> {
  const created = await request.post("/api/calendar-sync/_test/fake", { headers: CSRF });
  expect(created.status()).toBe(201);
  const { id } = (await created.json()) as { id: string };
  const scripted = await request.put(`/api/calendar-sync/_test/fake/${id}`, {
    headers: CSRF,
    data: { calendars: [["school", "School", false]] },
  });
  expect(scripted.status()).toBe(200);
  await request.post(`/api/calendar-sync/accounts/${id}/sync`, { headers: CSRF });
  let calendar = "";
  await expect(async () => {
    const accounts = (await (await request.get("/api/calendar-sync/accounts")).json()) as {
      id: string;
      calendars: { id: string }[];
    }[];
    calendar = accounts.find((a) => a.id === id)?.calendars[0]?.id ?? "";
    expect(calendar).not.toBe("");
  }).toPass({ timeout: 10_000 });
  if (!mapped) return id;
  const mapping = await request.put(`/api/calendar-sync/accounts/${id}/calendars/${calendar}`, {
    headers: CSRF,
    data: { mapped: true },
  });
  expect(mapping.status()).toBe(200);
  return id;
}
