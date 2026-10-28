/**
 * Captures the key screens for review (`just screenshots`, UX §10): the wall screen at 1920×1080
 * and 1080×1920 (Standard, Extra large and Small text), phones at 390×844 and a laptop at 1440×900, in
 * light and dark, at 09:40, 16:10 and 21:30 so the tint and theme stops show. Synthetic data
 * only; files go to the gitignored .screenshots/ folder and are never committed.
 */
import type { Page } from "@playwright/test";

import {
  expect,
  PASSWORD,
  pickView,
  PIN,
  resetServer,
  scriptedAccount,
  seed,
  settled,
  signInPhone,
  test,
} from "./fixtures";

const CSRF = { "X-Sunroom": "1" };
// The household's zone in end-to-end runs is America/New_York (UTC−4 in October).
const STOPS = [
  { name: "0940", at: "2026-10-07T13:40:00Z" },
  { name: "1610", at: "2026-10-07T20:10:00Z" },
  { name: "2130", at: "2026-10-08T01:30:00Z" },
  { name: "2300", at: "2026-10-08T03:00:00Z" },
];
const NIGHT = "2026-10-08T03:30:00Z";
const PAGES = [
  { key: "family", title: "Family" },
  { key: "features", title: "Features" },
  { key: "calendars", title: "Calendars & Accounts" },
  { key: "chores", title: "Tasks" },
  { key: "meals", title: "Meals" },
  { key: "screensaver", title: "Photos & Screensaver" },
  { key: "display", title: "Display" },
  { key: "household", title: "Household" },
  { key: "devices", title: "Devices" },
  { key: "removed", title: "Recently Removed" },
  { key: "backup", title: "Backup" },
  { key: "support", title: "Support Sunroom" },
  { key: "about", title: "About" },
];

test.skip(!process.env.SCREENSHOTS, "run with `just screenshots`");

const escapeRegExp = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
// Playwright's WebKit screenshot code injects an inline <style>, which the CSP blocks and
// reports. Every other spec keeps the guard on, so real violations are still caught.
test.use({ cspGuard: false });
// Every shot is of a screen as it first opens. A wall screen comes back to the view and the room
// it was in (ADR 0030), which would carry one shot's zoom, fold or room into the next reload: so
// here it remembers nothing.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    try {
      localStorage.removeItem("sunroom.display.view");
      localStorage.removeItem("sunroom.display.room");
    } catch {
      // No storage on this page: nothing was remembered.
    }
  });
});

async function shot(page: Page, name: string): Promise<void> {
  await settled(page);
  await page.screenshot({
    path: `../.screenshots/${test.info().project.name}/${name}.png`,
    // The default caret: "hide" injects an inline <style>, which the CSP rightly blocks.
    caret: "initial",
    animations: "disabled",
  });
}

async function moveClock(page: Page, at: string): Promise<void> {
  const response = await page.request.post("/api/_test/clock", {
    headers: CSRF,
    data: { set: at },
  });
  expect(response.status()).toBe(204);
}

/** The wall's keyboard down and the room it took given back (ui/Keyboard holds it a moment). */
async function keyboardGone(page: Page): Promise<void> {
  await expect(page.getByRole("group", { name: "On-screen keyboard" })).toBeHidden();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.style.getPropertyValue("--osk-h")))
    .toBe("0px");
}

async function change(page: Page, settings: Record<string, unknown>): Promise<void> {
  const response = await page.request.patch("/api/settings", { headers: CSRF, data: settings });
  expect(response.status()).toBe(200);
}

