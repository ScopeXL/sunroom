/**
 * The Week board's Hours layout end to end (UX §4 "Week board, Hours layout", ADR 0028): the
 * whole day with nothing to scroll, Zoom in (with no scrollbar), Zoom out and Fit the day, a
 * drop that keeps the time, a tap that adds at a time, the now line under the day heads, and the
 * layout and zoom staying through two idle minutes. The server's clock reads Wednesday, October 7,
 * 2026, 10:00 AM in New York.
 * Synthetic data only.
 */
import type { Locator, Page } from "@playwright/test";

import { expect, pairWall, seed, settled, test } from "./fixtures";

const CSRF = { "X-Sunroom": "1" };
const WEDNESDAY_10AM = "2026-10-07T14:00:00Z";

test.beforeEach(async ({ request }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("display"), "the wall screen");
  const moved = await request.post("/api/_test/clock", {
    headers: CSRF,
    data: { set: WEDNESDAY_10AM },
  });
  expect(moved.status()).toBe(204);
  await seed(request);
});

function toast(page: Page, message: string): Locator {
  return page.locator("[data-toast]").filter({ hasText: message });
}

async function boxOf(
  locator: Locator,
): Promise<{ x: number; y: number; width: number; height: number }> {
  const box = await locator.boundingBox();
  if (!box) throw new Error("not on the page");
  return box;
}

/** A long press (the board's drag sensor waits 400 ms), then a slow move and a drop. */
async function drag(page: Page, from: Locator, to: Locator): Promise<void> {
  const start = await boxOf(from);
  const end = await boxOf(to);
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(600);
  await page.mouse.move(end.x + end.width / 2, end.y + end.height / 2, { steps: 12 });
  await page.mouse.up();
  // dnd-kit swallows clicks for 50 ms after a drop; a person never taps that fast.
  await page.waitForTimeout(100);
}

