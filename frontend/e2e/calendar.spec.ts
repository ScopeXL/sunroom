/**
 * The calendar from end to end (PLAN §15 M1): quick add on the wall screen, the chip in its day
 * in the person's color, a phone seeing it within 3 seconds, a "this and the ones after" change
 * and its Undo, and a drag that Undo puts back. Synthetic data only; the server's clock is set to
 * Wednesday, October 7, 2026, 10:00 AM in the household's zone (New York).
 */
import type { Locator, Page } from "@playwright/test";

import { expect, pairWall, PASSWORD, phone, pickView, seed, signInPhone, test } from "./fixtures";

const CSRF = { "X-Sunroom": "1" };
const WEDNESDAY_10AM = "2026-10-07T14:00:00Z";

/** The toast that says `message`, for its Undo. */
function toast(page: Page, message: string): Locator {
  return page.locator("[data-toast]").filter({ hasText: message });
}

/** A long press (the board's drag sensor waits 400 ms), then a slow move and a drop. */
async function drag(page: Page, from: Locator, to: Locator): Promise<void> {
  const start = await from.boundingBox();
  const end = await to.boundingBox();
  if (!start || !end) throw new Error("nothing to drag, or nowhere to drop it");
  await page.mouse.move(start.x + start.width / 2, start.y + start.height / 2);
  await page.mouse.down();
  await page.waitForTimeout(600);
  await page.mouse.move(end.x + end.width / 2, end.y + end.height / 3, { steps: 12 });
  await page.mouse.up();
}

test.beforeEach(async ({ request }, testInfo) => {
  test.skip(testInfo.project.name !== "display-1080p", "the wall screen at 1080p, with a phone");
  const moved = await request.post("/api/_test/clock", {
    headers: CSRF,
    data: { set: WEDNESDAY_10AM },
  });
  expect(moved.status()).toBe(204);
  await seed(request);
});