test("the wall screen", async ({ page }) => {
  test.skip(!test.info().project.name.startsWith("display"), "the wall screen");
  test.setTimeout(240_000);
  await moveClock(page, STOPS[0]?.at ?? "");
  await page.goto("/display");
  await expect(page.getByRole("heading", { name: "Set Up Sunroom", exact: true })).toBeVisible();
  await shot(page, "display-setup");
  await seed(page.request);
  await page.reload();
  await expect(page.getByTestId("pair-code")).toBeVisible();
  await shot(page, "display-pair");
  await page.getByRole("button", { name: "Type the household password here instead" }).click();
  await page.getByLabel("Household password").click();
  await expect(page.getByRole("group", { name: "On-screen keyboard" })).toBeVisible();
  await shot(page, "display-keyboard");
  await page.getByLabel("Household password").fill(PASSWORD);
  await page.getByRole("button", { name: "Pair This Screen" }).click();
  await expect(page.getByRole("heading", { name: "Name this screen" })).toBeVisible();
  await shot(page, "display-name");
  await page.getByRole("button", { name: "Done" }).click();

  const board = page.getByRole("region", { name: "This Week" });
  for (const size of ["standard", "xl", "small"]) {
    for (const theme of ["light", "dark"]) {
      for (const stop of STOPS) {
        // Small text: one look in each theme is enough (the tints are the same).
        if (size === "small" && stop !== STOPS[1]) continue;
        await moveClock(page, stop.at);
        await change(page, { theme, text_size: size });
        await page.reload();
        await expect(board).toBeVisible();
        // The Today panel's plugin blocks arrive a moment after the board.
        await expect(page.getByRole("heading", { name: "Tasks Today" }).first()).toBeVisible();
        // Mia's birthday, the core's own chip, on Friday (at Extra large, portrait's short rows
        // keep it behind "+3 more").
        if (size === "standard") {
          await expect(board.locator("[data-overlay=birthdays]:visible")).toHaveCount(1);
        }
        await shot(page, `board-${size}-${theme}-${stop.name}`);
      }
    }
  }

  // The calendar at 16:10, light: the views, an event, Add and "Change which?".
  await change(page, { theme: "light", text_size: "standard" });
  await moveClock(page, STOPS[1]?.at ?? "");
  await page.reload();
  await expect(board).toBeVisible();
  for (const view of ["Rolling Week", "Day", "Month", "People"]) {
    await pickView(page, view);
    await shot(page, `view-${view.split(" ")[0]?.toLowerCase() ?? view}`);
  }
  // The View menu: a drawing, a name and a line for each view (ADR 0042).
  await page.getByRole("button", { name: "View: People" }).click();
  await expect(page.getByRole("menu", { name: "View" })).toBeVisible();
  await shot(page, "view-menu");
  await page.getByRole("menuitemradio", { name: "Week", exact: true }).click();
  // Filter: its menu under the button with two people chosen, then the board they leave.
  await page.getByRole("button", { name: "Filter", exact: true }).click();
  await page.getByRole("menuitemcheckbox", { name: "Mia" }).click();
  await page.getByRole("menuitemcheckbox", { name: "Leo" }).click();
  await shot(page, "filter-menu");
  await page.keyboard.press("Escape");
  await shot(page, "board-filtered");
  await page.getByRole("button", { name: "Filter: Mia, Leo" }).click();
  await page.getByRole("menuitemradio", { name: "Everyone" }).click();
  // The Hours layout: the whole day, then four taps of Zoom in, light and dark.
  await page.getByRole("button", { name: "Hours", exact: true }).click();
  const root = page.locator("html");
  for (const theme of ["light", "dark"] as const) {
    await change(page, { theme });
    await expect(root).toHaveAttribute("data-theme", theme);
    const fitDay = page.getByRole("button", { name: "Fit the day" });
    if (await fitDay.isEnabled()) await fitDay.click();
    await expect(board.locator("[data-now-line]")).toBeVisible();
    await shot(page, `board-hours-24h-${theme}`);
    for (let tap = 0; tap < 4; tap++) await page.getByRole("button", { name: "Zoom in" }).click();
    await shot(page, `board-hours-zoomed-${theme}`);
  }
  // At Extra large the header's second line holds the arrows, the layout, Filter and the views.
  await change(page, { theme: "light", text_size: "xl", display_week_layout: "hours" });
  await page.reload();
  await expect(root).toHaveAttribute("data-text-size", "xl");
  await expect(board.locator("[data-now-line]")).toBeVisible();
  await shot(page, "board-hours-24h-xl");
  if (test.info().project.name === "display-1080p") {
    // The rail folded to its icons, at Standard: the board takes the room.
    await change(page, { text_size: "standard", display_week_layout: "agenda" });
    await page.reload();
    await expect(board).toBeVisible();
    await page.getByRole("button", { name: "Hide the rail" }).click();
    await shot(page, "rail-compact");
    await page.getByRole("button", { name: "Show the rail" }).click();
    await change(page, { text_size: "xl", display_week_layout: "hours" });
    await page.reload();
    await expect(root).toHaveAttribute("data-text-size", "xl");
  }
  // The View menu at Extra large, in both orientations.
  await page.getByRole("button", { name: "View: Week" }).click();
  await expect(page.getByRole("menu", { name: "View" })).toBeVisible();
  await shot(page, "view-menu-xl");
  await page.keyboard.press("Escape");
  // At Small the whole day still fits, and every chip stays a 56 px target.
  await change(page, { text_size: "small" });
  await page.reload();
  await expect(root).toHaveAttribute("data-text-size", "small");
  await expect(board.locator("[data-now-line]")).toBeVisible();
  await shot(page, "board-hours-24h-small");
  // Tips under the board: Agenda, then the whole day in Hours above the strip.
  await change(page, { text_size: "standard", show_tips: true });
  await page.reload();
  await expect(page.locator("[data-tips]")).toBeVisible();
  await expect(board.locator("[data-now-line]")).toBeVisible();
  await shot(page, "board-hours-24h-tips");
  await change(page, { display_week_layout: "agenda" });
  await page.reload();
  await expect(page.locator("[data-tips]")).toBeVisible();
  await shot(page, "board-tips");
  await change(page, { show_tips: false });
  await page.reload();
  await expect(board).toBeVisible();
  await board.getByRole("button", { name: /^Soccer practice, .*Thursday/ }).click();
  const sheet = page.getByRole("dialog", { name: "Soccer practice" });
  await expect(sheet).toBeVisible();
  await shot(page, "event-sheet");
  await sheet.getByRole("button", { name: "Change" }).click();
  const editor = page.getByRole("dialog", { name: "Change" });
  await editor.getByLabel("Title").fill("Soccer training");
  await editor.getByRole("button", { name: "Save Changes" }).click();
  await expect(page.getByRole("dialog", { name: "Change which?" })).toBeVisible();
  await shot(page, "change-which");
  await page
    .getByRole("dialog", { name: "Change which?" })
    .getByRole("button", { name: "Close" })
    .click();
  await editor.getByRole("button", { name: "Close" }).click();
  await page.getByRole("button", { name: "Add", exact: true }).click();
  const add = page.getByRole("dialog", { name: "Add" });
  await add.getByLabel("What, when, who").fill("Dentist Thu 2:30pm Mia");
  await shot(page, "add-event-keyboard");
  await page
    .getByRole("group", { name: "On-screen keyboard" })
    .getByRole("button", { name: "Done" })
    .click();
  // The panel keeps the keyboard's padding for 400 ms after it lowers: wait it out, or the
  // shot shows the button floating mid-panel.
  await page.waitForTimeout(500);
  await shot(page, "add-event");
  await add.getByRole("button", { name: "Pick a date" }).click();
  await add.getByRole("button", { name: "Pick a date" }).scrollIntoViewIfNeeded();
  await shot(page, "add-pick-a-date");
  await add.getByRole("button", { name: "Pick a date" }).click();
  // Time, How long and Repeats: one button each, its picker opening under the row.
  await add.getByRole("button", { name: /^Time: / }).click();
  await add.getByRole("group", { name: "Time: minutes" }).scrollIntoViewIfNeeded();
  await shot(page, "add-time");
  await add.getByRole("button", { name: "Done", exact: true }).click();
  await add.getByRole("button", { name: /^How long: / }).click();
  await add.getByRole("radiogroup", { name: "How long" }).scrollIntoViewIfNeeded();
  await shot(page, "add-how-long");
  await add.getByRole("button", { name: "Done", exact: true }).click();
  await add.getByRole("button", { name: /^Repeats: / }).click();
  await add.getByRole("radiogroup", { name: "Repeats" }).scrollIntoViewIfNeeded();
  await shot(page, "add-repeats");
  await add.getByRole("radio", { name: "Custom…" }).click();
  await add.getByRole("button", { name: "Every: more" }).click();
  await add.getByRole("button", { name: "Tuesday" }).click();
  await add.getByRole("group", { name: "Ends" }).scrollIntoViewIfNeeded();
  await shot(page, "add-custom-repeat");
  await add.getByRole("button", { name: "Done", exact: true }).click();
  await add.getByRole("button", { name: "More…" }).click();
  await add.getByRole("button", { name: /^Remind: / }).scrollIntoViewIfNeeded();
  await shot(page, "add-details");
  await add.getByRole("button", { name: "Close" }).click();
  await change(page, { display_home_view: "today" });
  await page.reload();
  // The coming days' counts show once the events have arrived.
  await expect(
    page
      .getByRole("list", { name: "The coming days" })
      .getByText(/events?$/)
      .first(),
  ).toBeVisible();
  await shot(page, "view-today");
  await change(page, { display_home_view: "week" });

  // A synced account that stopped answering: Needs Attention's sheet. More failures are queued
  // than the three syncs below use: the plugin's own minute check may use some first.
  const account = await scriptedAccount(page.request);
  await page.request.put(`/api/calendar-sync/_test/fake/${account}`, {
    headers: CSRF,
    data: { fail_next: Array.from({ length: 8 }, () => "unreachable") },
  });
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    // "Refresh Now" waits a minute between syncs, and this clock only moves when told to.
    await expect(async () => {
      await page.request.post("/api/_test/clock", {
        headers: CSRF,
        data: { advance_minutes: 2 },
      });
      const synced = await page.request.post(`/api/calendar-sync/accounts/${account}/sync`, {
        headers: CSRF,
      });
      expect(synced.status()).toBe(200);
    }).toPass({ timeout: 10_000 });
    await expect(async () => {
      const accounts = (await (await page.request.get("/api/calendar-sync/accounts")).json()) as {
        id: string;
        syncing: boolean;
        last_error: string | null;
      }[];
      const found = accounts.find((a) => a.id === account);
      expect(found?.syncing).toBe(false);
      expect(found?.last_error).not.toBeNull();
    }).toPass({ timeout: 10_000 });
  }
  await moveClock(page, STOPS[1]?.at ?? "");
  await page.reload();
  const attention = page.getByRole("banner").getByRole("button", { name: /^Needs attention/ });
  await expect(attention).toBeVisible();
  await attention.click();
  const needs = page.getByRole("dialog", { name: "Needs Attention" });
  await expect(needs).toContainText("hasn't answered");
  await shot(page, "display-attention");
  await needs.getByRole("button", { name: "Done" }).click();
  await expect(needs).toBeHidden();

  // Settings at 16:10 on Auto, while there's no PIN yet (the screen opens them itself).
  await change(page, { theme: "auto", text_size: "standard" });
  await page.reload();
  await page.getByRole("button", { name: "Settings" }).click();
  for (const { key, title } of PAGES) {
    // A page Needs Attention points at is marked (ADR 0034): its link says so to a screen reader.
    await page
      .getByRole("navigation", { name: "Settings" })
      .getByRole("link", { name: new RegExp(`^${escapeRegExp(title)}(, needs attention)?$`) })
      .click();
    await expect(page.getByRole("heading", { name: title, level: 2, exact: true })).toBeVisible();
    await shot(page, `settings-${key}`);
  }
  // Below the fold: Features → Countdowns' Birthdays in Coming Up, and About's Updates.
  await page
    .getByRole("navigation", { name: "Settings" })
    .getByRole("link", { name: "Features", exact: true })
    .click();
  await page.getByRole("group", { name: "Birthdays in Coming Up" }).scrollIntoViewIfNeeded();
  await shot(page, "settings-features-countdowns");
  await page
    .getByRole("navigation", { name: "Settings" })
    .getByRole("link", { name: "About", exact: true })
    .click();
  await page.getByRole("switch", { name: /^Check for updates daily/ }).scrollIntoViewIfNeeded();
  await shot(page, "settings-about-versions");
  await page
    .getByRole("navigation", { name: "Settings" })
    .getByRole("link", { name: "Family", exact: true })
    .click();
  await page.getByRole("button", { name: "Edit Mia" }).click();
  await expect(page.getByRole("dialog", { name: "Edit Mia" })).toBeVisible();
  await shot(page, "settings-change-a-person");
  // The keyboard inside a sheet: the sheet moves up above the keys.
  const person = page.getByRole("dialog", { name: "Edit Mia" });
  const keys = page.getByRole("group", { name: "On-screen keyboard" });
  await person.getByLabel("Name").click();
  await expect(keys).toBeVisible();
  await shot(page, "settings-change-a-person-keyboard");
  await keys.getByRole("button", { name: "Done" }).click();
  // Saved: the toast is on the page. Opened again while it shows, the sheet stays where it was
  // and the toast stays on the page, under the backdrop (ADR 0032).
  await person.getByRole("button", { name: "Save Changes" }).click();
  await expect(person).toBeHidden();
  await expect(page.locator("[data-toast]").filter({ hasText: "Changes saved" })).toBeVisible();
  await page.getByRole("button", { name: /^Edit Mia/ }).click();
  await expect(person).toBeVisible();
  await shot(page, "settings-change-a-person-toast");
  await person.getByRole("button", { name: "Close" }).click();
  await expect(person).toBeHidden();

  // An account's sheet (its server stopped answering above), and its calendar's page.
  await page
    .getByRole("navigation", { name: "Settings" })
    .getByRole("link", { name: /^Calendars & Accounts(, needs attention)?$/ })
    .click();
  await page.getByRole("button", { name: "Edit Test server" }).click();
  await expect(page.getByRole("dialog", { name: "Edit Test server" })).toBeVisible();
  await shot(page, "settings-account");
  await page.getByRole("button", { name: "Edit School" }).click();
  const school = page.getByRole("dialog", { name: "Edit School" });
  await expect(school).toBeVisible();
  await shot(page, "settings-account-calendar");
  await school.getByRole("button", { name: "Close" }).click();
  await expect(school).toBeHidden();
  // The Default calendar's list, open: Home, and the account's calendar under its name.
  await page.getByRole("button", { name: "Default calendar: Home" }).click();
  await expect(page.getByRole("radiogroup", { name: "Default calendar" })).toBeVisible();
  await shot(page, "settings-default-calendar");
  await page.getByRole("button", { name: "Default calendar: Home" }).click();
  // Home's sheet: no Remove while it's the default, and a line says why.
  await page.getByRole("button", { name: "Edit Home" }).click();
  const homeSheet = page.getByRole("dialog", { name: "Edit Home" });
  await expect(homeSheet).toContainText("so it stays");
  await shot(page, "settings-calendar-stays");
  await homeSheet.getByRole("button", { name: "Close" }).click();
  await expect(homeSheet).toBeHidden();

  // Adding an account here: the choices with the phone shortcut, Apple's password on the
  // keyboard, and Google's two ways that need a phone.
  await page
    .getByRole("navigation", { name: "Settings" })
    .getByRole("link", { name: /^Calendars & Accounts(, needs attention)?$/ })
    .click();
  const addAccount = page.getByRole("button", { name: "Add an Account" });
  const adding = page.getByRole("dialog");
  await addAccount.click();
  await expect(adding.getByText("Or add it from a device")).toBeVisible();
  await shot(page, "settings-add-account");
  await adding.getByRole("button", { name: /^Apple/ }).click();
  await adding.getByLabel("App-specific password").click();
  await expect(keys).toBeVisible();
  await shot(page, "settings-add-apple-keyboard");
  await keys.getByRole("button", { name: "Done" }).click();
  await adding.getByRole("button", { name: "Close" }).click();
  await expect(adding).toBeHidden();
  await addAccount.click();
  await adding.getByRole("button", { name: /^Google/ }).click();
  await shot(page, "settings-add-google");
  await adding.getByRole("button", { name: /^Share with a Sunroom helper/ }).click();
  await expect(adding).toContainText("Do this from a device");
  await shot(page, "settings-add-google-phone");
  await adding.getByRole("button", { name: "Close" }).click();
  await expect(adding).toBeHidden();

  // Night: 11:30 PM inside a 10 PM to 6 AM schedule.
  await change(page, { sleep_from: "22:00", sleep_to: "06:00", sleep_mode: "dim_clock" });
  await moveClock(page, NIGHT);
  await page.goto("/display");
  await expect(
    page.getByRole("button", { name: "The screen is sleeping. Tap to wake it." }),
  ).toBeVisible();
  await shot(page, "night");
  await change(page, { sleep_from: null, sleep_to: null });

  // The PIN dialog, with a PIN set.
  const pin = await page.request.put("/api/auth/pin", { headers: CSRF, data: { pin: PIN } });
  expect(pin.status()).toBe(204);
  await moveClock(page, STOPS[1]?.at ?? "");
  await page.goto("/display");
  await page.getByRole("button", { name: "Settings" }).click();
  await expect(page.getByRole("dialog", { name: "Parent PIN" })).toBeVisible();
  await shot(page, "pin");
});