test("the Hours layout fits the day, zooms, keeps the time on a drop and adds at a tapped time", async ({
  page,
}) => {
  await pairWall(page);
  await page.goto("/display");
  const board = page.getByRole("region", { name: "This Week" });
  await expect(board).toBeVisible();
  // The layout is two icons in the header, beside the arrows; there is no bar over the days.
  await expect(board.getByRole("group", { name: "Zoom" })).toHaveCount(0);
  await page.getByRole("banner").getByRole("button", { name: "Hours", exact: true }).click();
  const grid = board.locator("[data-hours]");
  await expect(grid).toBeVisible();
  // No zoom is the default: the whole day, with nothing to zoom out of. The zoom sits on the
  // grid's own corner (ADR 0030), not in the header.
  const zoom = board.getByRole("group", { name: "Zoom" });
  const zoomIn = zoom.getByRole("button", { name: "Zoom in" });
  const zoomOut = zoom.getByRole("button", { name: "Zoom out" });
  const fitDay = zoom.getByRole("button", { name: "Fit the day" });
  const corner = await boxOf(zoom);
  const whole = await boxOf(grid);
  expect(corner.x + corner.width).toBeGreaterThan(whole.x + whole.width - 60);
  expect(corner.y + corner.height).toBeGreaterThan(whole.y + whole.height - 40);
  await expect(zoomIn).toBeEnabled();
  await expect(zoomOut).toBeDisabled();
  await expect(fitDay).toBeDisabled();
  // Fit the day first, then Zoom out and Zoom in (ADR 0032).
  expect(
    await zoom
      .getByRole("button")
      .evaluateAll((buttons) => buttons.map((button) => button.getAttribute("aria-label"))),
  ).toEqual(["Fit the day", "Zoom out", "Zoom in"]);

  // The whole day fits, and nothing scrolls.
  const wednesday = board.locator('[data-day="2026-10-07"] [data-day-body]');
  await expect(wednesday.locator("[data-now-line]")).toBeVisible();
  expect(await grid.evaluate((node) => node.scrollHeight - node.clientHeight)).toBeLessThanOrEqual(
    0,
  );
  const day = await boxOf(wednesday);
  const fit = day.height;
  // A one-hour event: a 56 px button holding a block as tall as its hour.
  const soccer = board.getByRole("button", {
    name: /^Soccer practice, 4:00 to 5:00 PM, .*Thursday/,
  });
  const block = soccer.locator(":scope > span");
  expect(Math.round((await boxOf(soccer)).height)).toBe(56);
  expect(Math.abs((await boxOf(block)).height - fit / 24)).toBeLessThanOrEqual(1.5);
  // The now line at 10:00, ten 24ths of the way down today.
  const nowLine = wednesday.locator("[data-now-line]");
  expect(Math.abs((await boxOf(nowLine)).y - day.y - (10 / 24) * fit)).toBeLessThanOrEqual(2);
  await expect(nowLine.locator(".now-label")).toHaveText(/^now 10:0\d$/);

  // Zoom in: half again as tall, scrolled so now (10:00) sits a third of the way down.
  await zoomIn.click();
  await expect
    .poll(async () => Math.abs((await boxOf(wednesday)).height - 1.5 * fit))
    .toBeLessThanOrEqual(1);
  const scrolled = () => grid.evaluate((node) => node.scrollTop);
  expect(Math.abs((await scrolled()) - ((10 / 24) * 1.5 * fit - fit / 3))).toBeLessThanOrEqual(2);
  await expect(zoomOut).toBeEnabled();
  await expect(fitDay).toBeEnabled();
  // It scrolls with no scrollbar, and none is kept room for (ADR 0033: on the wall screen
  // the overlay bar flashed once a minute while a resting grid followed now). The width only
  // tells where bars are classic (Linux); a Mac's headless Chromium draws overlay ones.
  expect(
    await grid.evaluate((node) => getComputedStyle(node).getPropertyValue("scrollbar-width")),
  ).toBe("none");
  expect(
    await grid.evaluate((node) => node.getBoundingClientRect().width - node.clientWidth),
  ).toBeLessThan(1);
  // The control stays put while the hours scroll under it.
  const at = await scrolled();
  await grid.evaluate((node) => {
    node.scrollBy(0, 80);
  });
  expect(await scrolled()).not.toBe(at);
  expect((await boxOf(zoom)).y).toBe(corner.y);
  await grid.evaluate((node, top) => {
    node.scrollTo(0, top);
  }, at);
  // Again: 2.25 times the day, and the minute in the middle of the view stays put (12:40).
  await zoomIn.click();
  await expect
    .poll(async () => Math.abs((await boxOf(wednesday)).height - 2.25 * fit))
    .toBeLessThanOrEqual(1);
  expect(Math.abs((await scrolled()) - 0.6875 * fit)).toBeLessThanOrEqual(3);
  expect(Math.abs((await boxOf(block)).height - (2.25 * fit) / 24)).toBeLessThanOrEqual(1.5);
  // Zoom out steps back the same way.
  await zoomOut.click();
  await expect
    .poll(async () => Math.abs((await boxOf(wednesday)).height - 1.5 * fit))
    .toBeLessThanOrEqual(1);
  // Fit the day: the whole day again, nothing to scroll, nothing left to zoom out of.
  await fitDay.click();
  await expect
    .poll(async () => Math.abs((await boxOf(wednesday)).height - fit))
    .toBeLessThanOrEqual(1);
  expect(await grid.evaluate((node) => node.scrollHeight - node.clientHeight)).toBeLessThanOrEqual(
    0,
  );
  await expect(zoomOut).toBeDisabled();
  await expect(fitDay).toBeDisabled();
  // A laptop's shortcut: ctrl + wheel (a trackpad pinch sends the same) zooms like the buttons.
  await page.mouse.move(day.x + day.width / 2, day.y + fit / 2);
  await page.keyboard.down("Control");
  await page.mouse.wheel(0, -120);
  await page.keyboard.up("Control");
  await expect
    .poll(async () => Math.abs((await boxOf(wednesday)).height - 1.5 * fit))
    .toBeLessThanOrEqual(1);
  await fitDay.click();
  // As far in as it goes: a 15-minute event would fill a full chip, and Zoom in stops.
  let taps = 0;
  while (await zoomIn.isEnabled()) {
    await zoomIn.click();
    taps += 1;
    expect(taps).toBeLessThan(12);
  }
  expect(taps).toBeGreaterThanOrEqual(3);
  expect((await boxOf(block)).height / 4).toBeGreaterThanOrEqual(72 - 1);
  await fitDay.click();
  // Three taps in for the rest: an hour is about a chip and a half tall.
  for (let tap = 0; tap < 3; tap++) await zoomIn.click();
  await expect
    .poll(async () => Math.abs((await boxOf(block)).height - (3.375 * fit) / 24))
    .toBeLessThanOrEqual(1.5);

  // A drop on another day keeps the time of day.
  const vet = board.getByRole("button", { name: /^Vet, 9:00 to 9:30 AM, Ana, Wednesday/ });
  await vet.scrollIntoViewIfNeeded();
  await drag(page, vet, board.locator('[data-day="2026-10-09"] h2'));
  await expect(toast(page, "Moved Vet to Fri")).toBeVisible();
  await expect(toast(page, "Moved Vet to Fri").getByRole("button", { name: "Undo" })).toBeVisible();
  await expect(
    board.getByRole("button", { name: /^Vet, 9:00 to 9:30 AM, Ana, Friday October 9/ }),
  ).toBeAttached();

  // A tap on an empty spot adds an event at that time, on that day.
  const friday = await boxOf(board.locator('[data-day="2026-10-09"] [data-day-body]'));
  const pph = friday.height / 24;
  await page.mouse.click(friday.x + friday.width / 2, friday.y + 10.5 * pph + 2);
  const add = page.getByRole("dialog", { name: "Add" });
  // The tapped time is what the Time row's one button says.
  await expect(add.getByRole("button", { name: "Time: 10:30 AM" })).toBeVisible();
  await expect(add.getByRole("button", { name: "All day" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await expect(
    add
      .getByRole("group", { name: "Day", exact: true })
      .getByRole("button", { name: "Fri, Oct 9" }),
  ).toHaveAttribute("aria-pressed", "true");
});

test("the now line stays under the day heads while the hours scroll under them", async ({
  page,
}) => {
  await pairWall(page);
  await page.goto("/display");
  const board = page.getByRole("region", { name: "This Week" });
  await expect(board).toBeVisible();
  await page.getByRole("banner").getByRole("button", { name: "Hours", exact: true }).click();
  const grid = board.locator("[data-hours]");
  await expect(grid).toBeVisible();
  const zoomIn = board
    .getByRole("group", { name: "Zoom" })
    .getByRole("button", { name: "Zoom in" });
  await zoomIn.click();
  await zoomIn.click();
  const today = board.locator('[data-day="2026-10-07"]');
  const head = today.locator(".day-column");
  const line = today.locator("[data-now-line]");
  const label = line.locator(".now-label");
  await expect(label).toBeVisible();
  // The line lets taps through (pointer-events: none), which hides it from elementFromPoint as
  // well. Let it be hit for this measurement: that changes nothing about what's painted on top.
  await line.evaluate((node) => {
    for (const part of [node, ...node.querySelectorAll<HTMLElement>("*")]) {
      if (part instanceof HTMLElement) part.style.pointerEvents = "auto";
    }
  });
  const centre = async () => {
    const box = await boxOf(label);
    return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  };
  const onTop = (point: { x: number; y: number }) =>
    page.evaluate(({ x, y }) => {
      const top = document.elementFromPoint(x, y);
      return {
        head: Boolean(top?.closest(".day-column")),
        line: Boolean(top?.closest("[data-now-line]")),
      };
    }, point);

  // Scrolled so the label is in today's head band: the head stays on top of it.
  const rest = await grid.evaluate((node) => node.scrollTop);
  const band = await boxOf(head);
  const below = await centre();
  await grid.evaluate(
    (node, by) => {
      node.scrollBy(0, by);
    },
    below.y - (band.y + band.height / 2),
  );
  await settled(page);
  const under = await centre();
  expect(under.y).toBeGreaterThan(band.y);
  expect(under.y).toBeLessThan(band.y + band.height);
  expect(await onTop(under)).toEqual({ head: true, line: false });

  // Back down among the hours, the line and its label are on top again.
  await grid.evaluate((node, top) => {
    node.scrollTo(0, top);
  }, rest);
  await settled(page);
  expect(await onTop(await centre())).toEqual({ head: false, line: true });
});

test("the layout and the zoom stay through two idle minutes, with now back in view", async ({
  page,
}) => {
  await page.clock.install();
  await pairWall(page);
  await page.goto("/display");
  const board = page.getByRole("region", { name: "This Week" });
  const grid = board.locator("[data-hours]");
  const hoursButton = page.getByRole("button", { name: "Hours", exact: true });
  const fitDay = page.getByRole("button", { name: "Fit the day" });
  await hoursButton.click();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await page.getByRole("button", { name: "Zoom in" }).click();
  await expect(fitDay).toBeEnabled();
  expect(await grid.evaluate((node) => node.scrollHeight - node.clientHeight)).toBeGreaterThan(0);
  // Scrolled up to midnight, far from now (10 AM).
  await grid.evaluate((node) => {
    node.scrollTop = 0;
  });
  await page.clock.fastForward("02:05");
  // Still Hours and still zoomed in (ADR 0031), and the grid has come back to now.
  await expect.poll(() => grid.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
  await expect(hoursButton).toHaveAttribute("aria-pressed", "true");
  await expect(fitDay).toBeEnabled();

  // The household's next choice of layout wins over this screen's own.
  await page.getByRole("button", { name: "Agenda", exact: true }).click();
  await expect(grid).toHaveCount(0);
  const hours = await page.request.patch("/api/settings", {
    headers: CSRF,
    data: { display_week_layout: "hours" },
  });
  expect(hours.ok()).toBe(true);
  await expect(grid).toBeVisible();
  await expect(hoursButton).toHaveAttribute("aria-pressed", "true");
});
