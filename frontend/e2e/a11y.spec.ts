/**
 * Accessibility on every main screen (PLAN §14.6, UX §1 and §10): no serious or critical axe
 * findings, in light and dark, on the wall screen (landscape and portrait), phones and a laptop.
 * Every tap target is at least 56 px on the wall screen and 44 px on a phone, with 8 px between
 * neighbours on a line; no typing field is under 16 px. Lesser axe findings are printed.
 * Synthetic data only.
 */
import type { Page } from "@playwright/test";

import { check } from "./checks";
import {
  expect,
  PASSWORD,
  pickView,
  PIN,
  scriptedAccount,
  seed,
  signInPhone,
  test,
} from "./fixtures";

const SETTINGS = [
  "Family",
  "Features",
  "Calendars & Accounts",
  "Tasks",
  "Meals",
  "Photos & Screensaver",
  "Display",
  "Household",
  "Devices",
  "Recently Removed",
  "Backup",
  "Support Sunroom",
];
const CSRF = { "X-Sunroom": "1" };
// Wednesday, October 7, 2026, 10:00 AM in New York: the same week of events on every run.
const WEDNESDAY_10AM = "2026-10-07T14:00:00Z";

// The screens at rest: with Reduce Motion nothing is caught halfway through an animation, which
// axe would read as low contrast.
test.use({ reducedMotion: "reduce" });

/** An unpaired wall starts from the browser's own clock and moves to the test server's (10 AM:
 * light, midday) when its first answer comes back. Check once it has, or axe can catch the theme
 * half switched in the evening. */
async function onServerTime(page: Page): Promise<void> {
  await expect(page.locator("html")).toHaveAttribute("data-daypart", "midday");
}