test("setup on the wall itself (ADR 0039)", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("display"), "the wall screen");
  test.setTimeout(120_000);
  for (const scheme of ["light", "dark"] as const) {
    await resetServer(page.request);
    await page.context().clearCookies();
    // Before setup the wall guesses by the time of day: dark from 7 PM (DisplayEntry's Frame).
    await moveClock(page, (scheme === "light" ? STOPS[0] : STOPS[2])?.at ?? "");
    await page.goto("/display");
    await expect(page.getByRole("heading", { name: "Set Up Sunroom", exact: true })).toBeVisible();
    await shot(page, `wall-setup-${scheme}`);
    await page.getByRole("button", { name: "Set Up Here" }).click();
    await page.getByLabel("Household password").click();
    await expect(page.getByRole("group", { name: "On-screen keyboard" })).toBeVisible();
    await page.getByLabel("Household password").fill(PASSWORD);
    await shot(page, `wall-setup-password-${scheme}`);
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel("Household name").fill("Sample Family");
    await page.getByRole("heading", { name: "Name your household" }).click();
    await keyboardGone(page);
    await shot(page, `wall-setup-household-${scheme}`);
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "Where’s home?" })).toBeVisible();
    await shot(page, `wall-setup-place-${scheme}`);
    await page.getByRole("button", { name: "Later" }).click();
    await page.getByLabel("Your name").fill("Ana");
    await page.getByRole("button", { name: "Add Me" }).click();
    await page.getByLabel("Name", { exact: true }).fill("Mia");
    await page.getByRole("button", { name: "Child", exact: true }).click();
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByRole("listitem").filter({ hasText: "Mia" })).toBeVisible();
    await page.getByRole("heading", { name: "Who lives here?" }).click();
    await keyboardGone(page);
    await shot(page, `wall-setup-people-${scheme}`);
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await shot(page, `wall-setup-pin-${scheme}`);
    await page.getByRole("button", { name: "Later" }).click();
    await expect(page.getByRole("heading", { name: "Bring in your calendars" })).toBeVisible();
    await shot(page, `wall-setup-calendars-${scheme}`);
    await page.getByRole("button", { name: "Skip for Now" }).click();
    await expect(page.getByRole("heading", { name: "Name this screen" })).toBeVisible();
    await shot(page, `wall-setup-name-${scheme}`);
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "All done!" })).toBeVisible();
    await shot(page, `wall-setup-done-${scheme}`);
  }
});

