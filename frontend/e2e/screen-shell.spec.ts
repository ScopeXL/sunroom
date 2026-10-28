/**
 * The screen's own pages (ADR 0035, docs/M7.md T5; Welcome's two ways on, ADR 0038), served by
 * Sunroom Screen's agent in --fake mode on 127.0.0.1:4174 (scripts/e2e-server.sh): a pretend
 * screen with three Wi-Fi networks, which "finds" this test server and a made-up older Sunroom,
 * and whose Run Sunroom Here "starts" this test server. Setting up a fresh screen both ways, a
 * typed address, the Wi-Fi step, Can't Reach going back by itself, and This Screen's twin; axe,
 * tap targets and the CSP guard on every page. Synthetic data only.
 */
import type { APIRequestContext, Page } from "@playwright/test";

import { check } from "./checks";
import { expect, seed, test } from "./fixtures";

const AGENT = "http://127.0.0.1:4174";
const SUNROOM = "http://127.0.0.1:4173";
const CHANGE = { "X-Sunroom-Screen": "1" };

test.beforeEach(async ({ request }) => {
  const name = test.info().project.name;
  test.skip(
    !name.startsWith("display") && name !== "desktop",
    "a screen's own pages: the wall, and a computer for Quit",
  );
  const reset = await request.post(`${AGENT}/api/screen/_test/reset`, { headers: CHANGE });
  expect(reset.status()).toBe(204);
  if (name === "desktop") await fake(request, { kind: "desktop" });
});

async function fake(request: APIRequestContext, data: Record<string, unknown>): Promise<void> {
  const response = await request.post(`${AGENT}/api/screen/_test/fake`, {
    headers: CHANGE,
    data,
  });
  expect(response.status()).toBe(204);
}

function toast(page: Page, message: string) {
  return page.locator("[data-toast]").filter({ hasText: message });
}