/** Open a side panel or sheet with a button, check it, close it. */
async function sheet(page: Page, open: string, where: string): Promise<void> {
  await page.getByRole("button", { name: open }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await check(page, where);
  await dialog.getByRole("button", { name: "Close" }).click();
  await expect(dialog).toBeHidden();
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.beforeEach(async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    });

    test("the first-run wizard on a phone", async ({ page, isMobile }) => {
      test.skip(!isMobile, "phones");
      await page.goto("/setup");
      await expect(page.getByRole("heading", { name: "Welcome to Sunroom" })).toBeVisible();
      await check(page, "setup: welcome");
      await page.getByRole("button", { name: "Start" }).click();
      await expect(page.getByLabel("Household password")).toBeVisible();
      await check(page, "setup: password");
      await page.getByLabel("Household password").fill(PASSWORD);
      await page.getByRole("button", { name: "Next" }).click();
      await expect(page.getByRole("heading", { name: "Name your household" })).toBeVisible();
      await check(page, "setup: household");
      await page.getByLabel("Household name").fill("Sample Family");
      await page.getByRole("button", { name: "Next" }).click();
      await expect(page.getByRole("heading", { name: "Where’s home?" })).toBeVisible();
      await check(page, "setup: where's home");
      await page.getByLabel("Your city").fill("Sample");
      await expect(page.getByRole("list", { name: "Places" })).toBeVisible();
      await check(page, "setup: where's home, the places");
      await page.getByRole("button", { name: "Later" }).click();
      await expect(page.getByRole("heading", { name: "Who lives here?" })).toBeVisible();
      await check(page, "setup: people");
      await page.getByLabel("Your name").fill("Ana");
      await page.getByRole("button", { name: "Add Me" }).click();
      await expect(page.getByRole("button", { name: "Add", exact: true })).toBeVisible();
      await check(page, "setup: people, one added");
      await page.getByRole("button", { name: "Next", exact: true }).click();
      await expect(page.getByRole("heading", { name: "Set a parent PIN?" })).toBeVisible();
      await check(page, "setup: PIN");
      await page.getByRole("button", { name: "Later" }).click();
      await expect(page.getByRole("heading", { name: "Bring in your calendars" })).toBeVisible();
      await check(page, "setup: calendars");
      await page.getByRole("button", { name: "Add a Calendar" }).click();
      await expect(page.getByRole("dialog", { name: "Add an Account" })).toBeVisible();
      await check(page, "setup: add an account");
      await page.getByRole("dialog").getByRole("button", { name: "Close" }).click();
      await page.getByRole("button", { name: "Skip for Now" }).click();
      await expect(page.getByRole("heading", { name: "All done!" })).toBeVisible();
      await check(page, "setup: done");
    });

    test("a phone, signed in", async ({ page, request, isMobile }) => {
      test.skip(!isMobile, "phones");
      // Some forty checks, each an axe scan and two sweeps of the page: minutes on CI's runner.
      test.slow();
      await request.post("/api/_test/clock", { headers: CSRF, data: { set: WEDNESDAY_10AM } });
      await seed(request, { pin: PIN });
      await page.goto("/sign-in");
      await expect(page.getByLabel("Household password")).toBeVisible();
      await check(page, "sign in");
      await page.getByRole("button", { name: "Use a code from another device" }).click();
      await check(page, "sign in with a code");
      await signInPhone(page);
      await check(page, "today");
      await page.goto("/who?from=more");
      await expect(page.getByRole("heading", { name: "Who’s using this device?" })).toBeVisible();
      await check(page, "who's using this");
      await page.goto("/");
      await page.getByRole("link", { name: "Calendar" }).click();
      await expect(page.getByRole("group", { name: "Days" })).toBeVisible();
      await check(page, "calendar");
      await page.getByRole("button", { name: /^Vet, / }).click();
      await expect(page.getByRole("dialog", { name: "Vet" })).toBeVisible();
      await check(page, "calendar: event");
      await page
        .getByRole("dialog", { name: "Vet" })
        .getByRole("button", { name: "Close" })
        .click();
      await sheet(page, "Add", "calendar: add");
      for (const mode of ["Day", "Agenda", "Month"]) {
        await page.getByRole("button", { name: mode, exact: true }).click();
        await check(page, `calendar: ${mode.toLowerCase()}`);
      }
      await sheet(page, "October 2026", "calendar: month picker");
      await page.getByRole("link", { name: "Lists" }).click();
      await expect(page.getByRole("heading", { name: "Lists", level: 1 })).toBeVisible();
      await check(page, "lists");
      await page.getByRole("link", { name: /^Groceries/ }).click();
      await expect(page.getByRole("heading", { name: "Groceries", level: 1 })).toBeVisible();
      await check(page, "lists: groceries");
      await page.getByRole("button", { name: "Eggs" }).click();
      await expect(page.getByRole("dialog", { name: "Eggs" })).toBeVisible();
      await check(page, "lists: an item");
      await page
        .getByRole("dialog", { name: "Eggs" })
        .getByRole("button", { name: "Close" })
        .click();
      await page.getByRole("link", { name: "Tasks" }).click();
      await expect(page.getByRole("heading", { name: "Tasks", level: 1 })).toBeVisible();
      await check(page, "chores");
      await sheet(page, "Add", "chores: add");
      await page.getByRole("link", { name: "Stars & Rewards" }).click();
      await expect(page.getByRole("heading", { name: "Stars & Rewards", level: 1 })).toBeVisible();
      await check(page, "chores: stars and rewards");
      await page.getByRole("link", { name: "More" }).click();
      await expect(page.getByRole("heading", { name: "More", level: 1 })).toBeVisible();
      await check(page, "more");
      await page.getByRole("link", { name: "Meals" }).click();
      await expect(page.getByRole("heading", { name: "Meals", level: 1 })).toBeVisible();
      await check(page, "meals");
      await page.getByRole("button", { name: /Tacos/ }).click();
      await expect(page.getByRole("dialog", { name: /Tacos/ })).toBeVisible();
      await check(page, "meals: a meal");
      await page
        .getByRole("dialog", { name: /Tacos/ })
        .getByRole("button", { name: "Close" })
        .click();
      await page.getByRole("link", { name: "Saved meals" }).click();
      await expect(page.getByRole("heading", { name: "Saved meals", level: 1 })).toBeVisible();
      await check(page, "meals: saved meals");
      await page.goto("/countdowns");
      await expect(page.getByRole("heading", { name: "Countdowns", level: 1 })).toBeVisible();
      await check(page, "countdowns");
      await sheet(page, "Add Countdown", "countdowns: add");
      await page.goto("/photos");
      await expect(page.getByRole("heading", { name: "Photos", level: 1 })).toBeVisible();
      await check(page, "photos");
      await page.goto("/more");
      await expect(page.getByRole("heading", { name: "More", level: 1 })).toBeVisible();
      await page.getByRole("link", { name: "Pair a Display" }).click();
      await expect(page.getByRole("heading", { name: "Pair a Display", level: 1 })).toBeVisible();
      await check(page, "pair a display");
      await scriptedAccount(page.request);
      // The pretend Immich (ADR 0036), for its row and its panel.
      await page.request.post("/api/screensaver/_test/library", { headers: CSRF, data: {} });
      await page.goto("/settings");
      await expect(page.getByRole("heading", { name: "Settings", level: 1 })).toBeVisible();
      await check(page, "settings");
      for (const title of [...SETTINGS, "About"]) {
        await page.goto("/settings");
        await page.getByRole("main").getByRole("link", { name: title, exact: true }).click();
        await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
        await check(page, `settings: ${title}`);
        if (title === "Family") await sheet(page, "Edit Mia", "change a person");
        if (title === "Calendars & Accounts") {
          await sheet(page, "Add a Calendar", "add a calendar");
          await sheet(page, "Edit Test server", "an account");
        }
        if (title === "Devices") {
          await sheet(page, "Add a Device", "add a device");
          await sheet(page, "Pair a Display", "pair a display from Settings");
        }
        if (title === "Photos & Screensaver") {
          await sheet(page, "Add a Library", "add a photo library");
          await sheet(page, "Edit Immich", "a photo library");
        }
      }
      await page.goto("/install?from=more");
      await expect(
        page.getByRole("heading", { name: "Put Sunroom on your home screen" }),
      ).toBeVisible();
      await check(page, "install");
    });

    test("the wall screen, from first light to Settings", async ({ page, request }, testInfo) => {
      test.skip(!testInfo.project.name.startsWith("display"), "the wall screen");
      // Some forty checks, each an axe scan and two sweeps of the page: minutes on CI's runner.
      test.slow();
      await request.post("/api/_test/clock", { headers: CSRF, data: { set: WEDNESDAY_10AM } });
      await page.goto("/display");
      await expect(
        page.getByRole("heading", { name: "Set Up Sunroom", exact: true }),
      ).toBeVisible();
      await onServerTime(page);
      await check(page, "display: before setup");
      // Setting up on the wall itself (ADR 0039): its first step, on the wall's keyboard.
      await page.getByRole("button", { name: "Set Up Here" }).click();
      await page.getByLabel("Household password").click();
      await expect(page.getByRole("group", { name: "On-screen keyboard" })).toBeVisible();
      await check(page, "display: set up here");
      await page.getByRole("button", { name: "Back" }).click();
      await expect(
        page.getByRole("heading", { name: "Set Up Sunroom", exact: true }),
      ).toBeVisible();
      await seed(request, { pin: PIN });
      await page.reload();
      await expect(page.getByTestId("pair-code")).toBeVisible();
      await onServerTime(page);
      await check(page, "display: pair this screen");
      await page.getByRole("button", { name: "Type the household password here instead" }).click();
      await page.getByLabel("Household password").click();
      await expect(page.getByRole("group", { name: "On-screen keyboard" })).toBeVisible();
      await check(page, "display: password and keyboard");
      await page.getByLabel("Household password").fill(PASSWORD);
      await page.getByRole("button", { name: "Pair This Screen" }).click();
      await expect(page.getByRole("heading", { name: "Name this screen" })).toBeVisible();
      await check(page, "display: name this screen");
      await page.getByRole("button", { name: "Done" }).click();
      const board = page.getByRole("region", { name: "This Week" });
      await expect(board).toBeVisible();
      // A new household's board: the Week with Hours, the whole day (ADR 0042).
      await expect(page.locator("[data-hours] [data-now-line]")).toBeVisible();
      await check(page, "display: board");
      // Filter: its menu under the button. Checked with nobody chosen: a filter fades the
      // other people's chips on purpose (UX §10), which no contrast rule would pass.
      await page.getByRole("button", { name: "Filter", exact: true }).click();
      await expect(page.getByRole("menu", { name: "Filter" })).toBeVisible();
      await check(page, "display: the Filter menu");
      await page.getByRole("menuitemcheckbox", { name: "Mia" }).click();
      await page.getByRole("menuitemcheckbox", { name: "Leo" }).click();
      // Closed by its own button, not Escape: a key press would keep the wall's own keyboard
      // down for the next five seconds, and Add comes next.
      await page.getByRole("button", { name: "Filter: Mia, Leo" }).click();
      await expect(page.getByRole("menu")).toHaveCount(0);
      await page.getByRole("button", { name: "Filter: Mia, Leo" }).click();
      await page.getByRole("menuitemradio", { name: "Everyone" }).click();
      await expect(page.getByRole("menu")).toHaveCount(0);
      // Tips on (a parent's phone turns them on): the strip stays under the board from here.
      const parent = await request.post("/api/auth/login", {
        headers: CSRF,
        data: { password: PASSWORD },
      });
      expect(parent.ok()).toBe(true);
      const tips = await request.patch("/api/settings", {
        headers: CSRF,
        data: { show_tips: true },
      });
      expect(tips.ok()).toBe(true);
      await expect(page.locator("[data-tips]")).toBeVisible();
      await check(page, "display: board with a tip");
      await board.getByRole("button", { name: /^Soccer practice, .*Thursday/ }).click();
      await expect(page.getByRole("dialog", { name: "Soccer practice" })).toBeVisible();
      await check(page, "display: event");
      await page
        .getByRole("dialog", { name: "Soccer practice" })
        .getByRole("button", { name: "Close" })
        .click();
      await page.getByRole("button", { name: "Add", exact: true }).click();
      const add = page.getByRole("dialog", { name: "Add" });
      await add.getByLabel("What, when, who").fill("Dentist every Thu 2:30pm Mia");
      await check(page, "display: add an event");
      // The keyboard down, each row's picker opened in turn: the month, the hours, Custom.
      await page
        .getByRole("group", { name: "On-screen keyboard" })
        .getByRole("button", { name: "Done" })
        .click();
      await add.getByRole("button", { name: "Pick a date" }).click();
      await expect(add.getByRole("button", { name: "October 8" })).toBeVisible();
      await check(page, "display: add, the month grid");
      await add.getByRole("button", { name: "Pick a date" }).click();
      await add.getByRole("button", { name: /^Time: / }).click();
      await expect(add.getByRole("group", { name: "Time: hour" })).toBeVisible();
      await check(page, "display: add, the time picker");
      await add.getByRole("button", { name: "Done", exact: true }).click();
      await add.getByRole("button", { name: /^How long: / }).click();
      await expect(add.getByRole("radiogroup", { name: "How long" })).toBeVisible();
      await check(page, "display: add, how long");
      await add.getByRole("radio", { name: "2 hours" }).click();
      await add.getByRole("button", { name: /^Repeats: / }).click();
      await expect(add.getByRole("radiogroup", { name: "Repeats" })).toBeVisible();
      await check(page, "display: add, repeats");
      await add.getByRole("radio", { name: "Custom…" }).click();
      await expect(add.getByRole("group", { name: "On", exact: true })).toBeVisible();
      await check(page, "display: add, the custom repeat");
      await add.getByRole("button", { name: "Done", exact: true }).click();
      await add.getByRole("button", { name: "More…" }).click();
      await expect(add.getByLabel("Where")).toBeVisible();
      await check(page, "display: add, more");
      await add.getByRole("button", { name: "Close" }).click();
      // Gone before the views below: Custom's "Day" and "Month" would answer to their names.
      await expect(add).toBeHidden();
      for (const view of ["Day", "Month", "People", "Today"]) {
        await pickView(page, view);
        await check(page, `display: ${view}`);
      }
      // The View menu, open, at every width (ADR 0042): six rows, each one target.
      await page.getByRole("button", { name: "View: Today" }).click();
      await expect(page.getByRole("menu", { name: "View" })).toBeVisible();
      await expect(page.getByRole("menuitemradio", { name: "Today" })).toBeFocused();
      await check(page, "display: the View menu");
      await page.getByRole("menuitemradio", { name: "Week", exact: true }).click();
      await expect(page.getByRole("menu", { name: "View" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "View: Week" })).toBeFocused();
      // Hours zoomed in all the way: Zoom in stops when a 15-minute event would fill a chip.
      const zoomIn = page.getByRole("button", { name: "Zoom in" });
      for (let tap = 0; tap < 12 && (await zoomIn.isEnabled()); tap++) await zoomIn.click();
      await expect(zoomIn).toBeDisabled();
      await check(page, "display: hours zoomed in");
      await page.getByRole("button", { name: "Fit the day" }).click();
      // The other layout, Agenda.
      await page.getByRole("button", { name: "Agenda", exact: true }).click();
      await expect(page.locator("[data-hours]")).toHaveCount(0);
      await check(page, "display: agenda");
      await page.getByRole("link", { name: "Lists" }).click();
      await expect(page.getByRole("heading", { name: "Lists", level: 1 })).toBeVisible();
      await check(page, "display: lists");
      await page.getByRole("link", { name: /^Groceries/ }).click();
      await expect(page.getByRole("heading", { name: "Groceries", level: 1 })).toBeVisible();
      await check(page, "display: groceries");
      await page.getByRole("link", { name: "Tasks" }).click();
      await expect(page.getByRole("heading", { name: "Tasks", level: 1 })).toBeVisible();
      await check(page, "display: chores");
      await page.getByRole("checkbox", { name: /^Empty the dishwasher/ }).click();
      await expect(page.getByRole("group", { name: "Who did it?" })).toBeVisible();
      await check(page, "display: who did it");
      await page.getByRole("button", { name: "Cancel" }).click();
      await page.getByRole("button", { name: "This Week", exact: true }).click();
      await check(page, "display: chores this week");
      await page.getByRole("link", { name: "Stars & Rewards" }).click();
      await expect(page.getByRole("heading", { name: "Stars & Rewards", level: 1 })).toBeVisible();
      await check(page, "display: stars and rewards");
      await page.getByRole("link", { name: "Meals" }).click();
      await expect(page.getByRole("heading", { name: "Meals", level: 1 })).toBeVisible();
      await check(page, "display: meals");
      await page.getByRole("table").getByRole("button", { name: /Tacos/ }).click();
      await check(page, "display: a meal");
      await page
        .getByRole("dialog", { name: /Tacos/ })
        .getByRole("button", { name: "Close" })
        .click();
      await page.getByRole("link", { name: "Saved meals" }).click();
      await expect(page.getByRole("heading", { name: "Saved meals", level: 1 })).toBeVisible();
      await check(page, "display: saved meals");
      await page.getByRole("link", { name: "Countdowns" }).click();
      await expect(page.getByRole("heading", { name: "Countdowns", level: 1 })).toBeVisible();
      await check(page, "display: countdowns");
      await page.getByRole("link", { name: "Photos" }).click();
      await expect(page.getByRole("heading", { name: "Photos", level: 1 })).toBeVisible();
      await check(page, "display: photos");
      await page.getByRole("button", { name: "Add", exact: true }).click();
      await page
        .getByRole("dialog", { name: "Add" })
        .getByRole("button", { name: "Meal", exact: true })
        .click();
      await check(page, "display: add a meal");
      await page
        .getByRole("dialog", { name: "Add" })
        .getByRole("button", { name: "Countdown", exact: true })
        .click();
      await check(page, "display: add a countdown");
      await page
        .getByRole("dialog", { name: "Add" })
        .getByRole("button", { name: "Close" })
        .click();
      await page.getByRole("link", { name: "Tasks" }).click();
      await page.getByRole("button", { name: "Add", exact: true }).click();
      await page
        .getByRole("dialog", { name: "Add" })
        .getByRole("button", { name: "Task", exact: true })
        .click();
      await check(page, "display: add a chore");
      await page
        .getByRole("dialog", { name: "Add" })
        .getByRole("button", { name: "Item", exact: true })
        .click();
      await check(page, "display: add an item");
      await page
        .getByRole("dialog", { name: "Add" })
        .getByRole("button", { name: "Close" })
        .click();
      await page.getByRole("button", { name: "Settings" }).click();
      await expect(page.getByRole("dialog", { name: "Parent PIN" })).toBeVisible();
      await check(page, "display: PIN");
      const pin = page.getByRole("dialog", { name: "Parent PIN" });
      for (const digit of PIN) await pin.getByRole("button", { name: digit, exact: true }).click();
      await expect(pin).toBeHidden();
      await scriptedAccount(page.request); // the PIN's grant makes this screen a parent's for now
      await page.request.post("/api/screensaver/_test/library", { headers: CSRF, data: {} });
      for (const title of [...SETTINGS, "About"]) {
        await page
          .getByRole("navigation", { name: "Settings" })
          .getByRole("link", { name: title, exact: true })
          .click();
        // Exact: the Today panel beside Settings has headings of its own ("Tasks Today").
        await expect(
          page.getByRole("heading", { name: title, level: 2, exact: true }),
        ).toBeVisible();
        await check(page, `display settings: ${title}`);
        if (title === "Family") await sheet(page, "Edit Mia", "display: change a person");
        if (title === "Calendars & Accounts") {
          await sheet(page, "Edit Kids' activities", "display: change a calendar");
          await sheet(page, "Add an Account", "display: add an account");
          await sheet(page, "Edit Test server", "display: an account");
        }
        if (title === "Photos & Screensaver") {
          await sheet(page, "Add a Library", "display: add a photo library");
          await sheet(page, "Edit Immich", "display: a photo library");
        }
        // The header's Sunroom Discord: a code to scan, with a name (ADR 0042).
        if (title === "Support Sunroom") {
          await sheet(page, "Sunroom's Discord", "display: the Sunroom Discord");
        }
      }
    });

    test("the wall screen at the Small text size", async ({ page, request }, testInfo) => {
      test.skip(!testInfo.project.name.startsWith("display"), "the wall screen");
      await request.post("/api/_test/clock", { headers: CSRF, data: { set: WEDNESDAY_10AM } });
      await seed(request);
      const paired = await page.request.post("/api/auth/kiosk/pair-with-password", {
        headers: CSRF,
        data: { password: PASSWORD, label: "Wall screen" },
      });
      expect(paired.ok()).toBe(true);
      // No PIN in this household: the wall may change its own settings.
      const small = await page.request.patch("/api/settings", {
        headers: CSRF,
        data: { text_size: "small", theme: scheme },
      });
      expect(small.ok()).toBe(true);
      await page.goto("/display");
      const board = page.getByRole("region", { name: "This Week" });
      await expect(board).toBeVisible();
      await expect(page.locator("html")).toHaveAttribute("data-text-size", "small");
      // Hours, a new household's layout (ADR 0042), then Agenda.
      await expect(page.locator("[data-hours] [data-now-line]")).toBeVisible();
      await check(page, "display at Small: hours");
      await page.getByRole("button", { name: "Agenda", exact: true }).click();
      await expect(page.locator("[data-hours]")).toHaveCount(0);
      await check(page, "display at Small: agenda");
      await page.getByRole("button", { name: "Add", exact: true }).click();
      const add = page.getByRole("dialog", { name: "Add" });
      await add.getByLabel("What, when, who").fill("Dentist every Thu 2:30pm Mia");
      await check(page, "display at Small: add");
      await add.getByRole("button", { name: "Close" }).click();
      await page.getByRole("link", { name: "Tasks" }).click();
      await expect(page.getByRole("heading", { name: "Tasks", level: 1 })).toBeVisible();
      await check(page, "display at Small: tasks");
      await page.getByRole("link", { name: "Lists" }).click();
      await page.getByRole("link", { name: /^Groceries/ }).click();
      await expect(page.getByRole("heading", { name: "Groceries", level: 1 })).toBeVisible();
      await check(page, "display at Small: groceries");
      await page.getByRole("button", { name: "Settings" }).click();
      await page
        .getByRole("navigation", { name: "Settings" })
        .getByRole("link", { name: "Display", exact: true })
        .click();
      await expect(page.getByRole("heading", { name: "Display", level: 2 })).toBeVisible();
      await check(page, "display at Small: Settings → Display");
    });

    test("a laptop", async ({ page, request }, testInfo) => {
      test.skip(testInfo.project.name !== "desktop", "a laptop");
      // The board's "Up next" needs events still to come today: the server's 10 AM.
      await request.post("/api/_test/clock", { headers: CSRF, data: { set: WEDNESDAY_10AM } });
      await seed(request);
      await page.goto("/sign-in");
      await expect(page.getByLabel("Household password")).toBeVisible();
      await check(page, "laptop: sign in");
      await signInPhone(page);
      await expect(page.getByRole("region", { name: "This Week" })).toBeVisible();
      await check(page, "laptop: board");
      await page.getByRole("button", { name: "Settings" }).click();
      for (const title of [...SETTINGS, "About"]) {
        await page
          .getByRole("navigation", { name: "Settings" })
          .getByRole("link", { name: title, exact: true })
          .click();
        await expect(
          page.getByRole("heading", { name: title, level: 2, exact: true }),
        ).toBeVisible();
        await check(page, `laptop settings: ${title}`);
        // A computer has no More: it pairs a screen from here.
        if (title === "Devices") {
          await sheet(page, "Pair a Display", "laptop: pair a display");
        }
      }
    });
  });
}