test("setup on a laptop: the steps beside the form", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "a laptop");
  test.setTimeout(120_000);
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await resetServer(page.request);
    await page.context().clearCookies();
    await page.goto("/setup");
    await expect(page.getByRole("heading", { name: "Welcome to Sunroom" })).toBeVisible();
    await shot(page, `setup-welcome-${scheme}`);
    await page.getByRole("button", { name: "Start" }).click();
    await page.getByLabel("Household password").fill(PASSWORD);
    await shot(page, `setup-password-${scheme}`);
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel("Household name").fill("Sample Family");
    await shot(page, `setup-household-${scheme}`);
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "Where’s home?" })).toBeVisible();
    await page.getByRole("button", { name: "Later" }).click();
    await page.getByLabel("Your name").fill("Ana");
    await page.getByRole("button", { name: "Add Me" }).click();
    await page.getByLabel("Name", { exact: true }).fill("Mia");
    await page.getByRole("button", { name: "Child", exact: true }).click();
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByRole("listitem").filter({ hasText: "Mia" })).toBeVisible();
    await shot(page, `setup-people-${scheme}`);
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await page.getByRole("button", { name: "Later" }).click();
    await page.getByRole("button", { name: "Skip for Now" }).click();
    await expect(page.getByRole("heading", { name: "All done!" })).toBeVisible();
    await shot(page, `setup-done-${scheme}`);
  }
});

test("a phone", async ({ page, isMobile }) => {
  test.skip(!isMobile, "phones");
  test.setTimeout(240_000);
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await resetServer(page.request);
    await page.context().clearCookies();
    await page.goto("/setup");
    await expect(page.getByRole("heading", { name: "Welcome to Sunroom" })).toBeVisible();
    await shot(page, `setup-welcome-${scheme}`);
    await page.getByRole("button", { name: "Start" }).click();
    await page.getByLabel("Household password").fill(PASSWORD);
    await shot(page, `setup-password-${scheme}`);
    await page.getByRole("button", { name: "Next" }).click();
    await page.getByLabel("Household name").fill("Sample Family");
    await shot(page, `setup-household-${scheme}`);
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByRole("heading", { name: "Where’s home?" })).toBeVisible();
    await page.getByLabel("Your city").fill("Sample");
    await expect(page.getByRole("list", { name: "Places" })).toBeVisible();
    await shot(page, `setup-place-${scheme}`);
    await page.getByRole("button", { name: /^Sample Town/ }).click();
    await page.getByLabel("Your name").fill("Ana");
    await page.getByRole("button", { name: "Add Me" }).click();
    await page.getByLabel("Name", { exact: true }).fill("Mia");
    await page.getByRole("button", { name: "Child", exact: true }).click();
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await expect(page.getByRole("listitem").filter({ hasText: "Mia" })).toBeVisible();
    await shot(page, `setup-people-${scheme}`);
    await page.getByRole("button", { name: "Next", exact: true }).click();
    await shot(page, `setup-pin-${scheme}`);
    await page.getByRole("button", { name: "Later" }).click();
    await expect(page.getByRole("heading", { name: "Bring in your calendars" })).toBeVisible();
    await shot(page, `setup-calendars-${scheme}`);
    await page.getByRole("button", { name: "Skip for Now" }).click();
    await shot(page, `setup-done-${scheme}`);
    await page.getByRole("button", { name: "Open Sunroom" }).click();
    await expect(page.getByRole("heading", { name: "Up next" })).toBeVisible();
    await shot(page, `today-${scheme}`);
    await page.getByRole("link", { name: "Calendar" }).click();
    await expect(page.getByRole("group", { name: "Days" })).toBeVisible();
    await shot(page, `calendar-empty-${scheme}`);
    await page.getByRole("link", { name: "More" }).click();
    await shot(page, `more-${scheme}`);
    await page.getByRole("link", { name: "Pair a Display" }).click();
    await shot(page, `pair-a-display-${scheme}`);
    await page.goto("/who?from=more");
    await shot(page, `who-${scheme}`);
    for (const { key, title } of PAGES) {
      await page.goto(`/settings/${key}`);
      await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
      await shot(page, `settings-${key}-${scheme}`);
    }
    await page.goto("/settings/features");
    await page.getByRole("group", { name: "Birthdays in Coming Up" }).scrollIntoViewIfNeeded();
    await shot(page, `settings-features-countdowns-${scheme}`);
    // A photo library's panel (ADR 0036), the pretend Immich.
    await page.request.post("/api/screensaver/_test/library", { headers: CSRF, data: {} });
    await page.goto("/settings/screensaver");
    await page.getByRole("button", { name: "Edit Immich" }).click();
    await expect(page.getByRole("dialog", { name: "Immich" })).toContainText("What to Show");
    await shot(page, `settings-screensaver-library-${scheme}`);
    await page.goto("/settings/family");
    await page.getByRole("button", { name: "Edit Mia" }).click();
    await expect(page.getByRole("dialog", { name: "Edit Mia" })).toBeVisible();
    await shot(page, `settings-change-a-person-${scheme}`);
    await page.goto("/settings/devices");
    await page.getByRole("button", { name: "Add a Device" }).click();
    await expect(page.getByRole("dialog", { name: "Add a Device" })).toBeVisible();
    await shot(page, `settings-add-a-device-${scheme}`);
    await page.goto("/settings/devices");
    await page.getByRole("button", { name: "Pair a Display" }).click();
    await expect(page.getByRole("dialog", { name: "Pair a Display" })).toBeVisible();
    await shot(page, `settings-pair-a-display-${scheme}`);
    // Erase everything: both steps of its sheet (nothing is erased here).
    await page.goto("/settings/backup");
    await page.getByRole("button", { name: "Erase Everything…" }).click();
    const erase = page.getByRole("dialog", { name: "Erase Everything?" });
    await expect(erase.getByText("Keep a copy first?")).toBeVisible();
    await shot(page, `settings-erase-copy-${scheme}`);
    await erase.getByRole("button", { name: "I Have a Copy" }).click();
    await expect(erase.getByLabel("Household password")).toBeVisible();
    await shot(page, `settings-erase-password-${scheme}`);
    await erase.getByRole("button", { name: "Keep Everything" }).click();
    await expect(erase).toBeHidden();
    await page.goto("/install?from=more");
    await shot(page, `install-${scheme}`);
    await page.context().clearCookies();
    await page.goto("/sign-in");
    await expect(page.getByLabel("Household password")).toBeVisible();
    await shot(page, `sign-in-${scheme}`);
  }
});