test("quick add on the wall, seen on a phone, changed and undone, dragged and put back", async ({
  page,
  browser,
  watch,
}) => {
  await pairWall(page);
  await page.goto("/display");
  const board = page.getByRole("region", { name: "This Week" });
  await expect(board.locator("[aria-current=date]")).toContainText("Wed");

  // A phone, open on its Calendar: Thursday is tomorrow.
  const { page: phonePage, context } = await phone(browser, watch);
  await signInPhone(phonePage);
  await phonePage.getByRole("link", { name: "Calendar" }).click();
  const thursdayOnPhone = phonePage.getByRole("region", { name: /^Thu, Oct 8/ });
  await expect(thursdayOnPhone).toContainText("Soccer practice");

  // Quick add from the rail.
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const add = page.getByRole("dialog", { name: "Add" });
  await add.getByLabel("What, when, who").fill("Dentist Thu 2:30pm Mia");
  // What was typed fills the rows: the title that's left, the day, the time, how long and who.
  await expect(add).toContainText('Saved as "Dentist"');
  const row = (name: string) => add.getByRole("group", { name, exact: true });
  const pressed = (group: string, name: string) =>
    expect(row(group).getByRole("button", { name, exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  await pressed("Day", "Thu, Oct 8");
  await pressed("Who", "Mia");
  // Time, How long and Repeats each say what's chosen on one button (ADR 0030): no row of
  // likely times, no nine chips of repeats.
  await expect(add.getByRole("button", { name: "Time: 2:30 PM" })).toBeVisible();
  await expect(add.getByRole("button", { name: "All day" })).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  await expect(add.getByRole("button", { name: "How long: 1 hour" })).toBeVisible();
  await expect(add.getByRole("button", { name: "Repeats: Doesn't repeat" })).toBeVisible();
  await expect(add.getByRole("button", { name: "9:00 AM" })).toHaveCount(0);
  // The form is in three parts: the first needs no heading, the others say what they are.
  await expect(add.getByRole("region", { name: "What and Who" })).toBeVisible();
  await expect(add.getByRole("heading", { name: "When" })).toBeVisible();
  await expect(add.getByRole("heading", { name: "Details" })).toBeAttached();
  // The kinds of thing to add are one row, and the button stays in view above the keyboard.
  const kinds = await row("What to add")
    .getByRole("button")
    .evaluateAll((cells) => cells.map((cell) => Math.round(cell.getBoundingClientRect().y)));
  expect(new Set(kinds).size).toBe(1);
  await expect(add.getByRole("button", { name: "Add Event" })).toBeInViewport();
  await add.getByRole("button", { name: "Add Event" }).click();
  await expect(add).toBeHidden();
  const dentist = board.getByRole("button", {
    name: "Dentist, 2:30 to 3:30 PM, Mia, Thursday October 8",
  });
  await expect(dentist).toBeVisible();
  // On the Hours grid (a new household's layout, ADR 0042) the block inside wears the color.
  await expect(dentist.locator("[data-person]").first()).toHaveAttribute("data-person", "rose");
  await expect(board.locator('[data-day="2026-10-08"]')).toContainText("Dentist");
  await expect(toast(page, "Added Dentist")).toBeVisible();

  // The phone sees it within 3 seconds, without a reload.
  await expect(thursdayOnPhone).toContainText("Dentist", { timeout: 3_000 });

  // Change Thursday's soccer practice and the ones after; Tuesday's stays as it was.
  await board
    .getByRole("button", { name: /^Soccer practice, 4:00 to 5:00 PM, Mia, Thursday October 8/ })
    .click();
  const sheet = page.getByRole("dialog", { name: "Soccer practice" });
  await expect(sheet).toContainText("Every week on Tue and Thu");
  await sheet.getByRole("button", { name: "Change" }).click();
  const editor = page.getByRole("dialog", { name: "Change" });
  await editor.getByLabel("Title").fill("Soccer training");
  await editor.getByRole("button", { name: "Save Changes" }).click();
  await page
    .getByRole("dialog", { name: "Change which?" })
    .getByRole("button", { name: "This and the Ones After" })
    .click();
  await expect(
    board.getByRole("button", { name: /^Soccer training, .*Thursday October 8/ }),
  ).toBeVisible();
  await expect(
    board.getByRole("button", { name: /^Soccer practice, .*Tuesday October 6/ }),
  ).toBeVisible();
  await expect(thursdayOnPhone).toContainText("Soccer training", { timeout: 3_000 });

  // Undo puts the series back together.
  await toast(page, "Changes saved").getByRole("button", { name: "Undo" }).click();
  await expect(
    board.getByRole("button", { name: /^Soccer practice, .*Thursday October 8/ }),
  ).toBeVisible();
  await expect(board.getByRole("button", { name: /^Soccer training/ })).toHaveCount(0);
  await expect(thursdayOnPhone).not.toContainText("Soccer training", { timeout: 3_000 });

  // Drag the vet from Wednesday to Friday, then Undo moves it back.
  const vet = board.getByRole("button", { name: /^Vet, 9:00 to 9:30 AM, Ana, Wednesday/ });
  await drag(page, vet, board.locator('[data-day="2026-10-09"]'));
  await expect(
    board.getByRole("button", { name: /^Vet, 9:00 to 9:30 AM, Ana, Friday October 9/ }),
  ).toBeVisible();
  await toast(page, "Moved Vet to Fri").getByRole("button", { name: "Undo" }).click();
  await expect(
    board.getByRole("button", { name: /^Vet, 9:00 to 9:30 AM, Ana, Wednesday October 7/ }),
  ).toBeVisible();

  await context.close();
});

test("the views, the event sheet and Recently Removed", async ({ page }) => {
  await pairWall(page);
  await page.goto("/display");
  const board = page.getByRole("region", { name: "This Week" });
  await expect(board).toBeVisible();

  // The Today panel: Up next is the piano lesson at 3:30 PM.
  const today = page.getByRole("complementary", { name: "Today" });
  await expect(today.getByRole("region", { name: "Up next" })).toContainText("Piano lesson");

  // Day: the vet is over, free time folds into one line. The view names its own day: the
  // header doesn't (ADR 0030).
  await pickView(page, "Day");
  const day = page.getByRole("region", { name: "Wed, Oct 7" });
  await expect(day).toContainText("Wednesday, October 7");
  await expect(page.getByRole("banner")).not.toContainText("October");
  await expect(day).toContainText("Vet");
  await expect(day.getByRole("button", { name: /^free until 3:30 PM/ })).toBeVisible();

  // Month: a cell opens its day.
  await pickView(page, "Month");
  const month = page.getByRole("region", { name: "October 2026" });
  await expect(month.getByText("October 2026", { exact: true })).toBeVisible();
  await month.getByRole("button", { name: /^Fri 9: .*Pajama day/ }).click();
  await expect(page.getByRole("region", { name: "Fri, Oct 9" })).toContainText("Pajama day");

  // People: a column per person, Everyone first, on the day the Day view was showing (the two
  // share it, ADR 0036); Today comes back to Wednesday. Nothing to filter there.
  await pickView(page, "People");
  const people = page.getByRole("region", { name: "People" });
  await expect(people.getByText("Friday, October 9", { exact: true })).toBeVisible();
  await page.getByRole("banner").getByRole("button", { name: "Today", exact: true }).click();
  await expect(people.getByText("Wednesday, October 7", { exact: true })).toBeVisible();
  await expect(page.getByRole("banner").getByRole("button", { name: /^Filter/ })).toHaveCount(0);
  await expect(people.getByRole("region", { name: "Ana" })).toContainText("Vet");
  await expect(people.getByRole("region", { name: "Leo" })).toContainText("Piano lesson");
  // A clear calendar reads "Free day" under the name, in a pill; a busy one doesn't (ADR 0032).
  await expect(people.getByRole("region", { name: "Sam" })).toContainText("Free day");
  await expect(people.getByRole("region", { name: "Ana" })).not.toContainText("Free day");

  // Back to the week; remove the vet, then put it back from Settings.
  await pickView(page, "Week");
  await board.getByRole("button", { name: /^Vet, / }).click();
  const sheet = page.getByRole("dialog", { name: "Vet" });
  await sheet.getByRole("button", { name: "Remove" }).click();
  await expect(sheet).toBeHidden();
  await expect(toast(page, "Removed Vet")).toBeVisible();
  await expect(board.getByRole("button", { name: /^Vet, / })).toHaveCount(0);
  await page.getByRole("button", { name: "Settings" }).click();
  await page
    .getByRole("navigation", { name: "Settings" })
    .getByRole("link", { name: "Recently Removed", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "Recently Removed", level: 2 })).toBeVisible();
  await page.getByRole("button", { name: "Put back Vet" }).click();
  await expect(toast(page, "Put back Vet")).toBeVisible();
  await page.getByRole("link", { name: "Calendar", exact: true }).click();
  await expect(board.getByRole("button", { name: /^Vet, / })).toBeVisible();
});

test("People pages a day at a time and says which day (ADR 0036)", async ({ page }) => {
  await pairWall(page);
  await page.goto("/display");
  const header = page.getByRole("banner");
  await pickView(page, "People");
  const people = page.getByRole("region", { name: "People" });
  const mia = people.getByRole("region", { name: "Mia" });
  // The day over the columns, as the Day view writes its own, and "today" beside it.
  await expect(people.getByText("Wednesday, October 7", { exact: true })).toBeVisible();
  await expect(people.getByText("today", { exact: true })).toBeVisible();
  await expect(mia).toContainText("Free day");
  const backToToday = header.getByRole("button", { name: "Today", exact: true });
  await expect(backToToday).toBeDisabled();
  await expect(header.getByRole("button", { name: "Previous day" })).toBeVisible();

  // Next day: Thursday's events, and Today comes back to Wednesday.
  await header.getByRole("button", { name: "Next day" }).click();
  await expect(people.getByText("Thursday, October 8", { exact: true })).toBeVisible();
  await expect(people.getByText("today", { exact: true })).toHaveCount(0);
  await expect(mia).toContainText("Soccer practice");
  await expect(people.getByRole("region", { name: "Sam" })).toContainText("Book club");
  await expect(backToToday).toBeEnabled();
  await backToToday.click();
  await expect(people.getByText("Wednesday, October 7", { exact: true })).toBeVisible();
  await expect(backToToday).toBeDisabled();
  await expect(mia).toContainText("Free day");

  // People's arrows page its day, never the Week view's week behind its back.
  await header.getByRole("button", { name: "Next day" }).click();
  await expect(people.getByText("Thursday, October 8", { exact: true })).toBeVisible();
  await pickView(page, "Week");
  await expect(header.getByRole("button", { name: "This Week" })).toBeDisabled();
});

test("the Today view has no arrows and no quick jump: nothing to page (ADR 0036)", async ({
  page,
  request,
}) => {
  const parent = await request.post("/api/auth/login", {
    headers: CSRF,
    data: { password: PASSWORD },
  });
  expect(parent.ok()).toBe(true);
  const home = await request.patch("/api/settings", {
    headers: CSRF,
    data: { display_home_view: "today" },
  });
  expect(home.ok()).toBe(true);
  await pairWall(page);
  await page.goto("/display");
  const todayView = page.getByRole("region", { name: "Today", exact: true });
  await expect(todayView).toContainText("Vet");
  const header = page.getByRole("banner");
  await expect(header.getByRole("button", { name: /^(Previous|Next) / })).toHaveCount(0);
  await expect(header.getByRole("button", { name: /^(Today|This Week)$/ })).toHaveCount(0);
  // The View menu is there too, so the screen can leave Today from the header, and come back
  // (ADR 0042).
  await pickView(page, "Week");
  await expect(page.getByRole("region", { name: "This Week" })).toBeVisible();
  await expect(header.getByRole("button", { name: "This Week" })).toBeDisabled();
  await pickView(page, "Today");
  await expect(todayView).toContainText("Vet");
  await expect(header.getByRole("button", { name: "View: Today" })).toBeVisible();
});

test("Filter is one button in the header: several people, a tap elsewhere, Everyone", async ({
  page,
}) => {
  await pairWall(page);
  await page.goto("/display");
  const board = page.getByRole("region", { name: "This Week" });
  const header = page.getByRole("banner");
  await expect(board.getByRole("button", { name: /^Vet, / })).toBeVisible();
  // No row over the days any more: the board starts under the header.
  await expect(page.getByRole("group", { name: "Show" })).toHaveCount(0);
  // A chip that isn't one of the chosen people's fades; it keeps its words.
  const faded = (name: RegExp) =>
    board
      .getByRole("button", { name })
      .first()
      .locator("xpath=ancestor::*[contains(@class, 'opacity-30')]");
  await header.getByRole("button", { name: "Filter", exact: true }).click();
  const menu = page.getByRole("menu", { name: "Filter" });
  const everyone = menu.getByRole("menuitemradio", { name: "Everyone" });
  await expect(everyone).toHaveAttribute("aria-checked", "true");
  await expect(everyone).toBeFocused();
  // Choosing a person keeps the menu open for the next, and the board already follows.
  await menu.getByRole("menuitemcheckbox", { name: "Mia" }).click();
  await expect(menu).toBeVisible();
  await expect(faded(/^Vet, /)).toHaveCount(1);
  await expect(faded(/^Soccer practice, /)).toHaveCount(0);
  await expect(faded(/^Piano lesson, /)).toHaveCount(1);
  await menu.getByRole("menuitemcheckbox", { name: "Leo" }).click();
  await expect(faded(/^Piano lesson, /)).toHaveCount(0);
  // Everyone's events always show (the seed's garbage night is nobody's in particular).
  await expect(faded(/^Garbage night/)).toHaveCount(0);
  const chosen = header.getByRole("button", { name: "Filter: Mia, Leo" });
  await expect(chosen).toHaveAttribute("aria-expanded", "true");
  // A tap on the board closes the menu and does nothing else: no event sheet, no Add panel.
  await board.getByRole("button", { name: /^Vet, / }).click();
  await expect(menu).toBeHidden();
  await page.waitForTimeout(300);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  // The next tap is an ordinary one again.
  await board.getByRole("button", { name: /^Vet, / }).click();
  const sheet = page.getByRole("dialog", { name: "Vet" });
  await expect(sheet).toBeVisible();
  await sheet.getByRole("button", { name: "Close" }).click();
  // Escape closes it too, back to the button; the filter holds on the Day and Month views.
  await chosen.click();
  await expect(menu.getByRole("menuitemcheckbox", { name: "Mia" })).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await expect(chosen).toBeFocused();
  await pickView(page, "Month");
  await expect(chosen).toBeVisible();
  await pickView(page, "Week");
  // Everyone clears the filter and closes the menu.
  await chosen.click();
  await everyone.click();
  await expect(menu).toBeHidden();
  await expect(header.getByRole("button", { name: "Filter", exact: true })).toBeVisible();
  await expect(faded(/^Vet, /)).toHaveCount(0);
});

test("times follow the household's zone and its 12- or 24-hour clock", async ({
  page,
  browser,
  watch,
}) => {
  await pairWall(page);
  await page.goto("/display");
  const board = page.getByRole("region", { name: "This Week" });
  // The visible now line (FitList keeps an invisible copy for measuring).
  const nowLabel = board.locator(".now-label:visible");
  await expect(nowLabel).toHaveText("now 10:00");

  // A parent's phone moves the household to Honolulu, where 14:00 UTC is 4:00 in the morning.
  const { page: phonePage, context } = await phone(browser, watch);
  await signInPhone(phonePage);
  const change = async (settings: Record<string, string>) => {
    const response = await phonePage.request.patch("/api/settings", {
      headers: CSRF,
      data: settings,
    });
    expect(response.status()).toBe(200);
  };
  await change({ timezone: "Pacific/Honolulu" });
  await expect(nowLabel).toHaveText("now 4:00", { timeout: 3_000 });

  // Back home, on the 24-hour clock: Thursday's soccer practice starts at 16:00. (On the Hours
  // grid, a new household's layout, an hour's block says its time only in its name.)
  await change({ timezone: "America/New_York", time_format: "24h" });
  const soccer = board.getByRole("button", { name: /^Soccer practice, .*Thursday October 8/ });
  await expect(soccer).toHaveAccessibleName(/^Soccer practice, 16:00 to 17:00, /, {
    timeout: 3_000,
  });
  await expect(nowLabel).toHaveText("now 10:00");
  await context.close();
});

test("a birthday from Family is a chip in its person's color, and moves when it's changed", async ({
  page,
  browser,
  watch,
}) => {
  await pairWall(page);
  await page.goto("/display");
  const board = page.getByRole("region", { name: "This Week" });
  const thursday = board.locator('[data-day="2026-10-08"]');
  const friday = board.locator('[data-day="2026-10-09"]');
  // The seed's: Mia's birthday is on Friday, in her color, with no plugin needed.
  const onFriday = friday.getByRole("button", { name: /^Mia's birthday, all day, Mia/ });
  await expect(onFriday).toHaveAttribute("data-overlay", "birthdays");
  await expect(onFriday).toHaveAttribute("data-person", "rose");

  // A parent's phone moves it to Thursday: the wall follows within 3 seconds.
  const { page: phonePage, context } = await phone(browser, watch);
  await signInPhone(phonePage);
  await phonePage.goto("/settings/family");
  await phonePage.getByRole("button", { name: "Edit Mia" }).click();
  await phonePage.getByLabel("Birthday (optional)").fill("2017-10-08");
  await phonePage.getByRole("button", { name: "Save Changes" }).click();
  await expect(toast(phonePage, "Changes saved")).toBeVisible();
  const onThursday = thursday.getByRole("button", { name: /^Mia's birthday/ });
  await expect(onThursday).toBeVisible({ timeout: 3_000 });
  await expect(friday.getByRole("button", { name: /^Mia's birthday/ })).toHaveCount(0);

  // A tap opens its sheet, read only, saying where it comes from.
  await onThursday.click();
  const sheet = page.getByRole("dialog", { name: "Mia's birthday" });
  await expect(sheet).toContainText("Thu, Oct 8 · all day");
  await expect(sheet).toContainText("From Mia's birthday in Settings → Family.");
  await expect(sheet.getByRole("button", { name: "Change" })).toHaveCount(0);
  await context.close();
});

test("an event added from a phone eases onto the wall, and one removed fades away", async ({
  page,
  browser,
  watch,
}) => {
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await pairWall(page);
  await page.goto("/display");
  const board = page.getByRole("region", { name: "This Week" });
  await expect(board.getByRole("button", { name: /^Vet, / })).toBeVisible();
  // Nothing arrives on first paint.
  await expect(board.locator("[data-arrive]")).toHaveCount(0);
  // Nor when the week is paged: the whole week slides in from its side instead.
  await page.getByRole("button", { name: "Next week" }).click();
  const body = board.locator("[data-page]");
  await expect(body).toHaveAttribute("data-page", "next");
  expect(await body.evaluate((node) => getComputedStyle(node).animationName)).toMatch(
    /^page-next-/,
  );
  await page.getByRole("button", { name: "This Week" }).click();
  await expect(body).toHaveAttribute("data-page", "prev");
  await expect(board.getByRole("button", { name: /^Vet, / })).toBeVisible();
  await expect(board.locator("[data-arrive]")).toHaveCount(0);

  // A parent's phone adds an event: its chip, and only it, eases in.
  const { page: phonePage, context } = await phone(browser, watch);
  await signInPhone(phonePage);
  const added = await phonePage.request.post("/api/calendar/events", {
    headers: CSRF,
    data: { title: "Library day", start_date: "2026-10-08" },
  });
  expect(added.status()).toBe(201);
  const { event } = (await added.json()) as { event: { id: string } };
  const chip = board.getByRole("button", { name: /^Library day/ });
  await expect(chip).toHaveAttribute("data-arrive", "", { timeout: 3_000 });
  expect(await chip.evaluate((node) => getComputedStyle(node).animationName)).toBe("arrive");
  await expect(board.locator("[data-arrive]")).toHaveCount(1);
  // The mark goes once it has arrived, so drawing the board again doesn't replay it.
  await expect(board.locator("[data-arrive]")).toHaveCount(0, { timeout: 3_000 });

  // Removed from the phone: the chip fades and shrinks before it goes (motion, under the CSP).
  await page.evaluate(() => {
    const seen = window as unknown as { faded?: boolean };
    seen.faded = false;
    const chip = document.querySelector('[data-chip][aria-label^="Library day"]');
    const watch = () => {
      const box = chip?.parentElement?.parentElement;
      if (box && Number(getComputedStyle(box).opacity) < 1) seen.faded = true;
      if (chip?.isConnected) requestAnimationFrame(watch);
    };
    requestAnimationFrame(watch);
  });
  const removed = await phonePage.request.delete(`/api/calendar/events/${event.id}`, {
    headers: CSRF,
  });
  expect(removed.ok()).toBe(true);
  // Gone for a reader and a finger at once (it's inert while it fades), then from the page.
  await expect(chip).toHaveCount(0, { timeout: 3_000 });
  await expect
    .poll(() => page.evaluate(() => (window as unknown as { faded?: boolean }).faded))
    .toBe(true);
  await expect(page.locator('[data-chip][aria-label^="Library day"]')).toHaveCount(0);

  // With Reduce motion on (Settings → Display), a newcomer has no animation at all.
  const calm = await phonePage.request.patch("/api/settings", {
    headers: CSRF,
    data: { display_reduce_motion: true },
  });
  expect(calm.ok()).toBe(true);
  await expect(page.locator("html[data-reduce-motion]")).toHaveCount(1, { timeout: 3_000 });
  const again = await phonePage.request.post("/api/calendar/events", {
    headers: CSRF,
    data: { title: "Dentist", start_date: "2026-10-08" },
  });
  expect(again.status()).toBe(201);
  const calmChip = board.getByRole("button", { name: /^Dentist/ });
  await expect(calmChip).toBeVisible({ timeout: 3_000 });
  expect(await calmChip.evaluate((node) => getComputedStyle(node).animationName)).toBe("none");
  await context.close();
});

test("Rolling Week keeps today in the same column, and still pages by seven days", async ({
  page,
  request,
}) => {
  // A Friday: the calendar week (Oct 4–10) and the rolling one (Oct 8–14) differ.
  const friday = await request.post("/api/_test/clock", {
    headers: CSRF,
    data: { set: "2026-10-09T14:00:00Z" },
  });
  expect(friday.status()).toBe(204);
  await pairWall(page);
  await page.goto("/display");
  const board = page.getByRole("region", { name: "This Week" });
  const days = board.locator("[data-day]");
  const today = board.locator("[aria-current=date]");
  await expect(days.first()).toHaveAttribute("data-day", "2026-10-04");
  await expect(days.nth(5)).toHaveAttribute("aria-current", "date");

  // A parent makes it the Home view (Settings → Display, ADR 0042); the wall follows at once.
  const parent = await request.post("/api/auth/login", {
    headers: CSRF,
    data: { password: PASSWORD },
  });
  expect(parent.ok()).toBe(true);
  const rolling = await request.patch("/api/settings", {
    headers: CSRF,
    data: { display_home_view: "rolling" },
  });
  expect(rolling.ok()).toBe(true);
  // Yesterday, today in the second column, and the five days after (ADR 0033).
  await expect(days.first()).toHaveAttribute("data-day", "2026-10-08", { timeout: 5_000 });
  await expect(days.nth(1)).toHaveAttribute("aria-current", "date");
  await expect(today).toContainText("Fri");
  await expect(days.last()).toHaveAttribute("data-day", "2026-10-14");
  // The button says so, and the week's two layouts are there as on Week.
  const banner = page.getByRole("banner");
  await expect(banner.getByRole("button", { name: "View: Rolling Week" })).toBeVisible();
  await expect(banner.getByRole("group", { name: "Week layout" })).toBeVisible();

  // The arrows page seven days; This Week comes back to the window around today.
  await banner.getByRole("button", { name: "Next week" }).click();
  await expect(days.first()).toHaveAttribute("data-day", "2026-10-15");
  await expect(today).toHaveCount(0);
  const thisWeek = banner.getByRole("button", { name: "This Week" });
  await thisWeek.click();
  // The region is named This Week on every week: wait for the button (docs/GOTCHAS.md).
  await expect(thisWeek).toBeDisabled();
  await expect(days.first()).toHaveAttribute("data-day", "2026-10-08");
  await expect(days.nth(1)).toHaveAttribute("aria-current", "date");
});

test("a screen picks Rolling Week for itself, and Settings → Display wins (ADR 0042)", async ({
  page,
  request,
}) => {
  // The Friday of the case above: the calendar week (Oct 4–10) and the rolling one differ.
  const friday = await request.post("/api/_test/clock", {
    headers: CSRF,
    data: { set: "2026-10-09T14:00:00Z" },
  });
  expect(friday.status()).toBe(204);
  await pairWall(page);
  await page.goto("/display");
  const board = page.getByRole("region", { name: "This Week" });
  const days = board.locator("[data-day]");
  const banner = page.getByRole("banner");
  await expect(days.first()).toHaveAttribute("data-day", "2026-10-04");
  await expect(banner.getByRole("button", { name: "View: Week" })).toBeVisible();

  // From the View menu: this screen's week rolls at once; the household's Home view stays.
  await pickView(page, "Rolling Week");
  await expect(days.first()).toHaveAttribute("data-day", "2026-10-08");
  await expect(days.nth(1)).toHaveAttribute("aria-current", "date");
  await expect(banner.getByRole("button", { name: "View: Rolling Week" })).toBeVisible();
  const parent = await request.post("/api/auth/login", {
    headers: CSRF,
    data: { password: PASSWORD },
  });
  expect(parent.ok()).toBe(true);
  const settings = (await (await request.get("/api/settings")).json()) as {
    display_home_view: string;
  };
  expect(settings.display_home_view).toBe("week");

  // Remembered across a reload, like the layout (ADR 0030).
  const kept = () =>
    page.evaluate(
      () =>
        (
          JSON.parse(localStorage.getItem("sunroom.display.view") ?? "{}") as Record<
            string,
            unknown
          >
        ).view,
    );
  expect(await kept()).toBe("rolling");
  await page.reload();
  await expect(days.first()).toHaveAttribute("data-day", "2026-10-08");
  await expect(banner.getByRole("button", { name: "View: Rolling Week" })).toBeVisible();

  // A new Home view in Settings → Display wins (ADR 0031): Rolling Week, then Week, and the
  // board follows both.
  const on = await request.patch("/api/settings", {
    headers: CSRF,
    data: { display_home_view: "rolling" },
  });
  expect(on.ok()).toBe(true);
  // The screen's own choice gave way to the household's, which also rolls.
  await expect.poll(kept).toBeNull();
  await expect(days.first()).toHaveAttribute("data-day", "2026-10-08");
  const off = await request.patch("/api/settings", {
    headers: CSRF,
    data: { display_home_view: "week" },
  });
  expect(off.ok()).toBe(true);
  await expect(days.first()).toHaveAttribute("data-day", "2026-10-04", { timeout: 5_000 });
  await expect(days.nth(5)).toHaveAttribute("aria-current", "date");
  await expect(banner.getByRole("button", { name: "View: Week" })).toBeVisible();
});

test("remind: the household's Default reminder brings the Vet up 10 minutes before (ADR 0034)", async ({
  page,
}) => {
  await pairWall(page);
  // The seed's Vet is today at 9:00 with no reminder of its own; it's 8:50.
  const early = await page.request.post("/api/_test/clock", {
    headers: CSRF,
    data: { set: "2026-10-07T12:50:00Z" },
  });
  expect(early.status()).toBe(204);
  const set = await page.request.patch("/api/settings", {
    headers: CSRF,
    data: { default_reminder_minutes: 10 },
  });
  expect(set.ok()).toBe(true);
  await page.goto("/display");
  await expect(page.getByRole("region", { name: "This Week" })).toBeVisible();
  await expect(toast(page, "Vet starts in 10 min")).toBeVisible({ timeout: 15_000 });
});

test("remind: an event opens with the reminder it holds, 30 min before (R1)", async ({ page }) => {
  await pairWall(page);
  await page.goto("/display");
  const board = page.getByRole("region", { name: "This Week" });
  await board.getByRole("button", { name: /^Soccer practice, .*Thursday October 8/ }).click();
  const sheet = page.getByRole("dialog", { name: "Soccer practice" });
  await sheet.getByRole("button", { name: "Change" }).click();
  const editor = page.getByRole("dialog", { name: "Change" });
  // More… is open already: the event has a reminder, and it reads as one.
  await expect(editor.getByRole("button", { name: "Remind: 30 min before" })).toBeVisible();
});