test("a fresh screen finds the Sunroom on its network and opens it", async ({ page, request }) => {
  test.slow(); // axe on three pages
  await seed(request);
  await page.goto(`${AGENT}/`);
  await expect(page.getByRole("heading", { name: "Sunroom", level: 1 })).toBeVisible();
  const ways = page.getByRole("radiogroup", { name: "Where will your family’s Sunroom run?" });
  await expect(ways.getByRole("radio", { name: "On This Computer" })).toBeChecked();
  const elsewhere = ways.getByRole("radio", { name: "Connect to a Sunroom" });
  await expect(elsewhere).toContainText("Your family already runs Sunroom somewhere else.");
  await elsewhere.click();
  await expect(elsewhere).toBeChecked();
  await check(page, "Welcome");
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.getByRole("heading", { name: "Where Is Your Sunroom?" })).toBeVisible();
  const network = page.getByRole("region", { name: "On Your Network" });
  await expect(network.getByText("Sample Family’s Sunroom")).toBeVisible();
  await expect(network.getByText(new RegExp(`^${SUNROOM} · version `))).toBeVisible();
  // An older Sunroom, from before /api/discover, by its version only.
  await expect(network.getByText("A Sunroom", { exact: true })).toBeVisible();
  await expect(network.getByText("http://198.51.100.21:8080 · version 0.11.0")).toBeVisible();
  await expect(network.getByRole("button", { name: "Look Again" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Somewhere Else" })).toBeVisible();
  await check(page, "Where Is Your Sunroom?");

  await network.getByRole("button", { name: "Use This Sunroom" }).first().click();
  // Opening it: the wall's own address, with this screen's dimmer and agent.
  await page.waitForURL(
    (url) =>
      url.origin === SUNROOM &&
      url.pathname === "/display" &&
      url.searchParams.get("screen") === "4174",
  );
  await expect(page.getByRole("heading", { name: "Pair This Screen" })).toBeVisible();
  const saved = (await (await request.get(`${AGENT}/api/screen`)).json()) as {
    sunroom: { url: string; found: string };
  };
  expect(saved.sunroom).toMatchObject({ url: SUNROOM, found: "discovered" });
});

test("a fresh screen runs Sunroom on this computer and opens it", async ({ page, request }) => {
  await seed(request);
  await fake(request, { run: "hold" });
  await page.goto(`${AGENT}/`);
  // Where Sunroom can run here, this computer is chosen from the start: Continue sets it up.
  await expect(page.getByRole("radio", { name: "On This Computer" })).toBeChecked();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Setting Up Sunroom" })).toBeVisible();
  await expect(page.getByRole("main").getByRole("status")).toContainText("Downloading Sunroom…");
  await check(page, "Setting Up Sunroom");

  // It stops: the page says why, and Try Again runs it once more, through to Sunroom.
  await request.post(`${AGENT}/api/screen/_test/reset`, { headers: CHANGE });
  if (test.info().project.name === "desktop") await fake(request, { kind: "desktop" });
  await fake(request, { run: "fail" });
  await page.goto(`${AGENT}/here`);
  await expect(page.getByRole("alert")).toHaveText(
    "Sunroom didn't download. Check this computer's internet connection, then try again.",
  );
  await fake(request, { run: "ok" });
  await page.getByRole("button", { name: "Try Again" }).click();
  await page.waitForURL(
    (url) =>
      url.origin === SUNROOM &&
      url.pathname === "/display" &&
      url.searchParams.get("screen") === "4174",
  );
  await expect(page.getByRole("heading", { name: "Pair This Screen" })).toBeVisible();
  const saved = (await (await request.get(`${AGENT}/api/screen`)).json()) as {
    sunroom: { url: string; found: string };
  };
  expect(saved.sunroom).toMatchObject({ url: SUNROOM, found: "local" });
});

test("a typed address is checked as the field is left, and said plainly when it isn't a Sunroom", async ({
  page,
  request,
}) => {
  await seed(request);
  await page.goto(`${AGENT}/find`);
  const elsewhere = page.getByRole("region", { name: "Somewhere Else" });
  const field = elsewhere.getByLabel(/^Sunroom address/);
  await expect(field).toHaveValue("");
  const checkButton = elsewhere.locator("form button[type=submit]");
  await expect(checkButton).toHaveText("Check Address");
  // Typed, then the field is left (a tap anywhere else): the check runs by itself.
  const leaveWith = async (address: string) => {
    await field.fill(address);
    await page.getByRole("heading", { name: "Where Is Your Sunroom?" }).click();
  };
  await leaveWith("http://127.0.0.1:9");
  await expect(elsewhere.getByRole("status")).toHaveText("Can't reach that address from here.");
  await expect(checkButton).toHaveText("Not Found");
  // The agent itself answers, and isn't a Sunroom; ↵ checks too.
  await field.fill(AGENT);
  await expect(checkButton).toHaveText("Check Address");
  await field.press("Enter");
  await expect(elsewhere.getByRole("status")).toHaveText(
    "That address isn't a Sunroom. Check it and try again.",
  );
  await expect(elsewhere.getByRole("button", { name: "Use This Sunroom" })).toHaveCount(0);
  await leaveWith(SUNROOM);
  await expect(elsewhere.getByRole("status")).toHaveText("That’s Sample Family’s Sunroom.");
  await expect(checkButton).toHaveText("Found");
  await check(page, "Where Is Your Sunroom? (found)");
  await elsewhere.getByRole("button", { name: "Use This Sunroom" }).click();
  await page.waitForURL((url) => url.origin === SUNROOM && url.pathname === "/display");
  const saved = (await (await request.get(`${AGENT}/api/screen`)).json()) as {
    sunroom: { found: string };
  };
  expect(saved.sunroom.found).toBe("typed");
});

test("a screen with no network starts by joining Wi-Fi on the wall's keyboard", async ({
  page,
  request,
}) => {
  test.skip(test.info().project.name === "desktop", "a computer joins Wi-Fi itself");
  await fake(request, { offline: true });
  await page.goto(`${AGENT}/`);
  await page.getByRole("radio", { name: "Connect to a Sunroom" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Connect to Wi-Fi" })).toBeVisible();
  await check(page, "Connect to Wi-Fi");
  await page.getByRole("button", { name: /^SampleStreet-5G, fair signal/ }).click();
  await expect(page.getByRole("heading", { name: "SampleStreet-5G" })).toBeVisible();
  await page.getByLabel("Password").click();
  const keys = page.getByRole("group", { name: "On-screen keyboard" });
  await expect(keys).toBeVisible();
  for (const letter of "samplestreet") {
    await keys.getByRole("button", { name: new RegExp(`^${letter}$`, "i") }).click();
  }
  await page.getByRole("button", { name: "Connect" }).click();
  await expect(toast(page, "Joined SampleStreet-5G")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Where Is Your Sunroom?" })).toBeVisible();
});

test("Can't Reach waits with every way out, and goes back to Sunroom by itself", async ({
  page,
  request,
}) => {
  await seed(request);
  // An address that refuses at once: the screen can't reach its Sunroom.
  await fake(request, { sunroom: "http://127.0.0.1:9" });
  await page.goto(`${AGENT}/cant-reach`);
  await expect(page.getByRole("heading", { name: "Can’t Reach Sunroom" })).toBeVisible();
  await expect(page.getByText("Trying again every 10 seconds…")).toBeVisible();
  const desktop = test.info().project.name === "desktop";
  for (const name of ["Try Again", "Change Address", "Restart"]) {
    await expect(page.getByRole("button", { name, exact: true })).toBeVisible();
  }
  await expect(page.getByRole("button", { name: "Wi-Fi", exact: true })).toHaveCount(
    desktop ? 0 : 1,
  );
  // The computer joins its network itself: nothing here opens its settings (ADR 0042).
  await expect(page.getByRole("button", { name: "Open Network Settings" })).toHaveCount(0);
  await check(page, "Can't Reach");
  await page.getByRole("button", { name: "Try Again" }).click();
  await expect(page.getByText("Can't reach that address from here.")).toBeVisible();
  // Sunroom answers again: the page goes back to it with nobody touching it.
  await fake(request, { sunroom: SUNROOM });
  await page.waitForURL((url) => url.origin === SUNROOM && url.pathname === "/display");
});

test("This Screen's twin works when Sunroom can't load, and Quit shows on a computer", async ({
  page,
  request,
}) => {
  await fake(request, { sunroom: "http://127.0.0.1:9" });
  await page.goto(`${AGENT}/settings`);
  await expect(page.getByRole("heading", { name: "This Screen", level: 1 })).toBeVisible();
  await expect(page.getByText("http://127.0.0.1:9 · on another computer")).toBeVisible();
  const desktop = test.info().project.name === "desktop";
  await expect(page.getByRole("button", { name: "Quit Sunroom Screen" })).toHaveCount(
    desktop ? 1 : 0,
  );
  // A computer turns its picture too, as a Pi does (ADR 0042).
  await expect(page.getByRole("group", { name: "Rotation" })).toHaveCount(1);
  await check(page, "This Screen (the screen's own page)");
  await page.getByRole("button", { name: "Restart" }).click();
  await expect(toast(page, "Restarting…")).toBeVisible();
  // Back to Sunroom: it can't be reached, so the page says so rather than going nowhere.
  await page.getByRole("button", { name: "Back to Sunroom" }).click();
  await expect(page.getByRole("heading", { name: "Can’t Reach Sunroom" })).toBeVisible();
  // Change Address asks, then looks for another.
  await page.getByRole("button", { name: "Change Address" }).click();
  const asking = page.getByRole("dialog", { name: "Use a Different Sunroom?" });
  await asking.getByRole("button", { name: "Change Address" }).click();
  await expect(page.getByRole("heading", { name: "Where Is Your Sunroom?" })).toBeVisible();
});