test("a phone's calendar", async ({ page, isMobile }) => {
  test.skip(!isMobile, "phones");
  test.setTimeout(240_000);
  await moveClock(page, STOPS[1]?.at ?? "");
  await seed(page.request);
  await signInPhone(page);
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Up next" })).toBeVisible();
    await shot(page, `today-events-${scheme}`);
    await page.getByRole("link", { name: "Calendar" }).click();
    for (const mode of ["Week", "Day", "Agenda", "Month"]) {
      await page.getByRole("button", { name: mode, exact: true }).click();
      await shot(page, `calendar-${mode.toLowerCase()}-${scheme}`);
    }
    await page.getByRole("button", { name: "Week", exact: true }).click();
    await page.getByRole("button", { name: /^Soccer practice, .*Thursday October 8/ }).click();
    await expect(page.getByRole("dialog", { name: "Soccer practice" })).toBeVisible();
    await shot(page, `calendar-event-${scheme}`);
    await page
      .getByRole("dialog", { name: "Soccer practice" })
      .getByRole("button", { name: "Close" })
      .click();
    await page.getByRole("button", { name: "Add", exact: true }).click();
    await page
      .getByRole("dialog", { name: "Add" })
      .getByLabel("What, when, who")
      .fill("Dentist Thu 2:30pm Mia");
    await shot(page, `calendar-add-${scheme}`);
    await page.getByRole("dialog", { name: "Add" }).getByRole("button", { name: "Close" }).click();
    await page.getByRole("button", { name: "October 2026" }).click();
    await page.getByRole("dialog", { name: "Find a day" }).getByLabel("Search").fill("soccer");
    await shot(page, `calendar-find-${scheme}`);
    await page
      .getByRole("dialog", { name: "Find a day" })
      .getByRole("button", { name: "Close" })
      .click();
  }
  // Synced calendars: an account on Calendars & Accounts, and every way to add one.
  await scriptedAccount(page.request);
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/settings/calendars");
    await expect(page.getByRole("heading", { name: "Accounts", exact: true })).toBeVisible();
    await shot(page, `settings-calendars-accounts-${scheme}`);
    await page.getByRole("button", { name: "Default calendar: Home" }).click();
    await expect(page.getByRole("radiogroup", { name: "Default calendar" })).toBeVisible();
    await shot(page, `settings-calendars-default-${scheme}`);
    await page.getByRole("button", { name: "Default calendar: Home" }).click();
    await page.getByRole("button", { name: "Edit Home" }).click();
    const homeSheet = page.getByRole("dialog", { name: "Edit Home" });
    await expect(homeSheet).toContainText("so it stays");
    await shot(page, `settings-calendar-stays-${scheme}`);
    await homeSheet.getByRole("button", { name: "Close" }).click();
    await expect(homeSheet).toBeHidden();
    // An account's sheet, and its calendar's page inside it.
    await page.getByRole("button", { name: "Edit Test server" }).click();
    await expect(page.getByRole("dialog", { name: "Edit Test server" })).toBeVisible();
    await shot(page, `settings-calendars-account-${scheme}`);
    await page.getByRole("button", { name: "Edit School" }).click();
    const school = page.getByRole("dialog", { name: "Edit School" });
    await expect(school).toBeVisible();
    await shot(page, `settings-calendars-account-calendar-${scheme}`);
    await school.getByRole("button", { name: "Close" }).click();
    await expect(school).toBeHidden();
    const flows: [string, string][] = [
      ["Apple", "apple"],
      ["Google", "google"],
      ["Holidays", "holidays"],
      ["Another calendar", "address"],
    ];
    for (const [choice, name] of flows) {
      await page.getByRole("button", { name: "Add an Account" }).click();
      const sheet = page.getByRole("dialog");
      if (name === "apple") await shot(page, `add-account-${scheme}`);
      await sheet.getByRole("button", { name: new RegExp(`^${choice}`) }).click();
      await shot(page, `add-${name}-${scheme}`);
      if (name === "google") {
        await sheet.getByRole("button", { name: /^Share with a Sunroom helper/ }).click();
        await shot(page, `add-google-helper-${scheme}`);
      }
      await sheet.getByRole("button", { name: "Close" }).click();
      await expect(sheet).toBeHidden();
    }
    // Sign in with Google: the step asks for the app's keys itself (ADR 0030), then keeps them.
    await page.getByRole("button", { name: "Add an Account" }).click();
    const google = page.getByRole("dialog");
    await google.getByRole("button", { name: /^Google/ }).click();
    await google.getByRole("button", { name: /^Sign in with Google/ }).click();
    const save = google.getByRole("button", { name: "Save Keys and Continue" });
    await save.scrollIntoViewIfNeeded();
    await shot(page, `add-google-signin-keys-${scheme}`);
    await google.getByLabel("Google app's client ID").fill("sample-id.apps.example.com");
    await google.getByLabel("Google app's client secret").fill("sample-secret-0001");
    await save.click();
    const signIn = google.getByRole("button", { name: "Sign in with Google" });
    await signIn.scrollIntoViewIfNeeded();
    await shot(page, `add-google-signin-${scheme}`);
    await google.getByRole("button", { name: "Remove Keys" }).click();
    await expect(save).toBeVisible();
    await google.getByRole("button", { name: "Close" }).click();
    await expect(google).toBeHidden();
  }
});

test("a phone's account steps", async ({ page, isMobile }) => {
  test.skip(!isMobile, "phones");
  test.setTimeout(240_000);
  await seed(page.request);
  await signInPhone(page);
  const flows: [string, string[]][] = [
    ["apple", ["Apple"]],
    ["google-address", ["Google", "Paste the secret address"]],
    ["google-helper", ["Google", "Share with a Sunroom helper"]],
  ];
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/settings/calendars");
    for (const [name, choices] of flows) {
      await page.getByRole("button", { name: "Add an Account" }).click();
      const sheet = page.getByRole("dialog");
      for (const choice of choices) {
        await sheet.getByRole("button", { name: new RegExp(`^${choice}`) }).click();
      }
      // One shot per step, with its drawing in the middle of the sheet.
      const steps = sheet.locator("ol > li");
      await expect(steps.first().locator("svg").first()).toBeVisible();
      const count = await steps.count();
      for (let step = 0; step < count; step += 1) {
        await steps.nth(step).evaluate((item) => {
          item.scrollIntoView({ block: "center" });
        });
        await shot(page, `add-${name}-step-${String(step + 1)}-${scheme}`);
      }
      await sheet.getByRole("button", { name: "Close" }).click();
      await expect(sheet).toBeHidden();
    }
  }
});

test("empty rooms: Lists, Tasks and Photos", async ({ page, request }, testInfo) => {
  const name = testInfo.project.name;
  test.skip(name === "phone-chromium", "the wall, a phone and a laptop");
  test.setTimeout(120_000);
  await moveClock(page, STOPS[1]?.at ?? "");
  await seed(page.request);
  // Empty the three rooms as a parent: no lists, no tasks, no children (whose stars give them
  // a column), no photos (ADR 0032's empty rooms).
  const parent = await request.post("/api/auth/login", {
    headers: CSRF,
    data: { password: PASSWORD },
  });
  expect(parent.ok()).toBe(true);
  const ids = async (path: string) =>
    ((await (await request.get(path)).json()) as { id: string }[]).map((item) => item.id);
  for (const id of await ids("/api/lists")) {
    expect((await request.delete(`/api/lists/${id}`, { headers: CSRF })).ok()).toBe(true);
  }
  for (const id of await ids("/api/chores")) {
    expect((await request.delete(`/api/chores/${id}`, { headers: CSRF })).ok()).toBe(true);
  }
  const members = (await (await request.get("/api/members")).json()) as {
    id: string;
    role: string;
  }[];
  for (const kid of members.filter((member) => member.role === "kid")) {
    const archived = await request.post(`/api/members/${kid.id}/archive`, { headers: CSRF });
    expect(archived.ok()).toBe(true);
  }
  const library = (await (await request.get("/api/photos?kind=library")).json()) as {
    photos: { id: string }[];
  };
  for (const photo of library.photos) {
    expect((await request.delete(`/api/photos/${photo.id}`, { headers: CSRF })).ok()).toBe(true);
  }
  if (name.startsWith("display")) {
    const paired = await page.request.post("/api/auth/kiosk/pair-with-password", {
      headers: CSRF,
      data: { password: PASSWORD, label: "Wall screen" },
    });
    expect(paired.status()).toBe(200);
  } else {
    await signInPhone(page);
  }
  for (const theme of ["light", "dark"]) {
    await change(page, { theme });
    for (const [room, path] of [
      ["lists", "/lists"],
      ["tasks", "/chores"],
      ["photos", "/photos"],
    ] as const) {
      await page.goto(path);
      await expect(page.locator("[data-empty]")).toBeVisible();
      await shot(page, `${room}-empty-${theme}`);
    }
  }
});

test("the wall's lists and chores", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("display"), "the wall screen");
  test.setTimeout(240_000);
  await moveClock(page, STOPS[1]?.at ?? "");
  await seed(page.request);
  const paired = await page.request.post("/api/auth/kiosk/pair-with-password", {
    headers: CSRF,
    data: { password: PASSWORD, label: "Wall screen" },
  });
  expect(paired.status()).toBe(200);
  for (const theme of ["light", "dark"]) {
    await change(page, { theme });
    await page.goto("/lists");
    await expect(page.getByRole("heading", { name: "Lists", level: 1 })).toBeVisible();
    await shot(page, `lists-${theme}`);
    await page.getByRole("link", { name: /^Groceries/ }).click();
    await expect(page.getByRole("heading", { name: "Groceries", level: 1 })).toBeVisible();
    await shot(page, `lists-groceries-${theme}`);
    await page.goto("/chores");
    await expect(page.getByRole("heading", { name: "Tasks", level: 1 })).toBeVisible();
    await shot(page, `chores-${theme}`);
    await page.getByRole("checkbox", { name: /^Water the plants/ }).click();
    await expect(page.getByRole("group", { name: "Who did it?" })).toBeVisible();
    await shot(page, `chores-who-did-it-${theme}`);
    await page.getByRole("button", { name: "Cancel" }).click();
    await page.getByRole("button", { name: "This Week", exact: true }).click();
    await shot(page, `chores-week-${theme}`);
    await page.getByRole("banner").getByRole("button", { name: "All Tasks" }).click();
    await expect(
      page.getByRole("region", { name: "Mia", exact: true }).getByText(/^\d+ tasks?$/),
    ).toBeVisible();
    await shot(page, `chores-all-${theme}`);
    await page.getByRole("link", { name: "Stars & Rewards" }).click();
    await expect(page.getByRole("heading", { name: "Stars & Rewards", level: 1 })).toBeVisible();
    await shot(page, `chores-rewards-${theme}`);
    await page.goto("/display");
    await pickView(page, "People");
    await shot(page, `chores-people-${theme}`);
    await page.getByRole("button", { name: "Add", exact: true }).click();
    const add = page.getByRole("dialog", { name: "Add" });
    await add.getByRole("button", { name: "Task", exact: true }).click();
    await shot(page, `add-task-${theme}`);
    await add.getByRole("button", { name: "Item", exact: true }).click();
    await shot(page, `add-item-${theme}`);
    await add.getByRole("button", { name: "Close" }).click();
  }
  // Bedtime: Leo's routine in his column, then the runner and its finish.
  await change(page, { theme: "auto" });
  await moveClock(page, "2026-10-07T23:45:00Z");
  await page.goto("/chores");
  await expect(page.getByRole("button", { name: "Start" })).toBeVisible();
  await shot(page, "chores-bedtime");
  await page.getByRole("button", { name: "Start" }).click();
  const runner = page.getByRole("dialog", { name: "Leo's bedtime routine" });
  await expect(runner).toContainText("Pajamas on");
  await shot(page, "routine-step");
  for (let step = 0; step < 5; step += 1) {
    await runner.getByRole("button", { name: "Done", exact: true }).click();
  }
  await expect(runner).toContainText("All done, Leo!");
  await shot(page, "routine-finished");
});

test("the wall's meals, countdowns, photos and screensaver", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("display"), "the wall screen");
  test.setTimeout(240_000);
  await moveClock(page, STOPS[1]?.at ?? "");
  await seed(page.request);
  const paired = await page.request.post("/api/auth/kiosk/pair-with-password", {
    headers: CSRF,
    data: { password: PASSWORD, label: "Wall screen" },
  });
  expect(paired.status()).toBe(200);
  // The pretend Immich (ADR 0036): its photos come first in the Photos room, so the viewer
  // shows "From Immich".
  const library = await page.request.post("/api/screensaver/_test/library", {
    headers: CSRF,
    data: {},
  });
  expect(library.ok()).toBe(true);
  for (const theme of ["light", "dark"]) {
    await change(page, { theme });
    await page.goto("/meals");
    await expect(page.getByRole("heading", { name: "Meals", level: 1 })).toBeVisible();
    await shot(page, `meals-${theme}`);
    await page.getByRole("table").getByRole("button", { name: /Tacos/ }).click();
    await shot(page, `meals-a-meal-${theme}`);
    await page
      .getByRole("dialog", { name: /Tacos/ })
      .getByRole("button", { name: "Close" })
      .click();
    await page.getByRole("link", { name: "Saved meals" }).click();
    await expect(page.getByRole("heading", { name: "Saved meals", level: 1 })).toBeVisible();
    await expect(page.getByRole("button", { name: /Grilled cheese and soup/ })).toBeVisible();
    await shot(page, `meals-saved-${theme}`);
    await page.goto("/countdowns");
    await expect(page.getByRole("heading", { name: "Countdowns", level: 1 })).toBeVisible();
    await shot(page, `countdowns-${theme}`);
    await page.goto("/photos");
    await expect(page.getByRole("heading", { name: "Photos", level: 1 })).toBeVisible();
    await shot(page, `photos-${theme}`);
    await page.getByRole("list", { name: "Photos" }).getByRole("button").first().click();
    await expect(page.getByRole("dialog", { name: "Photo" }).locator("img")).toHaveJSProperty(
      "complete",
      true,
    );
    await shot(page, `photos-one-${theme}`);
    await page.getByRole("button", { name: "Close" }).click();
    // Photo Libraries: the row, Add a Library, and a library's own panel.
    await page.goto("/settings/screensaver");
    await expect(page.getByRole("button", { name: "Edit Immich" })).toBeVisible();
    await page.getByRole("button", { name: "Add a Library" }).click();
    await expect(page.getByRole("dialog", { name: "Add a Library" })).toBeVisible();
    await shot(page, `settings-screensaver-add-library-${theme}`);
    await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
    await page.getByRole("button", { name: "Edit Immich" }).click();
    await expect(page.getByRole("dialog", { name: "Immich" })).toContainText("What to Show");
    await shot(page, `settings-screensaver-library-${theme}`);
    await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
    await page.goto("/photos");
    await page.getByRole("button", { name: "Start Screensaver" }).click();
    const saver = page.getByRole("button", { name: "Photos are showing. Tap to go back." });
    await expect(saver).toBeVisible();
    await shot(page, `screensaver-${theme}`);
    await saver.click();
    await expect(saver).toHaveCount(0);
    await page.goto("/display");
    await page
      .getByRole("button", { name: /^The weather:/ })
      .first()
      .click();
    await shot(page, `weather-${theme}`);
    await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
    await page.getByRole("button", { name: "Add", exact: true }).click();
    const add = page.getByRole("dialog", { name: "Add" });
    await add.getByRole("button", { name: "Meal", exact: true }).click();
    await shot(page, `add-meal-${theme}`);
    await add.getByRole("button", { name: "Countdown", exact: true }).click();
    await shot(page, `add-countdown-${theme}`);
    await add.getByRole("button", { name: "Close" }).click();
  }
  // Dinner on the board, and Night with tomorrow's first event under the clock.
  await change(page, { theme: "auto" });
  const shown = await page.request.put("/api/plugins/meals/settings", {
    headers: CSRF,
    data: { values: { slots: ["dinner"], calendar_slots: ["dinner"] } },
  });
  expect(shown.ok()).toBe(true);
  await page.goto("/display");
  await expect(page.locator("[data-overlay=meals]").first()).toBeVisible();
  await shot(page, "board-dinners");
});

test("the screen's own pages (Sunroom Screen, ADR 0035)", async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("display"), "the wall screen");
  test.setTimeout(240_000);
  const agent = "http://127.0.0.1:4174";
  const change = { "X-Sunroom-Screen": "1" };
  const fake = async (data: Record<string, unknown>) => {
    const response = await page.request.post(`${agent}/api/screen/_test/fake`, {
      headers: change,
      data,
    });
    expect(response.status()).toBe(204);
  };
  await seed(page.request);
  // The pages take their theme from the screen's own clock: daytime, then evening.
  for (const [theme, at] of [
    ["light", "2026-10-07T14:00:00Z"],
    ["dark", "2026-10-08T01:30:00Z"],
  ] as const) {
    await page.clock.setFixedTime(new Date(at));
    const reset = await page.request.post(`${agent}/api/screen/_test/reset`, { headers: change });
    expect(reset.status()).toBe(204);
    await page.goto(`${agent}/`);
    await expect(page.getByRole("radio", { name: "On This Computer" })).toBeChecked();
    await expect(page.getByRole("button", { name: "Continue" })).toBeVisible();
    await shot(page, `screen-welcome-${theme}`);
    await fake({ run: "hold" });
    await page.goto(`${agent}/here`);
    await expect(page.getByRole("main").getByRole("status")).toContainText("Downloading Sunroom…");
    await shot(page, `screen-here-${theme}`);
    await page.goto(`${agent}/find`);
    await expect(page.getByText("A Sunroom", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Look Again" })).toBeVisible();
    await shot(page, `screen-find-${theme}`);
    // An address typed and checked: Found, and Use This Sunroom beside it (ADR 0042).
    await page.getByLabel(/^Sunroom address/).fill("http://127.0.0.1:4173");
    await page.getByLabel(/^Sunroom address/).press("Enter");
    await expect(page.getByRole("button", { name: "Use This Sunroom" }).last()).toBeVisible();
    await shot(page, `screen-find-found-${theme}`);
    await fake({ offline: true });
    await page.goto(`${agent}/wifi`);
    await expect(page.getByRole("button", { name: /^SampleStreet-5G/ })).toBeVisible();
    await shot(page, `screen-wifi-${theme}`);
    await fake({ sunroom: "http://127.0.0.1:9" });
    await page.goto(`${agent}/opening`);
    await expect(page.getByRole("heading", { name: "Opening Sunroom…" })).toBeVisible();
    await shot(page, `screen-opening-${theme}`);
    await page.goto(`${agent}/cant-reach`);
    await expect(page.getByRole("heading", { name: "Can’t Reach Sunroom" })).toBeVisible();
    await shot(page, `screen-cant-reach-${theme}`);
    await page.goto(`${agent}/settings`);
    await expect(page.getByRole("heading", { name: "This Screen", level: 1 })).toBeVisible();
    await shot(page, `screen-settings-${theme}`);
  }
});

test("Settings → This Screen on a wall run by Sunroom Screen (ADR 0035)", async ({
  page,
}, testInfo) => {
  test.skip(!testInfo.project.name.startsWith("display"), "the wall screen");
  test.setTimeout(240_000);
  const agent = "http://127.0.0.1:4174";
  const screenChange = { "X-Sunroom-Screen": "1" };
  await moveClock(page, STOPS[1]?.at ?? "");
  // No parent PIN, as the wall's other shots: a paired wall may then change the theme itself.
  await seed(page.request);
  const reset = await page.request.post(`${agent}/api/screen/_test/reset`, {
    headers: screenChange,
  });
  expect(reset.status()).toBe(204);
  // The pretend screen shows this test server, so it answers the wall page's calls (CORS).
  const shows = await page.request.post(`${agent}/api/screen/_test/fake`, {
    headers: screenChange,
    data: { sunroom: new URL(testInfo.project.use.baseURL ?? "").origin },
  });
  expect(shows.status()).toBe(204);
  const paired = await page.request.post("/api/auth/kiosk/pair-with-password", {
    headers: CSRF,
    data: { password: PASSWORD, label: "Wall screen" },
  });
  expect(paired.status()).toBe(200);
  for (const theme of ["light", "dark"] as const) {
    await change(page, { theme });
    await page.goto("/display?dimmer=page&screen=4174");
    await expect(page.getByRole("region", { name: "This Week" })).toBeVisible();
    await page.getByRole("button", { name: "Settings" }).click();
    await page
      .getByRole("navigation", { name: "Settings" })
      .getByRole("link", { name: "This Screen", exact: true })
      .click();
    await expect(page.getByRole("heading", { name: "This Screen", level: 2 })).toBeVisible();
    await expect(page.getByRole("button", { name: "Restart" })).toBeVisible();
    await shot(page, `settings-this-screen-${theme}`);
  }
});

test("a phone's lists and chores", async ({ page, isMobile }) => {
  test.skip(!isMobile, "phones");
  test.setTimeout(240_000);
  await moveClock(page, STOPS[1]?.at ?? "");
  await seed(page.request);
  await signInPhone(page, "Mia");
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Up next" })).toBeVisible();
    await shot(page, `today-chores-${scheme}`);
    await page.getByRole("link", { name: "Lists" }).click();
    await expect(page.getByRole("heading", { name: "Lists", level: 1 })).toBeVisible();
    await shot(page, `lists-${scheme}`);
    await page.getByRole("link", { name: /^Groceries/ }).click();
    await expect(page.getByRole("heading", { name: "Groceries", level: 1 })).toBeVisible();
    await shot(page, `lists-groceries-${scheme}`);
    await page.getByRole("link", { name: "Tasks" }).click();
    await expect(page.getByRole("heading", { name: "Tasks", level: 1 })).toBeVisible();
    await shot(page, `chores-${scheme}`);
    await page.getByRole("button", { name: "All Tasks" }).click();
    await expect(page.getByRole("button", { name: /^Mia · \d+ tasks?$/ })).toBeVisible();
    await shot(page, `chores-all-${scheme}`);
    await page.getByRole("link", { name: "Stars & Rewards" }).click();
    await expect(page.getByRole("heading", { name: "Stars & Rewards", level: 1 })).toBeVisible();
    await shot(page, `chores-rewards-${scheme}`);
    await page.goto("/more");
    await expect(page.getByRole("heading", { name: "More", level: 1 })).toBeVisible();
    await shot(page, `more-${scheme}`);
    await page.getByRole("link", { name: "Meals" }).click();
    await expect(page.getByRole("heading", { name: "Meals", level: 1 })).toBeVisible();
    await shot(page, `meals-${scheme}`);
    await page.goto("/countdowns");
    await expect(page.getByRole("heading", { name: "Countdowns", level: 1 })).toBeVisible();
    await shot(page, `countdowns-${scheme}`);
    await page.goto("/photos");
    await expect(page.getByRole("heading", { name: "Photos", level: 1 })).toBeVisible();
    await shot(page, `photos-${scheme}`);
  }
});

test("a laptop", async ({ page }) => {
  test.skip(test.info().project.name !== "desktop", "a laptop");
  test.setTimeout(240_000);
  await seed(page.request);
  await page.goto("/sign-in");
  await shot(page, "sign-in");
  await signInPhone(page);
  for (const theme of ["light", "dark"]) {
    for (const stop of STOPS) {
      await moveClock(page, stop.at);
      await change(page, { theme });
      await page.reload();
      await expect(page.getByRole("region", { name: "This Week" })).toBeVisible();
      await shot(page, `board-${theme}-${stop.name}`);
    }
  }
  await change(page, { theme: "auto" });
  await page.getByRole("button", { name: "Settings" }).click();
  for (const { key, title } of PAGES) {
    // A page Needs Attention points at is marked (ADR 0034): its link says so to a screen reader.
    await page
      .getByRole("navigation", { name: "Settings" })
      .getByRole("link", { name: new RegExp(`^${escapeRegExp(title)}(, needs attention)?$`) })
      .click();
    await expect(page.getByRole("heading", { name: title, level: 2, exact: true })).toBeVisible();
    await shot(page, `settings-${key}`);
  }
  // A computer pairs a screen from Devices: it has no More.
  await page
    .getByRole("navigation", { name: "Settings" })
    .getByRole("link", { name: "Devices", exact: true })
    .click();
  await page.getByRole("button", { name: "Pair a Display" }).click();
  const pairing = page.getByRole("dialog", { name: "Pair a Display" });
  await expect(pairing).toBeVisible();
  await shot(page, "settings-pair-a-display");
  await pairing.getByRole("button", { name: "Close" }).click();
  await expect(pairing).toBeHidden();
  // A computer adds photos itself: the room's Add photos, and a person's Add a photo.
  await page
    .getByRole("navigation", { name: "Settings" })
    .getByRole("link", { name: "Family", exact: true })
    .click();
  await page.getByRole("button", { name: "Edit Mia" }).click();
  await expect(page.getByRole("dialog", { name: "Edit Mia" })).toBeVisible();
  await shot(page, "settings-change-a-person");
  await page.goto("/photos");
  await expect(page.getByRole("list", { name: "Photos" })).toBeVisible();
  await shot(page, "photos");
});
